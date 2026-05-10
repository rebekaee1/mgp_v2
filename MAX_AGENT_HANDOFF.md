# MAX Messenger Integration — Handoff для нового агента

> **Создано:** 8 мая 2026 (после успешной верификации юрлица в MAX).
> **Цель документа:** дать новому агенту в этой папке всё, что нужно, чтобы поднять бот основного офиса МГП Тур (`mgp-tour`) в мессенджере MAX, не повредив существующий runtime.

---

## 0. TL;DR — что делаем и зачем

Подключаем основной офис МГП Тур к мессенджеру MAX. У МГП уже работает AI-ассистент в виджете на сайте `mgp.ru` — нужно отдать тот же диалоговый движок (тот же `assistant_id`, та же логика поиска тура, та же CRM, та же email-копия лида) в новый канал — мессенджер MAX.

Юрлицо ООО МГП Тур **уже верифицировано** в MAX для бизнеса (профиль ID `12822510`). То есть формальный блокер снят, можно создавать бота.

**Архитектурное решение** — не трогаем основной `mgp-backend`, поднимаем **отдельный микросервис `mgp-max-bridge`**, который:
- Принимает webhook от MAX → конвертирует входящие сообщения в вызов нашего же `POST /api/v1/chat`.
- Получает ответ ассистента (текст + `tour_cards`) → рендерит в MAX-нативные сообщения (markdown + image attachment + inline_keyboard).
- Хранит маппинг `MAX user_id → session_id` в Redis (24-часовый TTL).
- Деплоится как **ещё один контейнер в существующем `docker-compose.yml`** на том же сервере.

Никакой код в `backend/yandex_handler.py`, `backend/runtime_config.py`, `backend/uon_client.py`, `backend/email_sender.py` **трогать не надо** — bridge ходит к chat API через те же контракты, что виджет на сайте.

---

## 1. Состояние работы (что уже сделано)

| Что | Статус | Где смотреть |
|---|---|---|
| Архитектурное исследование MAX Bot API | ✅ готово | `dev.max.ru/docs-api` (актуально на 8 мая 2026) |
| Решение по карточкам тура | ✅ принято — гибрид: один тур = одно сообщение image + markdown + inline_keyboard; 5+ туров — текстовый список с кнопками выбора | canvas `mgp-max-integration-plan.canvas.tsx` (раздел «Как карточки тура лягут в MAX») |
| Решение по сессиям | ✅ Redis-маппинг `max:user:<id> → session_id`, TTL 24 ч | этот файл, раздел 4 |
| Решение по архитектуре | ✅ отдельный микросервис, новый контейнер в нашем compose | этот файл, раздел 4 |
| Верификация юрлица в MAX | ✅ профиль ID 12822510 подтверждён | `business.max.ru/self` (личный кабинет пользователя) |
| Бот через `@MasterBot` | ⏳ **нужно создать** — это первый шаг агента-исполнителя или владельца | см. раздел 6 |
| Домен под webhook | ⏳ **нужно решить** — рекомендация `bot.mgp.ru` (поддомен) | см. раздел 7 |
| Юр-вопрос 152-ФЗ (где хранить webhook) | ⚠️ открыт — **обсудить с юристом МГП** до запуска в прод | см. раздел 8 |

---

## 2. Существующая архитектура — как устроен runtime сейчас

### 2.1 Production-топология

| Параметр | Значение |
|---|---|
| Хост | `72.56.88.193` (Timeweb Cloud, Amsterdam) |
| Hostname | `ams-1-vm-hyto` |
| OS | Ubuntu (cloud VM, 1 CPU / 2 GB RAM) |
| User | `mgpadmin` (root login отключён, password auth отключён) |
| SSH | только по ключу |
| SSH alias на локальной машине | `mgp-prod` (`~/.ssh/config`) — `ssh mgp-prod` работает |
| Project path | `/opt/mgp` |
| Public HTTP | nginx на `:80` |
| Backend | Flask + Gunicorn, слушает `127.0.0.1:8080` (за nginx) |

