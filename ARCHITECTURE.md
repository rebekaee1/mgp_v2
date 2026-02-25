# RuStats — Техническая архитектура

## Общее описание

RuStats — аналитическая платформа для мониторинга и прогнозирования инфляции в России. Платформа автоматически собирает данные Росстата, строит прогнозы с помощью OLS-модели и отображает результаты через веб-интерфейс.

Адрес: http://5.129.204.194
Сервер: Timeweb Cloud, Ubuntu 24.04, 1 CPU / 2 GB RAM / 30 GB NVMe, Москва

---

## Архитектура

```
Пользователь (браузер)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│                    Docker Compose                    │
│                                                     │
│  ┌───────────────────┐     ┌─────────────────────┐  │
│  │     Frontend       │     │      Backend        │  │
│  │                   │     │                     │  │
│  │  Nginx            │────▶│  FastAPI (Uvicorn)  │  │
│  │  - SPA (React)    │ /api│  - REST API         │  │
│  │  - Static файлы   │     │  - APScheduler      │  │
│  │  - Gzip           │     │  - OLS Forecaster   │  │
│  │  - Кеш assets 1y  │     │                     │  │
│  └───────────────────┘     └──────┬──────┬───────┘  │
│         :80                       │      │          │
│                              ┌────▼──┐ ┌─▼──────┐   │
│                              │Postgre│ │ Redis  │   │
│                              │SQL 16 │ │  7     │   │
│                              │       │ │        │   │
│                              │Данные │ │API-кеш │   │
│                              │Прогноз│ │TTL 1ч  │   │
│                              └───────┘ └────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
        │
        │ HTTPS (ежедневно в 06:00 МСК)
        ▼
┌───────────────┐
│   Росстат     │
│ rosstat.gov.ru│
│ (Excel-файлы) │
└───────────────┘
```

---

## Стек технологий

### Backend (Python 3.12)

| Инструмент | Версия | Назначение |
|---|---|---|
| FastAPI | 0.115+ | Async REST API фреймворк |
| Uvicorn | latest | ASGI-сервер |
| SQLAlchemy 2 | 2.0+ | ORM, async через asyncpg |
| asyncpg | latest | Async-драйвер PostgreSQL |
| Alembic | latest | Миграции базы данных |
| APScheduler | 3.x | Планировщик фоновых задач (cron) |
| statsmodels | latest | OLS-регрессия для прогнозирования |
| pandas / numpy | latest | Обработка данных, матричные операции |
| redis-py (async) | latest | Async-клиент Redis для кеширования |
| requests | latest | HTTP-клиент для загрузки с Росстата |
| openpyxl | latest | Парсинг Excel-файлов (.xlsx) |
| pydantic-settings | latest | Типизированная конфигурация из env-переменных |
| python-dateutil | latest | Работа с датами (relativedelta) |

### Frontend (Node 20)

| Инструмент | Версия | Назначение |
|---|---|---|
| React | 19 | UI-библиотека |
| Vite | 7 | Сборщик, HMR, оптимизация |
| Tailwind CSS | 4 | Utility-first CSS (темная тема "Midnight Luxe") |
| GSAP | 3 | Анимации (fade-up, stagger, number counters) |
| TanStack Query | 5 | Data fetching, кеширование, автообновление |
| Recharts | 2 | Графики (ComposedChart, Area, Line) |
| React Router | 7 | Маршрутизация SPA |
| Axios | latest | HTTP-клиент для API |
| Lucide React | latest | SVG-иконки |

### Инфраструктура

| Инструмент | Назначение |
|---|---|
| Docker Compose | Оркестрация 4 контейнеров |
| PostgreSQL 16 Alpine | Основная база данных |
| Redis 7 Alpine | Кеширование API-ответов (TTL 1 час) |
| Nginx Alpine | Раздача SPA + reverse proxy к API |
| Russian Trusted CA | SSL-сертификат для HTTPS к Росстату |

---

## Компоненты системы

### 1. ETL-пайплайн (автоматическое обновление данных)

Ежедневно в 06:00 по Москве APScheduler запускает цикл обновления:

```
APScheduler (cron 06:00 MSK)
    │
    ▼
RosstatFetcher
    │  HEAD-запросы к rosstat.gov.ru/storage/mediabank/ipc_mes_MM-YYYY.xlsx
    │  Перебирает от текущего месяца назад (до 6 мес.)
    │  Использует Russian Trusted CA для SSL
    │  Проверяет magic bytes (PK..) что это XLSX, а не HTML-ошибка
    ▼
Parser (parse_cpi_sheet)
    │  openpyxl читает pivot-таблицу Excel
    │  Извлекает месячные значения ИПЦ по всем годам
    │  4 листа: общий ИПЦ, продукты, непродовольственные, услуги
    ▼
Upsert в PostgreSQL
    │  INSERT ... ON CONFLICT DO NOTHING (идемпотентность)
    │  Сравнение COUNT до/после для определения новых записей
    ▼
OLS Retrain (если есть новые данные)
    │  Переобучение модели на полном наборе данных
    │  Генерация прогноза на 12 месяцев вперёд
    ▼
Cache Invalidation
    │  Сброс Redis-кеша для обновлённого индикатора
    ▼
Готово (логируется в fetch_log)
```

