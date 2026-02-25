#!/bin/bash
set -e

echo "=== MGP Backend starting ==="
echo "DATABASE_URL = ${DATABASE_URL:+***configured***}"
echo "REDIS_URL    = ${REDIS_URL:+***configured***}"

# Alembic миграции (graceful — если БД недоступна, стартуем без)
if [ -n "$DATABASE_URL" ]; then
    echo "Running alembic upgrade..."
    python -m alembic upgrade head 2>&1 || echo "WARNING: Alembic migration failed — starting without DB"
fi

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
