# Manager-Handoff Contract (MGP ↔ LK) — authoritative

> **Создан:** 2026-06-09. **Версия контракта:** `mh-1` (handoff-фича).
> **Назначение:** двусторонний контракт «вход менеджера в чат + уведомления».
> Это **дополнение** к `MAX_LK_INTEGRATION_HANDOFF.md` (тот — про атрибуцию канала и
> профиль клиента; здесь — то, что там помечено «Future, NOT in this iteration»).
> **Owner схемы:** MGP (значения полей/событий ниже — канонические; ЛK строит по ним).
> **Статус:** дизайн зафиксирован; код Ф.A в MGP стартует ПОСЛЕ поставки ЛК
> (тест-компания + reporting-секрет). На прод ничего не выкатывается до этого.

Сверено с кодом MGP:
`backend/dialog_sender.py` (`_build_snapshot_payload`, `_serialize_message`,
`_runtime_reporting_config`), `backend/app.py` (`_evaluate_runtime_auth`,
`_is_internal_request`), `backend/models.py` (`Conversation`, `Message`).

---

## 0. Базовые факты (подтверждены на проде 2026-06-09)

| Параметр | Значение |
|---|---|
| Тест-ассистент (MAX) | `593471b7-42da-4ae0-8499-904dcedd6a4b` (бот `@id9705243471_bot`, «Навылет! AI») |
| AnyTour/Павел (НЕ трогаем) | `64fea0d3-2605-4c4c-be67-62258ebfa7a9` |
| Scope фичи | **только `channel='max'` И assistant_id ∈ allow-list (сейчас только 593471b7)** |
| MGP HTTPS-домен | `https://max.navilet.ru` (Let's Encrypt, 443) — сюда вешаем back-channel |
| Reporting endpoint (MGP→LK) | `https://lk.navilet.ru/api/control-plane/runtime/events` |
| Заголовок auth (обе стороны) | `X-MGP-Service-Token` |
| `contract_version` в payload | остаётся `2026-03-09` (новые event_type — аддитивны) |
| Ключ дедупа сообщений | `remote_id` (= `messages.id`, int) — как в `conversation_snapshot` |
| Роль оператора | `messages.role = 'operator'` (миграции не требует — `String(16)` без CHECK) |

---

## 1. Два секрета, два направления (НЕ путать)

1. **Reporting MGP→LK** (события доходят в тест-кабинет):
   ЛК генерирует `shared_secret` под UUID **593471b7** → присылает мне → MGP применяет в
   `assistants.runtime_metadata.reporting` через `jsonb_set('{reporting}', …)`
   (endpoint=`…/runtime/events`, header `X-MGP-Service-Token`). Паттерн — как
   `MAX_LK_INTEGRATION_HANDOFF.md` §5.1 Finding 3.
2. **Back-channel LK→MGP** (ответ менеджера / перехват):
   MGP выдаёт ЛК токен `MGP_OPERATOR_TOKEN` (= `runtime_service_auth_secret` тест-
   ассистента). ЛК хранит его **только на бэкенде**, шлёт как `X-MGP-Service-Token` на
   операторские ручки MGP. На этих ручках проверка **строгая** (не `monitor`).

---

## 2. Новые поля в блоке `conversation` (мутабельные)

Добавляются в `conversation`-блок **каждого** события (`conversation_snapshot`,
`manager_alert`, `operator_inbound`). Старые потребители игнорируют незнакомые ключи.

```json
"operator_mode": false,
"handoff_state": "none",
"handoff_reason": null,
"operator_mode_since": null,
"operator_actor": null
```

| Поле | Тип | Значения | Семантика |
|---|---|---|---|
| `operator_mode` | bool | `true`/`false` | **`true` ⇒ ИИ на паузе** (источник истины для UI-гейта) |
| `handoff_state` | enum | `none` \| `requested` \| `operator` \| `returned` | жизненный цикл |
| `handoff_reason` | enum\|null | `book_click` \| `booking_intent` \| `phrase` \| `contact` \| `manual` | почему подняли |
| `operator_mode_since` | ISO8601\|null | — | когда включился operator_mode |
| `operator_actor` | str\|null | имя/идентификатор менеджера | кто за рулём (для баннера) |

> `operator_mode` дублирует `handoff_state ∈ {requested, operator}` намеренно: ЛК гейтит
> UI по одному булеву, не разбирая enum.

**Машина состояний (MGP-owned):**
```
none ──(жёсткий триггер)─► requested ──(/handoff take | ответ оператора)─► operator
  ▲                              │                                            │
  └──── returned ◄───────────────┴───(/handoff return | авто-возврат 10 мин)──┘
```
- Жёсткие триггеры (пауза+анонс+`manager_alert`): `book_click`, `phrase`, `contact`.
- Мягкий (только `manager_alert`, ИИ продолжает): `booking_intent`.

Метка для UI по `handoff_reason` (рекомендация ЛК):
`book_click`→«Клик Забронировать», `booking_intent`→«Намерение брони»,
`phrase`→«Просит менеджера», `contact`→«Оставил контакт», `manual`→«Ручной перехват».

---

## 3. События MGP → LK (`POST …/runtime/events`)

ЛК добавляет оба типа в `accepted_event_types` (рядом с `conversation_snapshot`).

### 3.1 `manager_alert` — нужен менеджер
```json
{
  "contract_version": "2026-03-09",
  "event_type": "manager_alert",
  "assistant_id": "593471b7-…",
  "conversation_id": "…",
  "occurred_at": "2026-06-09T08:00:00Z",
  "conversation": { "...": "полный блок conversation (см. §2 + существующие поля)" },
  "alert": {
    "reason": "book_click|booking_intent|phrase|contact|manual",
    "severity": "hot",
    "preview": "<последнее сообщение клиента, ≤200 симв.>",
    "requested_at": "2026-06-09T08:00:00Z",
    "deep_link": "/conversations/<conversation_id>?src=alert"
  }
}
```
**ЛК на приём:** upsert диалога (записать поля §2), создать запись уведомления →
in-app колокольчик + **web-push** всем менеджерам тест-компании с `deep_link`.

### 3.2 `operator_inbound` — клиент написал при активном операторе
```json
{
  "contract_version": "2026-03-09",
  "event_type": "operator_inbound",
  "assistant_id": "593471b7-…",
  "conversation_id": "…",
  "occurred_at": "2026-06-09T08:01:00Z",
  "conversation": { "...": "полный блок conversation" },
  "message": {
    "remote_id": 123456,
    "role": "user",
    "content": "…",
    "created_at": "2026-06-09T08:01:00Z"
  }
}
```
**ЛК на приём:** upsert сообщения с дедупом по `(conversation_id, remote_id)` (как в
снапшоте), пересчитать rollup, поднять push «клиент ответил».

> **Сообщения менеджера** (operator→клиент) НЕ требуют отдельного события: MGP пишет их
> как `role='operator'` и они приедут в обычном `conversation_snapshot`. Активный
> менеджер видит своё сообщение сразу из ответа ручки (§4.1); другие менеджеры — через
> ускоренный поллинг/снапшот.

---

## 4. Ручки LK → MGP (HTTPS, `https://max.navilet.ru`)

`Base = MGP_OPERATOR_BASE_URL = https://max.navilet.ru` (НЕ `bot_server_url`, он HTTP).
Заголовки: `X-MGP-Service-Token: <MGP_OPERATOR_TOKEN>`, `Content-Type: application/json`.
Проверка токена — строгая. Вызовы — только серверно из ЛК-бэкенда (токен не во фронте).

### 4.1 `POST /api/runtime/operator/message` — ответ менеджера клиенту
Request:
```json
{
  "assistant_id": "593471b7-…",
  "conversation_id": "…",
  "session_id": "max-299320353-…",
  "channel": "max",
  "external_chat_id": "…",
  "external_user_id": "…",
  "text": "Здравствуйте! …",
  "operator": { "id": "u123", "name": "Павел" }
}
```
Response `200`:
```json
{ "status": "sent", "message_id": 123457, "remote_id": 123457, "delivered": true }
```
Ошибки: `401` неверный токен · `403` фича выкл/ассистент не в allow-list ·
`409` `channel!='max'` или диалог не в operator-режиме · `422` нет `external_chat_id` ·
`502` MAX отверг отправку.
**MGP делает:** валидация (флаг+allow-list+channel) → `max_api.send_message(external_chat_id,text)`
бот-токеном тенанта → пишет `role='operator'` → `operator_last_activity_at=now` →
ответ. (operator-сообщение прилетит в LK снапшотом — §3.2 прим.)

### 4.2 `POST /api/runtime/operator/handoff` — перехват / возврат
Request:
```json
{ "assistant_id":"593471b7-…", "conversation_id":"…", "action":"take|return",
  "operator": { "id":"u123", "name":"Павел" } }
```
Response `200`:
```json
{ "status":"ok", "operator_mode": true, "handoff_state":"operator" }
```
- `take` → `operator_mode=true`, `handoff_state='operator'`, `operator_actor=<name>`,
  `operator_mode_since=now`.
- `return` → `operator_mode=false`, `handoff_state='returned'`.
**MGP** эмитит `conversation_snapshot` (эхо) → ЛК синхронизирует баннер.

---

## 5. Авто-возврат к ИИ (MGP-internal, 10 мин)

Монитор (по образцу `warm_nudge_monitor.py` + `scheduler.py`): если `operator_mode=true`,
есть неотвеченное сообщение клиента и прошло ≥ **10 мин** от
`max(operator_mode_since, operator_last_activity_at)` → MGP поднимает диалог из БД с
полной памятью (`_restore_handler_from_db`), ИИ отвечает по сути, затем
`operator_mode=false`, `handoff_state='returned'`. ЛК узнаёт через снапшот + push
«ИИ продолжил диалог». На стороне ЛК спец-логика не нужна (только отрисовать состояние).

---

## 6. Что подготовить на стороне ЛК — ЧЁТКИЙ чек-лист

**Блокер старта MGP (нужно сразу):**
- [ ] **B1.** Тест-компания + аккаунт-логин в `lk.navilet.ru`.
- [ ] **B2.** Сгенерировать `shared_secret` под UUID **593471b7** и **прислать мне**
      (для reporting MGP→LK). Endpoint = `…/runtime/events`.
- [ ] **B3.** Смаппить **593471b7 → тест-компания**. AnyTour `64fea0d3` НЕ трогать.

**Параллельно (разработка ЛК):**
- [ ] **L1. БД-реплика:** добавить в `conversations` колонки `operator_mode`(bool, default false),
      `handoff_state`(varchar16, default 'none'), `handoff_reason`(varchar24, null),
      `operator_mode_since`(timestamptz, null), `operator_actor`(varchar64, null).
- [ ] **L2. Приёмник:** обрабатывать `event_type` `manager_alert` и `operator_inbound`
      (§3); читать новые поля §2 из `conversation`; дедуп `operator_inbound` по
      `(conversation_id, remote_id)`.
- [ ] **L3. Прокси-ручки (JWT, tenant-scoped):**
      `POST /api/dashboard/conversations/:id/operator-message {text}` → MGP §4.1;
      `POST /api/dashboard/conversations/:id/handoff {action:"take|return"}` → MGP §4.2.
      Хранить `MGP_OPERATOR_BASE_URL=https://max.navilet.ru` и `MGP_OPERATOR_TOKEN`
      (дам я) в env ЛК-бэкенда; токен **никогда** во фронт.
- [ ] **L4. Web-push:** VAPID-ключи, таблица push-подписок + endpoint `subscribe`,
      обработчики `push` и `notificationclick` в service worker (PWA уже установлен).
      На `manager_alert` → push менеджерам тест-компании с `deep_link`.
- [ ] **L5. UI карточки диалога:** поле ответа + «Отправить»; кнопки «Перехватить» /
      «Вернуть боту»; баннер «Менеджер за рулём» (из `operator_mode`/`handoff_state`/
      `operator_actor`); ускоренный поллинг открытого диалога (3–5с вместо 60с).
- [ ] **L6. Deep-link:** роут `/conversations/:id?src=alert`; после логина —
      `/login?next=…` → редирект в диалог.
- [ ] **L7. Гейт UI:** операторский UI/пуши показывать ТОЛЬКО при `channel=='max'` И
      `assistant_id` ∈ allow-list (сейчас только 593471b7). Реальные компании
      (включая AnyTour) и `channel='widget'` — без изменений.

**Тексты клиенту — без эмодзи** (эмодзи только в пушах менеджеру). Анонс при handoff
один раз; реплики менеджера — без префикса/имени.

---

## 7. Что делает MGP (я), когда ЛК отдаст B1–B3

1. Применю reporting-секрет к 593471b7 → события поедут в тест-компанию (только его
   строка `runtime_metadata`, обратимо).
2. Соберу Ф.A под флагом OFF, scope = MAX + allow-list(593471b7):
   миграция (§2 колонки + `operator_last_activity_at`), модель, флаг
   `runtime_metadata.features.manager_handoff`, гейт ИИ в `chat_v1`, триггеры
   (`book_click` из `booking_redirect`, `booking_intent`/`phrase`/`contact` в чате),
   ручки §4, события §3, авто-возврат §5, подавление в `max_bridge`.
3. Добавлю nginx-locations `/api/runtime/operator/*` на `max.navilet.ru` → backend;
   выдам ЛК `MGP_OPERATOR_TOKEN`.
4. Включу флаг только на 593471b7 → e2e: ты пишешь `@id9705243471_bot` → триггер →
   push в тест-кабинет → перехват → ответ → клиент видит в MAX → 10 мин тишины → ИИ
   продолжает.

---

## 8. Несовпадения с черновиком ЛК (учесть при сборке)

- `operator_mode` — **boolean**, не строка `"bot|operator"`. Гранулярность — в
  `handoff_state`.
- `handoff_reason` — таксономия MGP (`book_click|booking_intent|phrase|contact|manual`),
  не `client_requested|bot_escalation|keyword`. Ярлыки для UI — §2.
- Back-channel base — `https://max.navilet.ru` (НЕ `bot_server_url=http://72.56.88.193`):
  HTTP не годится для токена/текста.
- Пути ручек MGP — `/api/runtime/operator/message` и `/api/runtime/operator/handoff`
  (namespaced), а не плоские `/operator-message`.