Контейнеры (все healthy на момент составления handoff):

```
mgp-backend-1    Up (healthy)
mgp-postgres-1   Up (healthy)
mgp-redis-1      Up (healthy)
```

### 2.2 Runtime API (в этот же API будет ходить bridge)

| Метод | Путь | Назначение для нашей задачи |
|---|---|---|
| `POST /api/v1/chat` | JSON-режим | **главный endpoint для bridge** |
| `POST /api/chat/stream` | SSE | используется виджетом на сайте, в MAX не понадобится |
| `GET /api/health` | health-check | для smoke-теста и алертов |
| `GET /api/runtime/status` | runtime status | для observability |
| `GET /api/runtime/metadata?assistant_id=...` | runtime metadata | для проверки tenant config |

**Контракт `POST /api/v1/chat`:**

Headers:
- `X-Assistant-Id: 593471b7-42da-4ae0-8499-904dcedd6a4b` — UUID `mgp-tour`.
- `X-MGP-Service-Token: <runtime_service_auth_secret>` — shared secret (значение есть в `/opt/mgp/.env` на проде, ключ `RUNTIME_SERVICE_AUTH_SECRET`; режим `RUNTIME_SERVICE_AUTH_MODE` сейчас `monitor` — токен валидируется, но не строго блокирует, см. `RUNTIME_DEPLOY.md`).
- `Content-Type: application/json`

Body (минимум):
```json
{
  "session_id": "max-<max_user_id>-<rotating_token>",
  "message": "<текст пользователя>",
  "assistant_id": "593471b7-42da-4ae0-8499-904dcedd6a4b"
}
```

Response (то, что нужно отрисовать в MAX):
```json
{
  "reply": "<markdown текст ассистента>",
  "tour_cards": [
    {
      "hotel_name": "...",
      "image_url": "https://...",
      "price": "...",
      "dates": "...",
      "hotel_link": "https://mgp.ru/tours#tvtourid=...",
      "meal_description": "...",
      ...
    }
  ],
  "session_id": "...",
  ...
}
```

### 2.3 Карта существующих тенантов (на проде)

Берём этот список через `psql` (новый агент сможет проверить):

| slug | assistant_id | Название | active |
|---|---|---|---|
| **mgp-tour** ⭐ | `593471b7-42da-4ae0-8499-904dcedd6a4b` | МГП Тур (главный офис) — **наш пилот** | true |
| mgp-vyhino | `9fa598f9-57b6-49b5-9ccb-195555cd1baa` | МГП Выхино | true |
| mgp-belgorod | `d14633da-bb3a-4305-90ce-877d757fc7b3` | МГП Белгород | true |
| mgp-kirishi | `1a7f1b86-3aa0-4edd-a911-568a25d19df3` | МГП Кириши | true |
| mgp-krasnogorsk | `fedfe143-554c-4dd6-ae3a-37ff6f81a021` | МГП Красногорск | true |
| mgp-shelkovo | `d5c16833-539b-4ed9-a6d6-042cc0064be8` | МГП Щёлково | true |
| mgp-tambov | `13ec306b-cc48-4585-8fa1-0216a0afdc3d` | МГП Тамбов | true |

> ⚠️ Все остальные branch-аккаунты — **на втором этапе**. Сначала пилотируем только `mgp-tour`. Архитектура bridge должна быть multi-tenant-ready с самого начала (см. раздел 4.4), но в DB регистрируется только один бот.

### 2.4 Стек существующего бэкенда

