# MGP Runtime Deploy

`mgp_v2` в целевой схеме используется как backend-only runtime.

Что остаётся в боевом контуре:
- `POST /api/v1/chat`
- `POST /api/chat/stream`
- `GET /api/health`
- `GET /api/runtime/metadata`
- `GET /api/runtime/status`
- PostgreSQL / Redis / runtime logs

Что не используется как production entrypoint:
- `frontend` сервис
- публичная раздача frontend/виджета с домена MGP

## Runtime env

Минимальные runtime-переменные:

- `RUNTIME_MODE=backend-only`
- `APP_PORT=80`
- `POSTGRES_PASSWORD=...`
- `REDIS_PASSWORD=...`
- `OPENAI_API_KEY=...` или tenant-aware assistant config в БД
- `LK_WIDGET_LOADER_URL=https://lk.navilet.ru/widget-loader.js`
- `RUNTIME_INSTANCE_ID=<runtime-id>`
- `RUNTIME_SERVICE_AUTH_MODE=monitor`

Опционально:

- `CORS_ORIGINS=...`
- `ALLOWED_ORIGINS=...`
- `OPENAI_BASE_URL=...`
- `RUNTIME_PUBLIC_BASE_URL=https://runtime.example.ru`
- `RUNTIME_SERVICE_AUTH_SECRET=...`
- `RUNTIME_TRUSTED_PROXY_CIDRS=...`
- `RUNTIME_REPORT_URL=...`
- `RUNTIME_REPORT_TOKEN=...`

## Backend-only profile

Использовать:

```bash
./deploy/deploy-runtime.sh
```

Что делает скрипт:

1. Останавливает и удаляет `frontend`
2. Поднимает `postgres + redis + backend` через `docker-compose.runtime.yml`
3. Публикует backend на `APP_PORT` (`80` по умолчанию)
4. Проверяет `GET /api/health`

## Phase-1 LK Auth

Для перехода без ломки текущего контракта runtime поддерживает 3 режима:

- `off` — service auth полностью выключен
- `monitor` — runtime принимает запросы как раньше, но уже валидирует/логирует service auth
- `enforce` — runtime требует trusted caller или валидный service auth

Согласованный phase-1 контракт `LK -> MGP`:

- header: `X-MGP-Service-Token`
- value: plain static shared secret
- scope: runtime-wide
- auth type: shared secret, без HMAC
- LK шлёт auth только в `POST /api/v1/chat`
- `GET /api/runtime/status` и `GET /api/runtime/metadata` пока без обязательного auth

Ключ: `RUNTIME_SERVICE_AUTH_SECRET`.

Совместимые fallback-варианты тоже поддерживаются, но phase-1 target contract именно `X-MGP-Service-Token`.

## Control-Plane API

Новые control-plane friendly endpoints:

- `GET /api/runtime/metadata`
- `GET /api/runtime/status`

Они предназначены для provisioning/orchestration слоя и не меняют chat-контракт.

`/api/runtime/metadata` возвращает:

- `runtime_instance_id`
- `runtime_mode`
- tenant metadata (`assistant_id`, `company_id`, branding, allowed_domains)
- LLM provider/model
- security mode и trusted caller config

`/api/runtime/status` возвращает:

- health PostgreSQL / Redis
- `active_sessions`
- `runtime_mode`
- `service_auth_mode`
- флаг включенного reporting/webhook слоя

## Template / Provisioning

Runtime рассчитан на шаблонный запуск новой компании без правки кода:

1. Поднять новый runtime из репозитория и `.env`
2. Выполнить auto-seed через `SEED_*` env
3. Или выполнить CLI provisioning:

```bash
python backend/cli.py provision-tenant \
  --email admin@example.com \
  --password 'strong-password' \
  --company 'New Company' \
  --slug new-company \
  --assistant-name 'New Company AI Assistant' \
  --allowed-domains 'https://site.example.com,https://www.site.example.com' \
  --bot-server-url 'https://runtime.example.com' \
  --system-prompt-file /opt/mgp/system_prompt.md \
  --faq-file /opt/mgp/faq.md
```

Tenant values, которые можно подменять без правки кода:

- company metadata: `name`, `slug`, `logo_url`
- assistant metadata: `name`, `assistant_id`, `bot_server_url`, `allowed_domains`
- branding: `title`, `subtitle`, `primary_color`, `logo_url`
- LLM/TourVisor credentials
- `system_prompt`, `faq_content`

## Minimal Clone Flow

Минимальный flow для нового runtime:

1. `git clone <repo> /opt/mgp-company`
2. `cp .env.example .env`
3. Заполнить runtime-wide env (`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `RUNTIME_INSTANCE_ID`, auth secret)
4. Заполнить `SEED_*` tenant env или запустить `cli.py provision-tenant`
5. `./deploy/deploy-runtime.sh`
6. Проверить:
   - `GET /api/health`
   - `GET /api/runtime/status`
   - `GET /api/runtime/metadata?assistant_id=<...>`

## Важное ограничение

Контракт `LK <-> MGP` не меняется:

- сайт клиента грузит loader из LK
- LK знает `assistant_id` и `bot_server_url`
- LK проксирует чат в runtime
- MGP остаётся runtime target
