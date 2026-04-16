#!/bin/bash
set -euo pipefail

# ============================================================================
# Provisioning script for new MGP clients
# Run on the production server from the project root directory.
#
# Prerequisites:
#   - Docker containers running (docker compose up -d)
#   - Latest code pulled (git pull origin main)
#   - Containers rebuilt (docker compose up -d --build)
#
# Usage:
#   ./deploy/provision_clients.sh [shelkovo|krasnogorsk|all]
#
# What it does for each company:
#   1. Runs Alembic migration (adds uon_api_key/uon_source columns if missing)
#   2. Creates Company + User + Assistant via CLI
#   3. Updates widget_config JSON with full personalization
#   4. Sets U-ON CRM API key (Krasnogorsk) or prints instructions (Shelkovo)
#   5. Loads custom FAQ from clients/<slug>/faq.md
# ============================================================================

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

log() { echo "[$(date +%H:%M:%S)] $*"; }
err() { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

docker compose ps --format '{{.Name}}' 2>/dev/null | grep -q backend || err "Backend container not running. Run: docker compose up -d"
docker compose ps --format '{{.Name}}' 2>/dev/null | grep -q postgres || err "Postgres container not running. Run: docker compose up -d"

run_cli() {
    docker compose exec -T backend python cli.py "$@"
}

run_sql() {
    docker compose exec -T postgres psql -U mgp -d mgp -tAc "$1"
}

get_assistant_id() {
    local slug="$1"
    run_sql "SELECT a.id FROM assistants a JOIN companies c ON a.company_id = c.id WHERE c.slug = '${slug}' AND a.is_active = true LIMIT 1;"
}

load_faq() {
    local assistant_id="$1"
    local faq_file="$2"
    if [ ! -f "$faq_file" ]; then
        log "⚠️  FAQ file not found: $faq_file — skipping"
        return
    fi
    docker compose exec -T postgres psql -U mgp -d mgp <<EOSQL
UPDATE assistants
SET faq_content = \$faq_body\$$(cat "$faq_file")\$faq_body\$
WHERE id = '${assistant_id}';
EOSQL
    log "FAQ loaded from $faq_file"
}

update_widget_config() {
    local assistant_id="$1"
    local json_patch="$2"
    run_sql "UPDATE assistants SET widget_config = COALESCE(widget_config, '{}'::jsonb) || '${json_patch}'::jsonb WHERE id = '${assistant_id}';"
}

# ── Shelkovo ──────────────────────────────────────────────────────────────────

provision_shelkovo() {
    log "════════════════════════════════════════════════"
    log "  Provisioning: МГП Щёлково"
    log "════════════════════════════════════════════════"

    local EXISTING_AID
    EXISTING_AID=$(get_assistant_id "mgp-shelkovo" 2>/dev/null || true)

    if [ -n "$EXISTING_AID" ]; then
        log "Company mgp-shelkovo already exists (assistant: $EXISTING_AID) — updating config"
    else
        local PASSWORD
        PASSWORD=$(openssl rand -base64 12)

        log "Creating company + user + assistant..."
        run_cli create-user \
            --email "otdih@c-mgp.ru" \
            --password "${PASSWORD}" \
            --company "МГП Щёлково" \
            --slug "mgp-shelkovo" \
            --name "Лариса" \
            --assistant-name "МГП Щёлково AI Assistant" \
            --widget-title "МГП г.Щёлково" \
            --widget-subtitle "Турагентство" \
            --widget-primary-color "#E30613" \
            --role admin

        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "📋 CREDENTIALS (save now!):"
        log "   Email:    otdih@c-mgp.ru"
        log "   Password: ${PASSWORD}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    local ASSISTANT_ID
    ASSISTANT_ID=$(get_assistant_id "mgp-shelkovo")
    [ -n "$ASSISTANT_ID" ] || err "Failed to find assistant for mgp-shelkovo"
    log "Assistant ID: ${ASSISTANT_ID}"

    log "Setting widget_config personalization..."
    update_widget_config "$ASSISTANT_ID" '{
        "title": "МГП г.Щёлково",
        "subtitle": "Турагентство",
        "primary_color": "#E30613",
        "welcome_message": "👋 Здравствуйте! Я — ИИ-ассистент турагентства МГП г.Щёлково.\n\nЯ помогу вам:\n• 🔍 Подобрать тур по вашим параметрам\n• 🔥 Найти горящие предложения\n• ❓ Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
        "company_name": "МГП г.Щёлково",
        "website": "https://c-mgp.ru/",
        "booking_base_url": "https://c-mgp.ru/",
        "contact_phone": "8 926 221-39-01",
        "office_address": "г. Щёлково, пл. Ленина, д.5, ком.107. Режим работы: Пн-Пт 10:00-19:00, Сб 11:00-17:00, Вс — удалённо",
        "contact_email": "otdih@c-mgp.ru",
        "notification_email": "otdih@c-mgp.ru",
        "booking_email_enabled": true
    }'

    log "Setting allowed_domains..."
    run_sql "UPDATE assistants SET allowed_domains = 'c-mgp.ru' WHERE id = '${ASSISTANT_ID}';"

    log "Loading custom FAQ..."
    load_faq "$ASSISTANT_ID" "$ROOT_DIR/clients/shelkovo/faq.md"

    log ""
    log "⚠️  U-ON API KEY: not set yet"
    log "   1. Log into mgpshelkovo.u-on.ru"
    log "   2. Go to Settings > Integrations > API"
    log "   3. Create a new API key for the AI assistant"
    log "   4. Add the server IP to the U-ON whitelist"
    log "   5. Then run:"
    log "   docker compose exec postgres psql -U mgp -d mgp -c \\"
    log "     \"UPDATE assistants SET uon_api_key='YOUR_KEY' WHERE id='${ASSISTANT_ID}';\""
    log ""
    log "✅ МГП Щёлково — provisioned (assistant: ${ASSISTANT_ID})"
    echo ""
}

