# Deploy Notes

Актуально на `2026-03-17`.

## Текущее состояние

- Локальный репозиторий, `origin/main` и код на сервере `/opt/mgp` синхронизированы.
- Текущий commit: `c7cd776` (`fix: departure-context-aware region handling, truncation prevention, date/meal fixes`).
- Production runtime работает в режиме `backend-only`.
- Основной production flow: `LK -> MGP runtime -> MGP Postgres`.
- Legacy SSH-sync на production явно отключен через `SYNC_MGP_ENABLED=false`.

## Production topology

- Сервер: `72.56.88.193`
- Production user: `mgpadmin`
- SSH-доступ: только по ключу
- `root` login по SSH: отключен
- Password SSH auth: отключен
- Внешний HTTP: `nginx` на `:80`
- Backend: только `127.0.0.1:8080`
- Database: локальный `postgres` контейнер
- Cache / queue state: локальный `redis` контейнер

## Что проверено

- `backend`, `postgres`, `redis` запущены и healthy.
- Публичный HTTP отвечает `200 OK`.
- `/api/runtime/status` отвечает `status=ok`.
- `dialog_sender_enabled=true`.
- В `assistants.runtime_metadata` есть `reporting.endpoint_url` минимум у 4 assistant'ов.
- В `runtime_event_outbox` есть отправленные события.
- На момент проверки: `OUTBOX_TOTAL=200`, `OUTBOX_STATUS=sent:200`.

## Вывод по истории диалогов

Текущая целевая схема выглядит так:

1. `LK` проксирует чат-запросы в `MGP runtime`.
2. `MGP runtime` сохраняет историю в свою PostgreSQL.
3. После записи runtime формирует `conversation_snapshot`.
4. Snapshot кладется в `runtime_event_outbox`.
5. `dialog_sender` доставляет snapshot в `LK`.
6. `LK` хранит свою реплицированную business/read copy.

Рабочая гипотеза на текущий момент:

- `MGP Postgres` = канонический source of truth
- `LK` = replicated business copy
- legacy SSH-sync не должен использоваться как основной production механизм

## Изменения, внесенные напрямую на сервере

Эти изменения не описаны полностью в git и относятся к server/runtime конфигурации:

- настроен пользователь `mgpadmin`
- добавлен SSH key-only доступ
- отключены `root` login и password SSH auth
- установлен и включен `nginx`
- backend переведен на `127.0.0.1:8080`
- включен базовый rate limiting в `nginx`
- в `.env` установлен `SYNC_MGP_ENABLED=false`

## Что еще нужно формально согласовать с MGP

Ниже вопросы, на которые нужна отдельная явная фиксация со стороны команды MGP.

### 1. Source of truth

Подтвердить, что `MGP Postgres` является единственным каноническим источником истины для:

- `conversations`
- `messages`
- `tour_searches`
- `api_calls`
- `tool_calls` / `tool events`
- статусов диалога
- runtime metadata, влияющих на восстановление истории

### 2. Outbox contract

Подтвердить, что после успешной записи диалога/события в `MGP Postgres` всегда создается запись в durable outbox, и доставка в `LK` идет именно из outbox, а не напрямую из request flow.

### 3. Event types

Нужно явно перечислить, какие event types гарантированно отправляются в `LK`:

- `conversation_snapshot`
- message-level events
- search events
- api call events
- status transitions
- anything else

### 4. Delivery state

Нужно зафиксировать:

- название таблицы/модели
- поля: `status`, `attempts`, `next_retry_at`, `last_error`, `last_status_code`, `delivered_at`, `failed_at`, `event_id`, `assistant_id`
- текущие статусы
- правила переходов статусов

### 5. Replay / backfill / reconciliation

Нужно отдельно ответить:

- что уже есть
- чего нет
- что планируется
- какой endpoint / job / команда используется

### 6. Observability

Нужно перечислить:

- endpoint'ы
- поля ответа
- метрики
- логи
- алерты

Минимально интересуют:

- backlog `pending`
- backlog `retrying`
- backlog `failed`
- oldest undelivered event age
- last successful delivery time
- delivery lag `MGP -> LK`

### 7. SLA

Нужно зафиксировать production SLA доставки, например:

- `p95` доставки `<= 30 сек`
- normal lag `<= 60 сек`
- alert на failed delivery `<= 5 мин`
- recovery after outage `<= N минут`

### 8. Fallback

Нужно подтвердить, что legacy SSH-sync остается только временным fallback и не считается основным production-механизмом.

### 9. Acceptance criteria

Схему можно считать согласованной только если выполнены все условия:

- история канонически хранится в `MGP`
- `LK` получает ее через `outbox/sender`
- доставка идемпотентна
- есть retry
- есть replay/backfill
- есть наблюдаемость backlog/lag
- зафиксирован SLA

## Комментарий

На текущем production уже видны признаки работающего нового канала `MGP -> LK` через outbox/sender, но часть критичных гарантий пока подтверждена только косвенно по коду и runtime-состоянию. До получения формального ответа от команды MGP архитектуру стоит считать близкой к целевой, но еще не полностью зафиксированной на уровне контракта.
