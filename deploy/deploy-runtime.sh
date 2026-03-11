#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "== MGP runtime deploy =="
echo "Project dir: $ROOT_DIR"

if [ ! -f ".env" ]; then
  echo "ERROR: .env not found in $ROOT_DIR"
  exit 1
fi

# Runtime-only profile:
# - keeps postgres + redis + backend
# - dashboard is bundled into backend image
# - publishes backend on APP_PORT (80 by default)

docker compose stop frontend >/dev/null 2>&1 || true
docker rm -f mgp-frontend-1 >/dev/null 2>&1 || true

docker compose up -d --build

echo "--- runtime ps ---"
docker compose ps

echo "--- runtime health ---"
sleep 5
curl -fsS "http://127.0.0.1:${APP_PORT:-80}/api/health" || {
  echo
  echo "ERROR: runtime healthcheck failed"
  exit 1
}
echo
echo "Runtime deploy complete."
