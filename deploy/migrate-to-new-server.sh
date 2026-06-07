#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# migrate-to-new-server.sh — безопасный перенос проекта (mgp ИЛИ lk) на новый
# сервер (например, другой аккаунт Timeweb).
#
# ГЛАВНЫЙ ПРИНЦИП: НЕ ПОТЕРЯТЬ ДИАЛОГИ.
#   • старый сервер только ЧИТАЕТСЯ (pg_dump), ничего на нём не меняем/не гасим;
#   • дамп БД скачивается локально и остаётся у тебя как артефакт;
#   • на новом сервере БД восстанавливается в пустой контейнер ДО старта backend;
#   • в конце сверяются количества conversations/messages СТАРЫЙ vs НОВЫЙ —
#     если не совпало, скрипт громко ругается.
#
# Запуск с ЛОКАЛЬНОЙ машины (нужен SSH-доступ к обоим серверам):
#   ./deploy/migrate-to-new-server.sh --project mgp --new root@NEW_IP
#   ./deploy/migrate-to-new-server.sh --project lk  --new root@NEW_IP --old root@5.129.204.194
#
# Фазы можно гонять по отдельности:
#   --only backup     только снять дамп со старого и скачать (безопасно, делай первым)
#   --only provision  поднять новый сервер + код + .env + restore + deploy
#   --only verify     только сверить количества строк
# По умолчанию (без --only) выполняются все фазы последовательно.
# ─────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

PROJECT=""              # mgp | lk
OLD_SSH=""              # user@host старого сервера
NEW_SSH=""              # user@host нового сервера (обычно root@NEW_IP на старте)
ONLY=""                 # backup | provision | verify | (пусто = всё)
ASSUME_YES="${MIGRATE_YES:-0}"
WORKDIR="${MIGRATE_WORKDIR:-$HOME/mgp_lk_migration}"

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2;;
    --old)     OLD_SSH="$2"; shift 2;;
    --new)     NEW_SSH="$2"; shift 2;;
    --only)    ONLY="$2"; shift 2;;
    --yes)     ASSUME_YES=1; shift;;
    *) echo "Неизвестный аргумент: $1"; exit 2;;
  esac
done

# ─── профили проектов ────────────────────────────────────────────────────────
case "$PROJECT" in
  mgp)
    : "${OLD_SSH:=mgpadmin@72.56.88.193}"
    APP_DIR="/opt/mgp"
    REPO="https://github.com/rebekaee1/mgp_v2.git"
    DEPLOY_CMD="./deploy/deploy-runtime.sh"
    ;;
  lk)
    : "${OLD_SSH:=root@5.129.204.194}"   # при необходимости поменяй юзера
    APP_DIR="/opt/lk-aimpact"
    REPO="https://github.com/rebekaee1/lk_navylet.git"
    DEPLOY_CMD="./deploy/deploy-prod.sh"
    ;;
  *) echo "ERROR: укажи --project mgp|lk"; exit 2;;
esac
BRANCH="${BRANCH:-main}"
PG_USER="${PG_USER:-mgp}"
PG_DB="${PG_DB:-mgp}"
TS="$(date +%Y%m%d_%H%M%S)"
DUMP="$WORKDIR/${PROJECT}_db_${TS}.sql.gz"
ENVBAK="$WORKDIR/${PROJECT}.env.from_old"