- **Flask 3 + Gunicorn**, Python 3.12
- **PostgreSQL 16**: таблицы `assistants`, `companies`, `conversations`, `messages`, `api_calls`, `tour_searches`, `runtime_event_outbox`
- **Redis 7**: кеш, сессии, blacklist
- **OpenAI** через **OpenRouter** (`OPENAI_BASE_URL=https://openrouter.ai/api/v1`, модель `openai/gpt-5-mini`)
- **TourVisor** XML API для туров
- **U-ON CRM** для лидов (`backend/uon_client.py`) + email-копия (`backend/email_sender.py`, `send_lead_email`)
- **Reporting MGP→LK** через `runtime_event_outbox` + `dialog_sender` (см. `RUNTIME_DEPLOY.md`)

---

## 3. MAX Bot API — что используем

> Источник: https://dev.max.ru/docs-api (актуально на 8 мая 2026).

| Возможность | Где используем | Лимит |
|---|---|---|
| `POST /subscriptions` (регистрация webhook) | один раз при провижене бота | — |
| `POST /messages` с `text` + `format=markdown` | текст ответа ассистента | 4000 символов на сообщение |
| `attachment: image` (URL или uploaded token) | фото отеля в карточке тура | URL должен быть HTTPS |
| `attachment: inline_keyboard` | кнопки под сообщением: «Подробнее», «Хочу этот», «Другие даты» | 210 кнопок макс., 7 в строке |
| `button.type=link` | ссылка на `mgp.ru/tours#tvtourid=...` | URL ≤ 2048 символов |
| `button.type=callback` | передаём `tourid` в payload, парсим в bridge | до 1024 байт |
| `button.type=request_contact` | получаем телефон клиента из MAX-аккаунта (с HMAC-проверкой) | требует клика клиента |
| `button.type=open_app` | mini-app — escape hatch на фазе 5+ | требует отдельной верификации mini-app |
| **Webhook** | MAX шлёт нам обновления на `https://bot.mgp.ru/max/webhook` | 30 RPS на бота, HTTPS обязателен (можно self-signed), таймаут 30 сек |

**Важные ограничения:**
- 4000 символов в одном сообщении → bridge должен **сплитить длинные ответы ассистента**.
- 30 RPS на исходящие → если ассистент выдаёт 6+ карточек подряд, нужен throttle ~25 rps + очередь.
- Webhook должен ответить за 30 сек → **обработка в фоне**, ответ MAX'у моментально (`200 OK` без тела).

**Авторизация** в `POST /messages`: header `Authorization: <bot_access_token>`. Токен получается при создании бота через `@MasterBot`.

**Валидация входящего webhook:** MAX в `Authorization` шлёт **наш собственный** `bot_access_token` (защита от подделки). Bridge должен проверять, что в каждом входящем запросе `Authorization == MAX_BOT_TOKEN_MGP_TOUR`.

---

## 4. Целевая архитектура — `mgp-max-bridge`

### 4.1 Общая схема

```
┌─────────────────────────────────────────────────────────────────┐
│                    MAX Messenger (платформа VK)                 │
│                  platform-api.max.ru / webhook                  │
└──────────┬───────────────────────────────────────▲──────────────┘
           │ POST /max/webhook                     │ POST /messages
           │ (входящие сообщения, callback'и)      │ (текст + image + кнопки)
           ▼                                       │
┌─────────────────────────────────────────────────────────────────┐
│                     mgp-max-bridge (NEW)                        │
│        FastAPI / Python 3.12, контейнер в docker-compose        │
│                                                                 │
│  • валидация Authorization == MAX_BOT_TOKEN                     │
│  • Redis: max:user:<id> → session_id (TTL 24h)                  │
│  • httpx → POST mgp-backend:8080/api/v1/chat                    │
│  • рендер ответа в MAX-сообщения (текст / image / inline_kbd)   │
│  • throttle 25 rps, retry на 5xx, dead-letter в Redis           │
└──────────┬─────────────────────────────────────▲────────────────┘
           │ http://mgp-backend:8080/api/v1/chat │
           │ X-Assistant-Id: 593471b7-...        │
           ▼                                     │
┌─────────────────────────────────────────────────────────────────┐
│              mgp-backend (EXISTING — НЕ ТРОГАЕМ)                │
│       Flask + Gunicorn, /api/v1/chat, YandexHandler, tools      │
│           U-ON CRM, email-дублирование, reporting в LK          │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Структура нового сервиса

```
services/
└── max_bridge/
    ├── Dockerfile
    ├── requirements.txt          # fastapi, uvicorn, httpx, redis, structlog
    ├── pyproject.toml
    ├── app/
    │   ├── main.py               # FastAPI app + lifespan + health
    │   ├── config.py             # pydantic-settings (env vars)
    │   ├── max_api.py            # клиент platform-api.max.ru (POST /messages, /subscriptions)
    │   ├── chat_proxy.py         # httpx → mgp-backend /api/v1/chat
    │   ├── session_store.py      # redis-обёртка для max:user:<id> ↔ session_id
    │   ├── renderers.py          # tour_cards → MAX attachments + inline_keyboard
    │   ├── webhook.py            # POST /max/webhook (роутер)
    │   ├── throttle.py           # rate-limiter 25 rps
    │   └── observability.py      # structlog + Prometheus метрики
    └── tests/
        ├── test_renderers.py
        ├── test_webhook.py
        └── test_session_store.py