### 2. OLS Multi-Window Forecasting Model

Модель прогнозирования основана на взвешенной OLS-регрессии с несколькими окнами:

**Подготовка данных:**
- ИПЦ (например 100.5) преобразуется в доходность: `value / 100 - 1` = 0.005

**Для каждого горизонта прогноза (1..12 месяцев):**
1. Берутся 4 окна данных: полное, 1/2, 1/3, 1/4 от длины ряда
2. В каждом окне:
   - Создаются лаговые признаки (lag horizon+0, horizon+1, horizon+2)
   - Удаляются выбросы (>3 сигма → заменяются на 1.9 сигма)
   - Удаляются коллинеарные признаки (корреляция > 0.7)
   - Строится OLS-регрессия
   - Обратная элиминация по p-value (порог 0.01)
3. Предсказания 4 окон взвешиваются обратно пропорционально дисперсии (inverse-variance weighting)

**Результат:**
- 12 помесячных прогнозов ИПЦ (например 100.48)
- 95% доверительные интервалы для каждого месяца
- Кумулятивная 12-месячная инфляция (скользящее произведение)

### 3. API (8 эндпоинтов)

| Endpoint | Метод | Описание | Кеш |
|---|---|---|---|
| `/api/v1/health` | GET | Healthcheck | Нет |
| `/api/v1/indicators` | GET | Список индикаторов (code, name, last value) | 5 мин |
| `/api/v1/indicators/{code}` | GET | Детали индикатора + метаданные | 5 мин |
| `/api/v1/indicators/{code}/data` | GET | Все исторические точки | 1 час |
| `/api/v1/indicators/{code}/stats` | GET | Min, max, avg, std_dev | 1 час |
| `/api/v1/indicators/{code}/forecast` | GET | Помесячный прогноз OLS | 1 час |
| `/api/v1/indicators/{code}/inflation` | GET | Кумулятивная 12-мес. инфляция (факт + прогноз) | 1 час |
| `/api/v1/system/status` | GET | Кол-во индикаторов, точек, последний ETL | 5 мин |

Swagger-документация: `/api/docs`

### 4. Frontend (SPA)

**Две страницы:**
- **Dashboard** (`/`) — плитки индикаторов, системный статус, hero-секция
- **IndicatorDetail** (`/indicators/:code`) — телеметрические карточки, график инфляции, таблица прогноза, таблица данных

