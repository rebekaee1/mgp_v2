# MGP AI Travel Bot

AI-ассистент турагентства с поиском туров через TourVisor API.

## Стек

| Компонент     | Технология                                |
|---------------|-------------------------------------------|
| Backend       | Flask + Gunicorn (Python 3.12)            |
| Frontend      | Vanilla HTML/CSS/JS + Nginx              |
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
docker compose up -d --build
```

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

## Логирование

Все диалоги логируются в PostgreSQL (таблицы `conversations`, `messages`, `tour_searches`, `api_calls`) для будущего личного кабинета и аналитики. При недоступности БД — fallback в файловые логи.