```

### 4.3 Поток сообщений

1. Клиент пишет боту в MAX → MAX делает `POST https://bot.mgp.ru/max/webhook` с заголовком `Authorization: <наш_token>` и телом `{ update_type: "message_created", message: { sender: { user_id }, body: { text } } }`.
2. `mgp-max-bridge` валидирует токен, отвечает MAX `200 OK` сразу, обработку ставит в фоновую задачу (`asyncio.create_task`).
3. Lookup `max:user:<id>` в Redis → если нет, генерируем `session_id = f"max-{user_id}-{uuid4()[:8]}"`, кладём в Redis с TTL 24 ч.
4. `POST http://mgp-backend:8080/api/v1/chat` с `X-Assistant-Id: 593471b7-...`, `X-MGP-Service-Token: <secret>`, body `{ session_id, message, assistant_id }`.
5. Получаем `{ reply, tour_cards }`.
6. Рендерер:
   - Если `tour_cards` пуст → `POST /messages` с `text=reply` (markdown). Если `len(reply) > 4000` — сплитим на части по абзацам/предложениям.
   - Если `tour_cards` есть — отправляем `reply` как короткое введение, потом для каждой карточки отдельный `POST /messages` с `attachments: [{type:"image", payload:{url:image_url}}, {type:"inline_keyboard", payload:{buttons:[[{text:"Подробнее", type:"link", url:hotel_link}, {text:"Хочу этот", type:"callback", payload:"select:<tourid>"}]]}}]`.
7. Если ассистент вызвал `submit_client_request` → CRM-заявка падает по тому же пути, что и из виджета (никакого дополнительного кода не нужно — это уже работает в основном backend).

### 4.4 Multi-tenant ready (на будущее)

Bridge должен поддерживать map `bot_token → assistant_id`, чтобы потом легко добавить ботов остальных филиалов без рефакторинга:

```python
TENANT_BOTS = {
    "<MAX_BOT_TOKEN_MGP_TOUR>":    {"assistant_id": "593471b7-42da-4ae0-8499-904dcedd6a4b", "slug": "mgp-tour"},
    # позже:
    # "<MAX_BOT_TOKEN_MGP_VYHINO>":  {"assistant_id": "9fa598f9-...", "slug": "mgp-vyhino"},
    # "<MAX_BOT_TOKEN_MGP_BELGOROD>":{"assistant_id": "d14633da-...", "slug": "mgp-belgorod"},
}
```

На фазе 1 — только `mgp-tour`, остальные слоты прокидываем заглушками.

### 4.5 Что **не трогаем** в существующем коде

