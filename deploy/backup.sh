#!/bin/bash
# Daily PostgreSQL backup with 7-day rotation
# Usage: crontab -e → 0 3 * * * /opt/mgp/deploy/backup.sh >> /var/log/mgp-backup.log 2>&1

set -e

BACKUP_DIR="${BACKUP_DIR:-/opt/mgp/backups}"
CONTAINER="${PG_CONTAINER:-$(docker ps --filter name=postgres -q | head -1)}"
DB_USER="${POSTGRES_USER:-mgp}"
DB_NAME="${POSTGRES_DB:-mgp}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

mkdir -p "$BACKUP_DIR"

DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="mgp_${DATE}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

echo "[$(date)] Starting backup..."

docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$FILEPATH"

SIZE=$(du -h "$FILEPATH" | cut -f1)
echo "[$(date)] Backup complete: ${FILENAME} (${SIZE})"

DELETED=$(find "$BACKUP_DIR" -name "mgp_*.sql.gz" -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] Rotated ${DELETED} old backups (>${RETENTION_DAYS} days)"
fi