# ── Krasnogorsk ───────────────────────────────────────────────────────────────

provision_krasnogorsk() {
    log "════════════════════════════════════════════════"
    log "  Provisioning: МГП Красногорск"
    log "════════════════════════════════════════════════"

    local EXISTING_AID
    EXISTING_AID=$(get_assistant_id "mgp-krasnogorsk" 2>/dev/null || true)

    if [ -n "$EXISTING_AID" ]; then
        log "Company mgp-krasnogorsk already exists (assistant: $EXISTING_AID) — updating config"
    else
        local PASSWORD
        PASSWORD=$(openssl rand -base64 12)

        log "Creating company + user + assistant..."
        run_cli create-user \
            --email "krasnogorsk@mgput.ru" \
            --password "${PASSWORD}" \
            --company "МГП Красногорск" \
            --slug "mgp-krasnogorsk" \
            --name "Наталия" \
            --assistant-name "Горящие туры Красногорск AI Assistant" \
            --widget-title "Горящие туры" \
            --widget-subtitle "Турагентство" \
            --widget-primary-color "#C1127B" \
            --uon-api-key "ghh8Fw63d4lY9J5ZNy6M" \
            --uon-source "AI-Ассистент" \
            --role admin

        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "📋 CREDENTIALS (save now!):"
        log "   Email:    krasnogorsk@mgput.ru"
        log "   Password: ${PASSWORD}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    local ASSISTANT_ID
    ASSISTANT_ID=$(get_assistant_id "mgp-krasnogorsk")
    [ -n "$ASSISTANT_ID" ] || err "Failed to find assistant for mgp-krasnogorsk"
    log "Assistant ID: ${ASSISTANT_ID}"

    log "Setting widget_config personalization..."
    update_widget_config "$ASSISTANT_ID" '{
        "title": "Горящие туры",
        "subtitle": "Турагентство",
        "primary_color": "#C1127B",
        "welcome_message": "Здравствуйте, меня зовут Наталия, спасибо за обращение! Я могу помочь Вам подобрать тур.\n\n🔍 Подобрать тур по вашим параметрам\n🔥 Найти горящие предложения\n❓ Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
        "company_name": "Горящие туры (МГП Красногорск)",
        "website": "https://www.mgput.ru",
        "booking_base_url": "https://www.mgput.ru",
        "contact_phone": "+7 925 788-72-97",
        "office_address": "г. Красногорск, Красногорский бульвар, д. 3а. Режим работы: ежедневно 10:00-17:00",
        "notification_email": "krasnogorsk@mgput.ru",
        "booking_email_enabled": true
    }'

    log "Setting allowed_domains..."
    run_sql "UPDATE assistants SET allowed_domains = 'mgput.ru,www.mgput.ru' WHERE id = '${ASSISTANT_ID}';"

    log "Ensuring U-ON CRM credentials..."
    run_sql "UPDATE assistants SET uon_api_key = 'ghh8Fw63d4lY9J5ZNy6M', uon_source = 'AI-Ассистент' WHERE id = '${ASSISTANT_ID}';"

    log "Loading custom FAQ..."
    load_faq "$ASSISTANT_ID" "$ROOT_DIR/clients/krasnogorsk/faq.md"

    log ""
    log "✅ МГП Красногорск — provisioned (assistant: ${ASSISTANT_ID})"
    log "   U-ON API key: ghh8Fw63d4lY9J5ZNy6M (set)"
    log "   ⚠️  Verify U-ON IP whitelist includes this server's IP"
    echo ""
}