- `backend/yandex_handler.py` (логика ассистента, function calling)
- `backend/runtime_config.py` (тенантная конфигурация)
- `backend/uon_client.py` (CRM)
- `backend/email_sender.py` (email-дублирование лидов — уже работает для `mgp-tour`, см. `widget_config.lead_email_enabled`)
- `backend/dialog_sender.py` (reporting MGP→LK)
- `backend/app.py` за исключением, возможно, добавления одного безопасного internal endpoint, если bridge'у понадобится что-то, чего нет в `/api/v1/chat`. Но **по умолчанию — не трогаем**.

---

## 5. Доступы и креды (всё, что нужно агенту)

### 5.1 Локальная разработка (эта папка)

| Что | Где | Значение / комментарий |
|---|---|---|
| Repo path | `/Users/lukiansilagadze/Desktop/МГП ОСНОВНОЙ АССИСТЕНТ` | (текущий workspace) |
| `.env` (локальный) | `./.env` | значения OK для локального dev (порт 8080, пароли БД `localtest2026`) |
| OpenRouter ключ (тот же, что на проде) | `./.env` → `OPENAI_API_KEY` | `sk-or-v1-266f...bcbc9` (хватит для разработки и теста) |
| TourVisor login/pass | `./.env` → `TOURVISOR_AUTH_LOGIN/PASS` | `online@mgp.ru / 1mFIsdqQ473m` |
| Поднять локально | `./deploy/deploy-runtime.sh` или `docker compose up -d` | контейнеры станут `mgp-postgres-1, mgp-redis-1, mgp-backend-1` |

### 5.2 Production-сервер

| Параметр | Значение |
|---|---|
| Host | `72.56.88.193` |
| User | `mgpadmin` |
| SSH alias | `mgp-prod` (уже настроен в `~/.ssh/config`) |
| Способ входа | по ключу (private key уже на машине пользователя) |
| Project path | `/opt/mgp` |
| `.env` | `/opt/mgp/.env` (читать через `sudo cat`) |
| Docker | `sudo docker compose ps`, `sudo docker exec mgp-postgres-1 psql -U mgp -d mgp ...` |

**Команды-смоук для проверки доступа** (агент должен выполнить первой ракетой):

```bash
# 1) SSH работает, контейнеры live
ssh mgp-prod "sudo docker compose ps"

# 2) Backend отвечает
ssh mgp-prod "curl -s http://127.0.0.1:8080/api/health"

# 3) DB читается
ssh mgp-prod 'sudo docker exec mgp-postgres-1 psql -U mgp -d mgp -t -A -c "SELECT count(*) FROM assistants;"'

# 4) Локально docker compose поднимается
docker compose up -d && curl -s http://localhost:8080/api/health
```

### 5.3 Что НЕ хранится в репо и нужно от пользователя

| Имя | Где взять | Когда понадобится |
|---|---|---|
| **`MAX_BOT_TOKEN_MGP_TOUR`** | создать бота через `@MasterBot` в MAX (`/create` → ник `mgp_tour_bot` или похожий, оканчивающийся на `bot/_bot`, длина ≥ 10 символов; токен MAX отдаст в чате с `@MasterBot`) | в начале фазы 1 (без него bridge работать не сможет) |
| **Webhook URL** | DNS-запись `bot.mgp.ru` → IP `72.56.88.193` + Let's Encrypt cert. Альтернатива: `https://mgp.ru/max-webhook` через nginx prefix-route. | в начале фазы 1 (нужно зарегистрировать через `POST /subscriptions` в MAX API) |
| **`RUNTIME_SERVICE_AUTH_SECRET`** | прод `/opt/mgp/.env` (читается через SSH) — ключ `RUNTIME_SERVICE_AUTH_SECRET` | при деплое bridge на прод (для аутентификации в `/api/v1/chat`) |

### 5.4 ENV-переменные для нового сервиса `mgp-max-bridge`

Добавить в `.env` (и пробросить в docker-compose сервис):

