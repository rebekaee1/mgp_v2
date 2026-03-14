#!/bin/bash
set -euo pipefail

APP_DIR="/opt/mgp"
LOG_FILE="/var/log/mgp-autodeploy.log"
LOCK_FILE="/tmp/mgp-autodeploy.lock"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd "$APP_DIR"

git fetch origin main --quiet 2>>"$LOG_FILE"

LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse origin/main)

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    exit 0
fi

log "New commits detected: $LOCAL_HEAD -> $REMOTE_HEAD"
log "Pulling changes..."

git pull origin main --ff-only 2>>"$LOG_FILE" || {
    log "ERROR: git pull failed, attempting reset"
    git reset --hard origin/main 2>>"$LOG_FILE"
}

log "Rebuilding containers..."
docker compose up -d --build 2>>"$LOG_FILE"

log "Waiting for health check..."
sleep 10

HEALTH=$(curl -sf http://127.0.0.1:${APP_PORT:-80}/api/health 2>/dev/null || echo "FAILED")
log "Health check: $HEALTH"

if echo "$HEALTH" | grep -q "FAILED"; then
    log "WARNING: Health check failed after deploy!"
else
    log "Deploy successful. New HEAD: $(git rev-parse --short HEAD)"
fi

log "--- deploy cycle complete ---"
