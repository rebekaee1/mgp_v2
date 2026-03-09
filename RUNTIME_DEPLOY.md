# MGP Runtime Deploy

`mgp_v2` в целевой схеме используется как backend-only runtime.

Что остаётся в боевом контуре:
- `POST /api/v1/chat`
- `POST /api/chat/stream`
- `GET /api/health`
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

Опционально:

- `CORS_ORIGINS=...`
- `ALLOWED_ORIGINS=...`
- `OPENAI_BASE_URL=...`

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

## Важное ограничение

Контракт `LK <-> MGP` не меняется:

- сайт клиента грузит loader из LK
- LK знает `assistant_id` и `bot_server_url`
- LK проксирует чат в runtime
- MGP остаётся runtime target