```bash
# === MAX Bridge ===
MAX_BOT_TOKEN_MGP_TOUR=<получить от @MasterBot>
MAX_API_BASE_URL=https://botapi.max.ru
MAX_WEBHOOK_PUBLIC_URL=https://bot.mgp.ru/max/webhook   # или https://mgp.ru/max-webhook
MAX_WEBHOOK_LISTEN_PORT=8090
MAX_BACKEND_INTERNAL_URL=http://backend:8080            # доступ внутри docker network
MAX_BACKEND_SERVICE_TOKEN=${RUNTIME_SERVICE_AUTH_SECRET}
MAX_REDIS_URL=${REDIS_URL}                              # тот же redis, отдельный db?
MAX_SESSION_TTL_SECONDS=86400
MAX_RATE_LIMIT_RPS=25
MAX_DEFAULT_ASSISTANT_ID=593471b7-42da-4ae0-8499-904dcedd6a4b
MAX_LOG_LEVEL=INFO
```

---

## 6. Поэтапный план работы

> Каждая фаза самодостаточна — между фазами можно показать результат.

### Фаза 0 — Diagnostic check (~30 минут)

1. Прочитать этот документ целиком, прочитать canvas `mgp-max-integration-plan.canvas.tsx`.
2. Прочитать `RUNTIME_DEPLOY.md` (контракт LK↔MGP, как backend защищён).
3. Прочитать `backend/yandex_handler.py:_handle_submit_client_request` и `_map_hotel_to_card` (понять какой `tour_cards` shape придёт).
4. Выполнить смоук-команды из 5.2.
5. Подтвердить пользователю, что всё понятно, и спросить токен бота от `@MasterBot` + DNS-запись.

### Фаза 1 — MVP «Hello, MAX» (2–3 дня)

**Цель:** написать боту в MAX → получить ответ нашего ассистента в виде текста (без карточек, без кнопок).

Tasks:
- [ ] Создать `services/max_bridge/` (см. структуру 4.2).
- [ ] FastAPI приложение с одним POST `/max/webhook` и GET `/health`.
- [ ] Валидация `Authorization` header против `MAX_BOT_TOKEN_MGP_TOUR`.
- [ ] Распарсить `update_type=message_created`, вытащить `sender.user_id` и `body.text`.
- [ ] Redis: `get_or_create_session(max_user_id)`.
- [ ] httpx → `POST $MAX_BACKEND_INTERNAL_URL/api/v1/chat` с правильными headers и body.
- [ ] Получить `reply`, обрезать/сплитить если > 4000 chars, отправить в MAX через `POST /messages` (markdown).
- [ ] Юнит-тесты: парсер webhook, session_store, splitter длинного текста.
- [ ] Локальный e2e-тест: ngrok-туннель на dev-машине → зарегистрировать bot webhook → написать боту → получить ответ.
- [ ] Добавить сервис в `docker-compose.yml`, в `deploy/deploy-runtime.sh` (если нужно).
- [ ] Деплой на прод: nginx vhost `bot.mgp.ru` → `127.0.0.1:8090` (или префикс), Let's Encrypt cert.

**Acceptance criteria фазы 1:**
- `curl https://bot.mgp.ru/max/webhook -d ...` возвращает `200 OK`.
- В MAX-чате бота: «Найди Турцию в июне» → приходит текстовый ответ от ассистента (тот же, что в виджете).
- `mgp-postgres-1` фиксирует диалог в `conversations` с `assistant_id = 593471b7-...`.

### Фаза 2 — карточки и кнопки (2 дня)

**Цель:** туры в чате с фото и интерактивными кнопками.

