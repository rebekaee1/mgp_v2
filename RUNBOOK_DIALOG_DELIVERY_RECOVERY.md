# Dialog Delivery Recovery Runbook

Актуально для runtime-only production схемы `MGP -> LK` через `runtime_event_outbox` + `dialog_sender`.

## Цель

Штатно восстановить доставку истории диалогов в `LK`, если:

- backlog sender-а растет
- `LK` обнаружил пропуск истории
- delivery pipeline перешел в `degraded` или `failed`

## Проверка статуса

Основной endpoint:

```bash
curl -s http://127.0.0.1/api/runtime/status | jq
```

Ключевые поля:

- `dialog_sender_backlog.pending`
- `dialog_sender_backlog.retrying`
- `dialog_sender_backlog.failed`
- `oldest_undelivered_event_age_sec`
- `last_successful_delivery_at`
- `estimated_delivery_lag_sec`
- `delivery_pipeline_status`
- `dialog_sender_alert_thresholds`

## Как интерпретировать

- `delivery_pipeline_status=ok`
  Значит sender работает штатно.

- `delivery_pipeline_status=degraded`
  Значит backlog или lag вышли за normal threshold, либо sender уже retry-ит события.

- `delivery_pipeline_status=failed`
  Значит backlog failed > alert threshold или oldest undelivered event age достиг alert threshold.

## Когда запускать replay

Replay нужен, если:

- `LK` не видит историю, которая уже есть в `MGP`
- backlog sender-а не возвращается к норме после восстановления канала
- нужно безопасно дозалить историю по assistant / conversation / time range

## Replay команда

CLI:

```bash
python backend/cli.py replay-outbox --assistant-id <assistant_uuid>
python backend/cli.py replay-outbox --conversation-id <conversation_uuid>
python backend/cli.py replay-outbox --from 2026-03-16T00:00:00+00:00 --to 2026-03-16T23:59:59+00:00
```

С немедленной доставкой:

```bash
python backend/cli.py replay-outbox --assistant-id <assistant_uuid> --deliver-now
python backend/cli.py replay-outbox --conversation-id <conversation_uuid> --deliver-now
python backend/cli.py replay-outbox --from 2026-03-16T00:00:00+00:00 --to 2026-03-16T23:59:59+00:00 --deliver-now
```

## Параметры replay

Поддерживаются:

- `assistant_id`
- `conversation_id`
- `from`
- `to`
- `limit`

Replay ставит новые `conversation_snapshot` события в `runtime_event_outbox`.
На стороне `LK` прием должен быть идемпотентным.

## Recovery flow

1. Проверить `GET /api/runtime/status`.
2. Зафиксировать:
   - backlog
   - `oldest_undelivered_event_age_sec`
   - `last_successful_delivery_at`
   - `delivery_pipeline_status`
3. Убедиться, что исходная история есть в `MGP Postgres`.
4. Запустить replay по самому узкому безопасному фильтру:
   - сначала `conversation_id`
   - затем `assistant_id`
   - затем `time range`
5. Если нужно срочно догнать `LK`, использовать `--deliver-now`.
6. Перепроверить `GET /api/runtime/status`.
7. Подтвердить на стороне `LK`:
   - история появилась
   - дублей нет
   - backlog/lag вернулись в норму

## Acceptance checklist

Считаем recovery успешным, если:

- нужная история появилась в `LK`
- дублей в `LK` нет
- `dialog_sender_backlog.failed == 0`
- `delivery_pipeline_status != failed`
- `oldest_undelivered_event_age_sec` вернулся в допустимый диапазон
- `last_successful_delivery_at` обновился после replay

## Alert thresholds

Runtime использует следующие базовые пороги:

- `normal_lag_sec = 60`
- `oldest_undelivered_alert_sec = 300`
- `failed_backlog_alert_count = 1`

Эти значения отдаются в `dialog_sender_alert_thresholds` и могут быть переопределены через env:

- `RUNTIME_DIALOG_SENDER_NORMAL_LAG_THRESHOLD_SECONDS`
- `RUNTIME_DIALOG_SENDER_OLDEST_PENDING_ALERT_SECONDS`
- `RUNTIME_DIALOG_SENDER_FAILED_BACKLOG_ALERT_THRESHOLD`

## Комментарий

Этот runbook покрывает `Phase 1` recovery path на стороне `MGP`.
`Phase 2` добавляет `LK-triggered reconciliation API`:

```bash
POST /api/runtime/reconciliation
GET /api/runtime/reconciliation/<reconciliation_request_id>
```

Для вызова используются:

- `Authorization: Bearer <RUNTIME_PROVISIONING_API_TOKEN>`
- `X-Idempotency-Key`
- `X-Control-Plane-Request-Id`

Body поддерживает:

- `assistant_id`
- `conversation_id`
- `from`
- `to`
- `limit`
- `deliver_now`