log()  { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ABORT]\033[0m %s\n' "$*" >&2; exit 1; }

# pg-контейнер на удалённом хосте определяем динамически
REMOTE_PG='docker ps --filter name=postgres -q | head -1'

confirm() {
  [ "$ASSUME_YES" = "1" ] && return 0
  printf '\033[1;33m%s\033[0m [yes/NO]: ' "$1"; read -r a; [ "$a" = "yes" ]
}

counts_on() { # $1 = ssh target -> печатает "conv|msg"
  ssh -o ConnectTimeout=15 "$1" "
    PG=\$($REMOTE_PG);
    C=\$(docker exec \$PG psql -U $PG_USER -d $PG_DB -tAc 'SELECT count(*) FROM conversations' 2>/dev/null || echo NA);
    M=\$(docker exec \$PG psql -U $PG_USER -d $PG_DB -tAc 'SELECT count(*) FROM messages' 2>/dev/null || echo NA);
    echo \"\$C|\$M\"
  "
}

# ─── PHASE 1: BACKUP (только чтение старого сервера) ──────────────────────────
phase_backup() {
  log "ФАЗА 1 — БЭКАП со старого ($OLD_SSH), читаем, ничего не меняем"
  mkdir -p "$WORKDIR"
  ssh -o ConnectTimeout=15 "$OLD_SSH" "echo connected" >/dev/null || die "нет SSH до старого сервера $OLD_SSH"
  log "Снимаю pg_dump и качаю локально → $DUMP"
  ssh "$OLD_SSH" "PG=\$($REMOTE_PG); docker exec \$PG pg_dump -U $PG_USER $PG_DB | gzip -c" > "$DUMP"
  SZ=$(du -h "$DUMP" | cut -f1)
  [ -s "$DUMP" ] || die "дамп пустой! миграцию НЕ продолжать"
  ok "дамп получен: $DUMP ($SZ)"
  log "Забираю .env со старого → $ENVBAK (секреты, хранить безопасно)"
  if ssh "$OLD_SSH" "test -f $APP_DIR/.env"; then
    ssh "$OLD_SSH" "cat $APP_DIR/.env" > "$ENVBAK"; chmod 600 "$ENVBAK"; ok ".env сохранён ($ENVBAK)"
  else
    warn ".env не найден в $APP_DIR на старом — заполнишь вручную из .env.example"
  fi
  log "Контрольные количества на СТАРОМ сервере:"
  OLD_COUNTS=$(counts_on "$OLD_SSH"); echo "  conversations|messages = $OLD_COUNTS"
  echo "$OLD_COUNTS" > "$WORKDIR/${PROJECT}_old_counts.txt"
  ok "Бэкап-фаза завершена. Дамп и счётчики сохранены. Старый сервер не тронут."
}

# ─── PHASE 2: PROVISION нового сервера ────────────────────────────────────────
phase_provision() {
  [ -n "$NEW_SSH" ] || die "укажи --new user@NEW_IP"
  [ -f "$DUMP" ] || { DUMP="$(ls -t "$WORKDIR/${PROJECT}_db_"*.sql.gz 2>/dev/null | head -1)"; }
  [ -f "$DUMP" ] || die "не найден дамп БД — сначала прогони фазу backup"
  log "ФАЗА 2 — РАЗВЁРТЫВАНИЕ на новом ($NEW_SSH), APP_DIR=$APP_DIR"
  echo "  project=$PROJECT  repo=$REPO  branch=$BRANCH  dump=$DUMP"
  confirm "Развернуть проект на $NEW_SSH? (старый продолжит работать)" || die "отменено пользователем"

  ssh -o ConnectTimeout=15 "$NEW_SSH" "echo connected" >/dev/null || die "нет SSH до нового сервера $NEW_SSH"

  log "2.1 базовая настройка сервера (Docker/firewall/swap)"
  ssh "$NEW_SSH" "curl -fsSL https://raw.githubusercontent.com/${REPO#https://github.com/}" >/dev/null 2>&1 || true
  ssh "$NEW_SSH" "set -e; mkdir -p $APP_DIR; cd $APP_DIR; \
    if [ ! -d .git ]; then git clone -b $BRANCH $REPO .; else git fetch origin && git checkout $BRANCH && git pull; fi"
  # setup-server.sh из репо (Docker и пр.)
  ssh "$NEW_SSH" "cd $APP_DIR && sudo bash deploy/setup-server.sh"
  ok "сервер настроен, код склонирован"

  log "2.2 загружаю .env на новый сервер"
  if [ -f "$ENVBAK" ]; then
    scp "$ENVBAK" "$NEW_SSH:$APP_DIR/.env"; ssh "$NEW_SSH" "chmod 600 $APP_DIR/.env"
    warn "ВНИМАНИЕ: проверь .env — POSTGRES_PASSWORD оставь как на старом (иначе дамп не сядет), при желании поменяй ПОСЛЕ миграции"
  else
    warn ".env не перенесён — зайди на новый сервер, cp .env.example .env и заполни (см. чеклист)"
    confirm "Продолжить без авто-.env (ты зальёшь его вручную сейчас в другом окне)?" || die "останов"
  fi

  log "2.3 поднимаю ТОЛЬКО postgres+redis (backend пока НЕ стартуем)"
  ssh "$NEW_SSH" "cd $APP_DIR && docker compose up -d postgres redis && sleep 8 && docker compose ps"

  log "2.4 ВОССТАНОВЛЕНИЕ БД из дампа в пустой контейнер"
  gunzip -c "$DUMP" | ssh "$NEW_SSH" "PG=\$($REMOTE_PG); docker exec -i \$PG psql -U $PG_USER -d $PG_DB" \
    && ok "дамп восстановлен" || die "ошибка восстановления БД — backend НЕ запускаю"

  log "2.5 запускаю весь стек (build + backend), деплой-скрипт проекта"
  ssh "$NEW_SSH" "cd $APP_DIR && $DEPLOY_CMD"
  ok "стек запущен"
}

# ─── PHASE 3: VERIFY (сверка количеств — защита диалогов) ─────────────────────
phase_verify() {
  [ -n "$NEW_SSH" ] || die "укажи --new user@NEW_IP"
  log "ФАЗА 3 — СВЕРКА КОЛИЧЕСТВ (диалоги не потеряны?)"
  OLD_COUNTS="$(cat "$WORKDIR/${PROJECT}_old_counts.txt" 2>/dev/null || counts_on "$OLD_SSH")"
  NEW_COUNTS="$(counts_on "$NEW_SSH")"
  echo "  СТАРЫЙ conversations|messages = $OLD_COUNTS"
  echo "  НОВЫЙ  conversations|messages = $NEW_COUNTS"
  if [ "$OLD_COUNTS" = "$NEW_COUNTS" ]; then
    ok "СОВПАДАЕТ — диалоги на месте ✅"
  else
    warn "НЕ СОВПАДАЕТ! Не переключай DNS, разберись (дамп цел: $DUMP). ❌"
    return 1
  fi
  log "health-check нового:"
  ssh "$NEW_SSH" "curl -fsS http://127.0.0.1:\${APP_PORT:-80}/api/health || curl -fsS http://127.0.0.1/api/health" \
    && ok "health OK" || warn "health не прошёл — проверь логи: docker compose logs -f backend"
}

# ─── финальные ручные шаги ────────────────────────────────────────────────────
final_notes() {
  cat <<EOF

\033[1;36m== ОСТАЛОСЬ СДЕЛАТЬ РУКАМИ ==\033[0m
1. DNS: направить домен на новый IP (для lk — lk.navilet.ru → новый IP).
   Старый сервер пока НЕ гаси — он живой бэкап, пока не убедишься в новом.
2. SSL (только lk): после смены DNS на новом сервере выпустить сертификат
   (certbot уже в docker-compose; см. deploy LK).
3. Связки LK <-> MGP: в .env обоих обновить адреса/токены друг друга
   (bot_server_url / RUNTIME_* / REPORTING_ENDPOINT_URL), чтобы ходили на новые IP.
4. Безопасность: создать non-root юзера, добавить SSH-ключ, отключить root/пароль.
5. Бэкапы: на новом включить cron deploy/backup.sh (ежедневный pg_dump).
6. Только после полной проверки — переключить трафик и (опц.) погасить старый.

Дамп БД сохранён локально: $DUMP  (НЕ удаляй, пока не убедишься на 100%).
EOF
}

# ─── запуск ───────────────────────────────────────────────────────────────────
log "Миграция проекта: $PROJECT | старый: $OLD_SSH | новый: ${NEW_SSH:-<не задан>}"
case "$ONLY" in
  backup)    phase_backup;;
  provision) phase_provision;;
  verify)    phase_verify;;
  "")        phase_backup; phase_provision; phase_verify; final_notes;;
  *) die "неизвестная фаза --only $ONLY";;
esac
ok "Готово (фаза: ${ONLY:-all})."