Tasks:
- [ ] Реализовать `renderers.py: render_tour_card(tour) -> MAXMessage`.
- [ ] Использовать `tour_cards[*].image_url` (TourVisor picturelink) как `attachment: image`.
- [ ] Markdown-блок: `**Hotel** · place\nDates\n2 adults · **price**`.
- [ ] `inline_keyboard`: кнопки `[Подробнее](link → hotel_link)`, `[Хочу этот](callback → "select:<tourid>")`, `[Другие даты](callback → "ask:other_dates")`.
- [ ] Callback handler: при `update_type=message_callback` парсим `payload`, конвертируем в обычное сообщение пользователя («расскажи про вариант 1» / «другие даты»), посылаем дальше в `/api/v1/chat`.
- [ ] Гибридный режим: если `tour_cards.length > 3`, отправляем сначала текстовый список с кнопками-выборами, по выбору — отправляем полную карточку.
- [ ] Fallback на отсутствие `image_url` или 404 на picturelink: пропускаем attachment, оставляем только текст + кнопки.

**Acceptance criteria фазы 2:**
- Запрос «Турция в июне на 2 взрослых» → 1–3 карточки с фото и кнопками.
- Клик «Подробнее» → открывается `mgp.ru/tours#tvtourid=...`.
- Клик «Хочу этот» → ассистент в следующем сообщении начинает оформление (запрашивает имя/контакт).

### Фаза 3 — лид и CRM (1 день)

**Цель:** клиент в MAX оставляет заявку → она падает в ту же U-ON CRM, что из виджета.

Tasks:
- [ ] Реализовать кнопку `request_contact` в момент, когда ассистент готов оформить заявку (триггер: ассистент в ответе попросил телефон).
- [ ] Принять `update_type=message_callback` с `vcf_info`, проверить HMAC по схеме MAX (см. dev.max.ru → request_contact).
- [ ] Полученный телефон отдать в обычный диалог через `/api/v1/chat` как сообщение пользователя в формате, который ассистент уже понимает (тестировать!).
- [ ] Убедиться, что `submit_client_request` отрабатывает и приходит U-ON-карточка + email-дубликат на `online@mgp.ru` (этот код **уже работает**, ничего нового не пишем).

**Acceptance criteria фазы 3:**
- Полный сценарий: «привет → турция в июне → выбор тура → нажатие «Хочу этот» → ассистент просит контакт → клик `request_contact` → CRM-заявка создана + email на `online@mgp.ru` пришёл».

### Фаза 4 — observability и регламент (1–2 дня)

Tasks:
- [ ] Structlog с `correlation_id` (один на webhook → chain до /messages).
- [ ] Prometheus метрики: входящие webhook'и, исходящие сообщения, латентность `/api/v1/chat`, ошибки 5xx, длина очереди rate-limiter'а.
- [ ] Алерты (хотя бы лог-based): >5% ошибок за 5 минут, p95 латентность > 8 сек.
- [ ] Короткий README в `services/max_bridge/README.md`: как запустить локально, как смотреть логи, как откатить.
- [ ] Запустить пилот в течение недели на одном офисе (или в отпуск-режиме), собрать первые метрики.

### Фаза 5 (опционально, после пилота) — mini-app

- Зарегистрировать widget на mgp.ru как mini-app в `@MasterBot`.
- Кнопка `open_app` в карточке для full-screen подбора тура.
- Не делать до окончания фазы 4.

---

## 7. Решения, которые нужны от владельца до старта фазы 1

| # | Что | Кто решает | Дефолт, если не решат |
|---|---|---|---|
| 1 | Ник бота в MAX | владелец (через `@MasterBot`) | `mgp_tour_bot` |
| 2 | Webhook host | владелец/DNS-админ | `bot.mgp.ru` (создать DNS A → 72.56.88.193) |
| 3 | TLS-сертификат | DevOps | Let's Encrypt через certbot на сервере |
| 4 | Имя бота, аватар, описание | маркетинг МГП | временно: «МГП Тур» + лого с mgp.ru |
| 5 | Хранить ли webhook в РФ (152-ФЗ) | юрист МГП | для пилота — оставляем в Амстердаме (как backend), фиксируем что MAX уже хранит ПДн в РФ; если юрист скажет «нет», поднимем bridge в Yandex Cloud РФ как зеркало |

---

## 8. Риски и как с ними жить

