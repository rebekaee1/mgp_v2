#!/bin/bash
set -e

mkdir -p /app/logs
echo "=== MGP Backend starting ==="
echo "DATABASE_URL = ${DATABASE_URL:+***configured***}"
echo "REDIS_URL    = ${REDIS_URL:+***configured***}"

# 1. JWT_SECRET fail-safe: generate if missing or default
if [ -z "$JWT_SECRET" ] || [ "$JWT_SECRET" = "change-me-in-production-please" ]; then
    export JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
    echo "WARNING: JWT_SECRET auto-generated (not persisted across container restarts)"
fi

# 2. Alembic migrations (graceful — если БД недоступна, стартуем без)
if [ -n "$DATABASE_URL" ]; then
    echo "Running alembic upgrade..."
    python -m alembic upgrade head 2>&1 || echo "WARNING: Alembic migration failed — starting without DB"
fi

# 3. Auto-seed: create company + admin + assistant if companies table is empty
NEED_SEED=$(python -c "
from database import init_db
from config import settings
init_db(settings.database_url)
from models import Company
from database import get_db
with get_db() as db:
    if db and db.query(Company).count() == 0:
        print('yes')
    else:
        print('no')
" 2>/dev/null || echo "skip")

if [ "$NEED_SEED" = "yes" ]; then
    echo "Empty database detected — running seed..."
    python seed_data.py
fi

# 4. Start gunicorn
echo "Starting gunicorn..."
exec gunicorn app:app \
    --bind 0.0.0.0:8080 \
    --workers "${GUNICORN_WORKERS:-1}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${LOG_LEVEL:-info}"