**Дизайн-система "Midnight Luxe":**
- Тёмная тема (bg: #0D0D12, surface: #16161E)
- Акцентный цвет: champagne (#C9A84C)
- Прогнозная линия: фиолетовая (#A78BFA)
- SVG noise overlay для текстуры
- rounded-[2rem] контейнеры
- GSAP-анимации: fade-up, stagger, number counter typewriter

**График инфляции (Recharts):**
- Линия "Факт" (золотая) — скользящая 12-месячная кумулятивная инфляция
- Линия "Прогноз" (фиолетовая, пунктир) — OLS-прогноз на 12 месяцев
- Заливка 95% CI (confidence interval)
- Переключатель диапазона: 3 года / 5 лет / 10 лет / Все
- Toggle "Предиктивный слой" вкл/выкл

### 5. База данных (PostgreSQL 16)

**5 таблиц:**

```
indicators
├── id, code, name, name_en, unit, frequency
├── source, source_url, description, methodology
├── parser_type, excel_sheet, model_config_json
├── is_active, category
└── created_at, updated_at

indicator_data
├── id, indicator_id (FK → indicators)
├── date, value
└── UNIQUE(indicator_id, date)  — "uq_indicator_date"

forecasts
├── id, indicator_id (FK → indicators)
├── model_name, model_params (JSON), aic, bic
├── is_current (bool)
└── created_at

forecast_values
├── id, forecast_id (FK → forecasts)
├── date, value, lower_bound, upper_bound
└── INDEX(forecast_id, date)

fetch_log
├── id, indicator_id (FK → indicators)
├── status (running/success/failed/no_new_data)
├── source_url, records_added, error_message
└── started_at, completed_at
```

---

## Потоки данных

### Первый запуск (автоматически)

```
docker compose up -d --build
    │
    ▼
entrypoint.sh
    ├── alembic upgrade head        → создаёт 5 таблиц
    ├── python check indicator count → 0 индикаторов
    ├── python seed_data.py         → 6 индикаторов + 419 точек ИПЦ из CSV
    │                                + OLS-прогноз для CPI
    └── exec uvicorn                → API + Scheduler запущены
```

### Ежедневное обновление (06:00 МСК)

```
Scheduler → daily_update_job()
    │
    ├── cpi:          fetch → parse sheet 01 → upsert → retrain → cache flush
    ├── cpi-food:     fetch → parse sheet 02 → upsert → retrain → cache flush
    ├── cpi-nonfood:  fetch → parse sheet 03 → upsert → retrain → cache flush
    └── cpi-services: fetch → parse sheet 04 → upsert → retrain → cache flush
```

### Запрос пользователя

```
Браузер → GET /api/v1/indicators/cpi/inflation
    │
    ▼
Nginx (frontend контейнер)
    │ location /api/ → proxy_pass http://backend:8000
    ▼
FastAPI
    │ Redis cache hit? → да → вернуть из кеша
    │                   нет ↓
    ▼
PostgreSQL
    │ SELECT indicator_data + forecast_values
    │ Вычислить rolling 12-month cumulative inflation
    │ Вычислить forecast cumulative с confidence intervals
    ▼
Redis SET (TTL 1 час) → Response JSON → Браузер
```

---

## Отказоустойчивость

| Сценарий | Поведение |
|---|---|
| Росстат недоступен | ETL логирует ошибку, данные и прогноз остаются прежними |
| Redis упал | API работает без кеша (try/except, graceful degradation) |
| Сервер перезагрузился | Docker restart: unless-stopped → всё поднимается |
| PostgreSQL volume потерян | entrypoint.sh обнаружит пустую БД → автоматический seed |
| Росстат сменил формат файла | Parser вернёт 0 точек → ошибка логируется, данные сохранены |
| OLS выдал плохой прогноз | Сохраняется как есть (нет auto-validation — риск) |

---

## Индикаторы

| Код | Название | Excel-лист | Статус |
|---|---|---|---|
| `cpi` | Индекс потребительских цен | 01 | Активен, 421 точка (1991–2026) |
| `cpi-food` | ИПЦ на продовольственные товары | 02 | Активен, 421 точка |
| `cpi-nonfood` | ИПЦ на непродовольственные товары | 03 | Активен, 421 точка |
| `cpi-services` | ИПЦ на услуги | 04 | Активен, 421 точка |
| `unemployment` | Уровень безработицы | — | Запланирован |
| `key-rate` | Ключевая ставка ЦБ РФ | — | Запланирован |

---

## Структура файлов

```
rosstat/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── indicators.py    # CRUD эндпоинты индикаторов
│   │   │   ├── forecasts.py     # Прогнозы + кумулятивная инфляция
│   │   │   ├── system.py        # Системный статус
│   │   │   └── router.py        # Сборка всех роутов
│   │   ├── core/
│   │   │   └── cache.py         # Redis get/set/invalidate с try/except
│   │   ├── services/
│   │   │   ├── fetcher.py       # HTTP-клиент к Росстату + SSL cert
│   │   │   ├── parser.py        # Excel pivot → list[DataPoint]
│   │   │   └── forecaster.py    # OLS Multi-Window модель
│   │   ├── tasks/
│   │   │   └── scheduler.py     # ETL: fetch → parse → upsert → retrain
│   │   ├── config.py            # Pydantic Settings (env vars)
│   │   ├── database.py          # AsyncEngine + session factory
│   │   ├── models.py            # SQLAlchemy ORM (5 таблиц)
│   │   ├── schemas.py           # Pydantic response schemas
│   │   └── main.py              # FastAPI app + lifespan + scheduler
│   ├── alembic/
│   │   └── versions/
│   │       └── 8524e35ba1ee_init_schema.py  # Начальная миграция
│   ├── certs/
│   │   └── russiantrustedca2024.pem         # SSL для rosstat.gov.ru
│   ├── seed_data.py             # Начальная загрузка данных
│   ├── entrypoint.sh            # Миграции → seed → uvicorn
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .dockerignore
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Navbar.jsx       # Навигация + scroll effect
│   │   │   ├── CpiChart.jsx     # График инфляции (Recharts)
│   │   │   ├── ForecastTable.jsx# Таблица прогноза с CI
│   │   │   ├── DataTable.jsx    # Таблица исторических данных
│   │   │   ├── IndicatorTile.jsx# Карточка индикатора на Dashboard
│   │   │   ├── Footer.jsx       # Подвал
│   │   │   ├── NoiseOverlay.jsx # SVG текстура
│   │   │   └── Skeleton.jsx     # Скелетоны загрузки
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx    # Главная страница
│   │   │   └── IndicatorDetail.jsx  # Страница индикатора
│   │   ├── lib/
│   │   │   ├── api.js           # Axios + базовые запросы
│   │   │   ├── hooks.js         # React Query хуки
│   │   │   └── format.js        # Форматирование дат/чисел
│   │   ├── App.jsx              # Router
│   │   ├── main.jsx             # Entry point
│   │   └── index.css            # Tailwind + custom tokens
│   ├── nginx.conf               # SPA routing + API proxy + gzip
│   ├── Dockerfile               # Multi-stage: node build → nginx
│   └── package.json
├── output/
│   └── ipc_monthly.csv          # Seed-данные (419 точек до Nov 2025)
├── docker-compose.yml           # 4 сервиса + healthchecks + volumes
├── .env.example                 # POSTGRES_PASSWORD + scheduler config
├── .gitignore
└── README.md
```

---

## Обновление кода на сервере

```bash
ssh root@5.129.204.194
cd /opt/rosstat
git pull
docker compose up -d --build
```

Docker пересобирает только изменённые слои (обычно <5 секунд если менялся только код Python).
