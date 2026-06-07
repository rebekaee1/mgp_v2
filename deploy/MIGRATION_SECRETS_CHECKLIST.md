# Чеклист переноса: что заполнить в `.env` на новом сервере

Секретов нет ни в репозитории, ни в этом файле. Самый безопасный путь —
**скопировать рабочий `.env` со старого сервера 1:1** (скрипт `migrate-to-new-server.sh`
делает это автоматически), и менять значения только ПОСЛЕ успешной миграции.

> Если копируешь `.env` со старого — менять ничего не нужно, всё уже консистентно.
> Заполнять вручную нужно только если поднимаешь `.env` с нуля из `.env.example`.

Легенда: ⚠️ = обязательно (без него не стартует) · 🔗 = связка LK↔MGP · 💾 = влияет на БД.

## Критичные (REPLACE_ME)
| Переменная | Где | Зачем |
|---|---|---|
| `POSTGRES_PASSWORD` 💾 | оба | пароль БД. Должен совпадать в .env и контейнере (берётся из одного .env). При копировании старого .env — не трогать до миграции |
| `OPENAI_API_KEY` ⚠️ | оба | ключ OpenRouter/OpenAI (мозг ассистента) |
| `OPENAI_BASE_URL` | оба | `https://openrouter.ai/api/v1` если OpenRouter |
| `TOURVISOR_AUTH_LOGIN` / `TOURVISOR_AUTH_PASS` ⚠️ | оба | поиск туров |
| `JWT_SECRET` ⚠️ | оба | вход в ЛК/админку. Если сменить — разлогинит всех (`openssl rand -hex 32`) |
| `CORS_ORIGINS` / `ALLOWED_ORIGINS` | оба | домены фронта/виджета |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` / `SEED_COMPANY_*` | оба | автосид при ПЕРВОМ запуске пустой БД. При миграции с восстановлением дампа сид не сработает (данные уже есть) — можно оставить как есть |

## Связки LK ↔ MGP (🔗 — обновить на новые адреса!)
| Переменная | Сторона | Зачем |
|---|---|---|
| `RUNTIME_SERVICE_AUTH_SECRET` 🔗 | MGP | общий секрет заголовка `X-MGP-Service-Token` (должен совпасть с LK) |
| `RUNTIME_REPORT_URL` / `RUNTIME_REPORT_TOKEN` 🔗 | MGP | куда MGP шлёт диалоги в LK |
| `RUNTIME_PROVISIONING_API_TOKEN` 🔗 | MGP | приём provisioning от LK |
| `RUNTIME_PROVISIONER_URL` / `RUNTIME_PROVISIONER_TOKEN` 🔗 | LK | LK → MGP provisioning |
| `RUNTIME_PROVISIONER_CALLBACK_TOKEN` 🔗 | LK | MGP → LK callback |
| `PLATFORM_ADMIN_EMAILS` | LK | внутренние админы Навылет |
| `LK_WIDGET_LOADER_URL` / `WIDGET_HOST_URL` 🔗 | оба | `https://lk.navilet.ru/...` (поменять если меняется домен LK) |
| Assistant `bot_server_url` (в БД, не в .env) 🔗 | LK→MGP | адрес MGP-runtime для каждого тенанта. **После смены IP MGP — обновить в БД LK** |

## Интеграции
| Переменная | Зачем |
|---|---|
| `UON_API_KEY` / `UON_SOURCE` / `UON_DRY_RUN` | CRM U-ON (dry-run по умолчанию; реальные вызовы только с whitelisted IP — новый IP надо добавить в U-ON) |
| `AI_REPORT_API_KEY` / `AI_REPORT_MODEL` | AI-отчёты в ЛК |
| `YANDEX_API_KEY` / `YANDEX_FOLDER_ID` | альтернативный LLM (если используется) |
| MAX bot (в БД/конфиге тенанта, не в .env) | токен бота MAX — **живой секрет**, хранить вне гита |

## Инфраструктура (можно оставить дефолты)
`REDIS_PASSWORD`, `APP_PORT=80`, `RUNTIME_MODE=backend-only`, `PG_SHARED_BUFFERS`,
`GUNICORN_WORKERS/THREADS`, `DB_POOL_*`, `SESSION_TTL_SECONDS`, `LOG_LEVEL`.
Подгони `GUNICORN_WORKERS`/`PG_*` под RAM нового сервера (2 → 2GB, 4 → 4GB+).

## Legacy sync (обычно выключено)
`SYNC_MGP_ENABLED=false` (если включён — `MGP_SSH_*`, `MGP_PG_*`, файл `sync_key`).
Для новой архитектуры доставка идёт через outbox/dialog_sender, sync не нужен.

---
### Порядок безопасной миграции (кратко)
1. `./deploy/migrate-to-new-server.sh --project mgp --only backup` — снять дамп (старый не трогается).
2. Купить VPS, получить `root@NEW_IP`.
3. `./deploy/migrate-to-new-server.sh --project mgp --new root@NEW_IP` — развернуть + restore + сверка.
4. Убедиться, что conversations/messages совпали (скрипт проверит). Только потом DNS.
5. Те же шаги с `--project lk` (+ certbot для SSL после DNS).
6. Обновить связки LK↔MGP и `bot_server_url` тенантов на новые IP.
7. Старый сервер не гасить, пока новый не проверен в бою.
