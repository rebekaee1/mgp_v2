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
- отдельный `frontend` сервис
- публичная раздача widget UI с домена MGP

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
- `RUNTIME_DIALOG_SENDER_ENABLED=true`
- `RUNTIME_DIALOG_SENDER_BATCH_SIZE=20`
- `RUNTIME_DIALOG_SENDER_INTERVAL_SECONDS=10`
- `RUNTIME_DIALOG_SENDER_TIMEOUT_SECONDS=15`
- `RUNTIME_DIALOG_SENDER_MAX_ATTEMPTS=5`
- `RUNTIME_DIALOG_SENDER_RETRY_BACKOFF_SECONDS=10`
- `RUNTIME_DIALOG_SENDER_RETRY_BACKOFF_MAX_SECONDS=300`
- `RUNTIME_PROVISIONING_API_TOKEN=...`
- `RUNTIME_PROVISIONING_CALLBACK_TIMEOUT_SECONDS=15`
- `RUNTIME_PROVISIONING_CALLBACK_MAX_ATTEMPTS=3`
- `RUNTIME_PROVISIONING_CALLBACK_BACKOFF_SECONDS=2`

## Backend-only profile

Использовать:

```bash
./deploy/deploy-runtime.sh
```

Что делает скрипт:

1. Удаляет старый `frontend` контейнер, если он ещё остался после legacy-деплоя
2. Поднимает `postgres + redis + backend` через основной `docker-compose.yml`
3. Собирает dashboard SPA внутрь backend image
4. Публикует backend на `APP_PORT` (`80` по умолчанию)
5. Проверяет `GET /api/health`

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

Для tenant-specific runtime auth в `enforce` mode `LK` должен передавать `assistant_id` в body и/или `X-Assistant-Id` в header вместе с `X-MGP-Service-Token`, чтобы runtime выбрал корректный per-tenant secret.

## Control-Plane API

Новые control-plane friendly endpoints:

- `GET /api/runtime/metadata`
- `GET /api/runtime/status`
- `POST /api/provisioning/tenants`
- `GET /api/provisioning/tenants/<provisioning_request_id>`

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
- backlog sender-а: `dialog_sender_backlog.pending|retrying|failed`

### Provisioning Contract

`POST /api/provisioning/tenants` принимает:

- `Authorization: Bearer <RUNTIME_PROVISIONING_API_TOKEN>`
- `X-Idempotency-Key`
- `X-Control-Plane-Request-Id`
- `provisioning_request_id` в body
- tenant/admin/assistant/runtime payload

Финально согласованный способ передачи runtime chat-secret:

- `LK` генерирует runtime-wide secret
- передаёт его в `runtime.service_auth.secret`
- `MGP` сохраняет и применяет его в новом runtime
- `callback/status API` secret не возвращают

Стабильное поведение runtime payload:

- `poll` и `callback` должны всегда возвращать полный `runtime` payload
- минимум: `runtime.public_base_url`
- target payload: `public_base_url`, `health_url`, `status_url`, `metadata_url`
- если `LK` не прислал `runtime.public_base_url` или `assistant.bot_server_url`, runtime использует base URL самого provisioning endpoint как fallback

Поддерживаемая структура:

```json
{
  "provisioning_request_id": "req_123",
  "callback": {
    "url": "https://lk.example/api/runtime/callback",
    "auth": {
      "token": "callback-secret"
    }
  },
  "tenant": {
    "company_name": "New Company",
    "company_slug": "new-company",
    "company_logo_url": "https://cdn.example/logo.png"
  },
  "admin_user": {
    "email": "admin@example.com",
    "password": "strong-password",
    "name": "Admin"
  },
  "assistant": {
    "assistant_id": "11111111-2222-3333-4444-555555555555",
    "name": "New Company AI Assistant",
    "bot_server_url": "https://runtime.example.com",
    "allowed_domains": "https://site.example.com",
    "system_prompt": "...",
    "faq_content": "..."
  },
  "runtime": {
    "public_base_url": "https://runtime.example.com",
    "service_auth": {
      "mode": "shared_secret",
      "header_name": "X-MGP-Service-Token",
      "scope": "runtime",
      "secret": "generated-by-lk"
    },
    "reporting": {
      "mode": "batch_snapshot",
      "contract_version": "2026-03-09",
      "endpoint_url": "https://lk.example.com/api/control-plane/runtime/events",
      "accepted_event_types": ["conversation_snapshot"],
      "auth": {
        "type": "shared_secret",
        "header_name": "X-MGP-Service-Token",
        "secret": "generated-by-lk"
      }
    }
  }
}
```

Status model:

- `accepted`
- `provisioning`
- `runtime_ready`
- `failed`

В `GET /api/provisioning/tenants/<provisioning_request_id>` и callback body возвращаются только:

- `provisioning_request_id`
- `status`
- `control_plane_request_id`
- `tenant.company_id`
- `tenant.assistant_id`
- runtime URLs/metadata без `service_auth.secret`
- callback delivery diagnostics: `callback.configured`, `callback.delivery_status`, `callback.attempts`, `callback.last_status_code`, `callback.last_error`
- `error` при `failed`

## Runtime Reporting

Новый `MGP -> LK` канал больше не зависит от legacy SSH-sync.

Что делает runtime:

- после успешной записи чата в PostgreSQL формирует versioned `conversation_snapshot`
- кладёт snapshot в durable `runtime_event_outbox`
- фоновой job доставляет snapshot в `LK`
- при ошибках применяет retry/backoff и сохраняет `last_status_code` / `last_error`

Текущий transport-контракт:

- endpoint: `runtime.reporting.endpoint_url`
- auth: `runtime.reporting.auth.header_name` + plain shared secret
- event type: `conversation_snapshot`
- payload: полная snapshot-модель диалога (`conversation`, `messages`, `tour_searches`, `api_calls`)
- idempotency: `event_id` уникален на snapshot; receiver может дедуплицировать по `assistant_id + event_id`

Секрет `runtime.reporting.auth.secret` сохраняется в `assistant.runtime_metadata`, но не возвращается в callback/status API.

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
  --dry-run

# затем реальный запуск:
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

Safe smoke-test без создания tenant:

```bash
python backend/cli.py provision-tenant \
  --email smoke-test@example.com \
  --password 'not-used-in-dry-run' \
  --company 'Smoke Test Company' \
  --slug smoke-test-company \
  --assistant-name 'Smoke Test Assistant' \
  --dry-run
```

## Важное ограничение

Контракт `LK <-> MGP` не меняется:

- сайт клиента грузит loader из LK
- LK знает `assistant_id` и `bot_server_url`
- LK проксирует чат в runtime
- MGP остаётся runtime target
