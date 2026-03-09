# MGP AI Travel Bot

AI-ассистент турагентства с поиском туров через TourVisor API.

Текущий production-профиль: `backend-only runtime`.
Публичный widget/embed живёт в `LK`, а `MGP` принимает runtime chat traffic и отдает health/runtime metadata.

## Стек

| Компонент     | Технология                                |
|---------------|-------------------------------------------|
| Backend       | Flask + Gunicorn (Python 3.12)            |
| Frontend      | Legacy only; production widget is served from LK |
| LLM           | OpenAI (OpenRouter) / YandexGPT           |
| Database      | PostgreSQL 16                             |
| Cache         | Redis 7                                   |
| API           | TourVisor XML API                         |
| Deploy        | Docker Compose                            |

## Быстрый старт (Docker)

```bash
# 1. Клонировать и настроить
git clone <repo-url> && cd mgp-prod-1
cp .env.example .env
nano .env  # заполнить API ключи

# 2. Запустить
docker compose up -d --build

# 3. Открыть
open http://localhost
```

## Локальная разработка (без Docker)

```bash
cd backend
pip install -r requirements.txt
cp .env.example ../.env  # или используйте backend/.env
python app.py
# → http://localhost:8080
```

## Деплой на Timeweb

```bash
ssh user@server
git clone <repo-url> && cd mgp-prod-1
cp .env.example .env && nano .env
./deploy/deploy-runtime.sh
```

Подробный runtime-only профиль и provisioning contract: `RUNTIME_DEPLOY.md`.

## Структура проекта

```
├── backend/
│   ├── app.py              # Flask routes, SSE streaming
│   ├── config.py           # Pydantic settings
│   ├── database.py         # SQLAlchemy engine/session
│   ├── models.py           # ORM модели (conversations, messages, ...)
│   ├── cache.py            # Redis wrapper
│   ├── yandex_handler.py   # YandexGPT handler
│   ├── openai_handler.py   # OpenAI handler
│   ├── tourvisor_client.py # TourVisor API client
│   ├── alembic/            # Database migrations
│   ├── Dockerfile
│   └── entrypoint.sh
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── script.js
│   ├── nginx.conf
│   └── Dockerfile
├── system_prompt.md        # System prompt for LLM
├── function_schemas.json   # Tool definitions
├── faq.md                  # Knowledge base
├── docker-compose.yml
├── .env.example
└── README.md
```

## Мониторинг

- `GET /api/health` — health check (PostgreSQL + Redis)
- `GET /api/status` — active sessions count
- `GET /api/metrics` — AI assistant metrics
- `GET /api/runtime/metadata` — runtime metadata для control-plane
- `GET /api/runtime/status` — runtime status для provisioning/orchestration

## Логирование

Все диалоги логируются в PostgreSQL (таблицы `conversations`, `messages`, `tour_searches`, `api_calls`) для будущего личного кабинета и аналитики. При недоступности БД — fallback в файловые логи.

## Provisioning

Новый tenant можно поднимать без правки кода:

```bash
python backend/cli.py provision-tenant \
  --email smoke-test@example.com \
  --password 'not-used-in-dry-run' \
  --company 'Smoke Test Company' \
  --slug smoke-test-company \
  --dry-run

# реальный запуск:
python backend/cli.py provision-tenant \
  --email admin@example.com \
  --password 'strong-password' \
  --company 'New Company' \
  --slug new-company
```

Дополнительные tenant-настройки (`allowed_domains`, `bot_server_url`, branding, prompt/faq, ключи) передаются через env/CLI.