# ── Alembic migration ─────────────────────────────────────────────────────────

run_migration() {
    log "Running Alembic migrations..."
    docker compose exec -T backend alembic upgrade head 2>&1 || log "⚠️  Migration may already be applied (check manually if errors)"
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo ""
log "MGP Client Provisioning"
log "========================"
echo ""

case "${1:-all}" in
    shelkovo)
        run_migration
        provision_shelkovo
        ;;
    krasnogorsk)
        run_migration
        provision_krasnogorsk
        ;;
    all)
        run_migration
        provision_shelkovo
        provision_krasnogorsk
        echo ""
        log "════════════════════════════════════════════════"
        log "  ALL CLIENTS PROVISIONED"
        log "════════════════════════════════════════════════"
        log ""
        log "REMAINING MANUAL STEPS:"
        log ""
        log "1. [Щёлково] Create U-ON API key:"
        log "   - Log into mgpshelkovo.u-on.ru (otdih@c-mgp.ru)"
        log "   - Settings > Integrations > API > Create key"
        log "   - Add server IP to U-ON whitelist"
        log "   - Set key via SQL (see command above)"
        log ""
        log "2. [Красногорск] Verify U-ON IP whitelist:"
        log "   - Ensure server IP is allowed for key ghh8Fw63d4lY9J5ZNy6M"
        log ""
        log "3. LK setup (lk.navilet.ru) — for each company:"
        log "   - Create widget linked to assistant_id"
        log "   - Enable pre-chat start form (name + phone)"
        log "   - Set allowed_domains"
        log ""
        log "4. Embed code — install on client websites:"
        log "   - c-mgp.ru (Щёлково)"
        log "   - mgput.ru (Красногорск)"
        log ""
        log "5. Test full flow for each company:"
        log "   - Widget opens with correct branding"
        log "   - Start form collects name + phone"
        log "   - Tour search works, booking links go to correct site"
        log "   - CRM lead created in correct U-ON instance"
        ;;
    *)
        echo "Usage: $0 [shelkovo|krasnogorsk|all]"
        echo ""
        echo "Options:"
        echo "  shelkovo     — provision МГП Щёлково only"
        echo "  krasnogorsk  — provision МГП Красногорск only"
        echo "  all          — provision both (default)"
        exit 1
        ;;
esac