| Риск | Митигация |
|---|---|
| MAX поменяет API → bridge сломается | держим клиент `max_api.py` тонким, версионируем константы, мониторим CHANGELOG dev.max.ru |
| Picturelink TourVisor отдаёт 404 | renderer ловит ошибку attachment, отправляет текст без картинки |
| Длинный ответ ассистента (>4000) | `text_splitter.py`: делит по абзацам, потом по предложениям |
| Rate-limit MAX 30 RPS превышен на пиках | внутренний throttle 25 rps + очередь в Redis с FIFO |
| Webhook повторился (MAX не получил 200 за 30 сек) | dedup по `update_id` в Redis (TTL 1 час) |
| Bridge упал, сообщения потерялись | MAX делает retry до 3 раз с backoff — мы успеем подняться (ставим `restart: unless-stopped`) |
| 152-ФЗ — вопрос юриста | bridge можно вынести в Yandex Cloud РФ при необходимости (изолированный сервис, не трогает основной backend) |
| Клиент пишет ночью, ассистент задумался > 30 сек | webhook отвечает 200 моментально, ответ ассистента уходит позже отдельным `POST /messages` (асинхронно) |

---

## 9. Что НЕ должен делать новый агент

❌ Менять `backend/yandex_handler.py` или другие файлы внутри `backend/` (кроме крайней нужды и согласования).
❌ Создавать новых tenants в БД.
❌ Менять схемы существующих таблиц (`alembic upgrade` — табу).
❌ Деплоить bridge в прод **до** того, как:
  - токен от `@MasterBot` получен,
  - DNS и TLS на webhook host настроены,
  - локальный e2e-сценарий прошёл (ngrok + ассистент).
❌ Логировать `MAX_BOT_TOKEN_*` или `RUNTIME_SERVICE_AUTH_SECRET` в plain text.
❌ Логировать телефоны клиентов в plain text — маскировать (`+7***1234`).
❌ Трогать существующий nginx конфиг без согласования (только дополнить новый vhost для `bot.mgp.ru`).

---

## 10. Полезные ссылки

- **MAX Bot API docs:** https://dev.max.ru/docs-api
- **Бизнес-кабинет MAX:** https://business.max.ru/self (профиль `12822510`)
- **Архитектура runtime:** `RUNTIME_DEPLOY.md` (этот repo)
- **Deploy-практика:** `DEPLOY_NOTES.md` (этот repo)
- **План интеграции (визуал):** canvas `mgp-max-integration-plan.canvas.tsx`
- **CRM-аудит и метрики:** canvas `mgp-tour-crm-statuses.canvas.tsx`
- **Open questions:** canvas `open-questions-checklist.canvas.tsx`

---

## 11. Контрольный чек-лист первого дня (для агента)

```
[ ] Прочитал MAX_AGENT_HANDOFF.md (этот файл)
[ ] Прочитал RUNTIME_DEPLOY.md
[ ] Прочитал canvas mgp-max-integration-plan.canvas.tsx
[ ] Выполнил смоук-команды из раздела 5.2 — все вернули OK
[ ] Изучил backend/yandex_handler.py:_map_hotel_to_card (формат tour_cards)
[ ] Изучил docker-compose.yml (как добавлять новый сервис)
[ ] Создал ветку feature/max-bridge
[ ] Создал каркас services/max_bridge/ (Dockerfile, FastAPI app, requirements.txt)
[ ] Запросил у владельца MAX_BOT_TOKEN_MGP_TOUR
[ ] Запросил у владельца DNS / TLS для bot.mgp.ru
[ ] Согласовал план фазы 1 с владельцем
```

После прохождения чек-листа — приступать к фазе 1 (раздел 6).

---

**Last updated:** 2026-05-08, предыдущий агент.
**Если что-то непонятно — `agent-transcripts/a2d6aaa3-4109-4674-83fc-156b2a09d63c/` хранит всю предыдущую переписку с владельцем по этой задаче (читать через keyword search, файл большой).**
