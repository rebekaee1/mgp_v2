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
#   ./deploy/provision_clients.sh [shelkovo|krasnogorsk|vyhino|belgorod|all]
#
# What it does for each company:
#   1. Runs Alembic migration (adds uon_api_key/uon_source columns if missing)
#   2. Creates Company + User + Assistant via CLI
#   3. Updates widget_config JSON with full personalization
#   4. Sets U-ON CRM API key (Krasnogorsk, Vyhino, Belgorod) or prints instructions (Shelkovo)
#   5. Loads custom FAQ from clients/<slug>/faq.md (Shelkovo, Krasnogorsk only;
#      Vyhino, Belgorod use the common faq.md without override, like Kirishi/Tambov)
#   6. Configures runtime_metadata.reporting (PUSH webhook MGP → LK control-plane).
#      Per-tenant shared secret can be supplied via env vars
#      MGP_REPORTING_SECRET_<UPPER_SLUG_WITH_UNDERSCORES> (e.g.
#      MGP_REPORTING_SECRET_MGP_VYHINO=…). If absent, an existing secret in DB is
#      kept; otherwise a new one is generated locally and printed for manual
#      mirroring on the LK side (lk_navylet).
# ============================================================================

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

# ── Reporting / control-plane defaults (override via env if needed) ──────────
REPORTING_ENDPOINT_URL="${MGP_REPORTING_ENDPOINT:-https://lk.navilet.ru/api/control-plane/runtime/events}"
REPORTING_CONTRACT_VERSION="${MGP_REPORTING_CONTRACT:-2026-03-09}"
REPORTING_AUTH_HEADER="${MGP_REPORTING_AUTH_HEADER:-X-MGP-Service-Token}"

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

# ── Reporting (control-plane PUSH MGP → LK) ──────────────────────────────────
#
# Idempotent. Resolution order for the shared_secret:
#   1) Env var MGP_REPORTING_SECRET_<UPPER_SLUG> (slug with `-` → `_`)
#   2) Existing secret already stored in runtime_metadata.reporting.auth.secret
#   3) Locally generated 43-char URL-safe random string (printed for the admin
#      to mirror on the LK side; without that mirror PUSH will be rejected 401).
#
# Even if the secret stays the same, we still rewrite the full reporting block
# so that endpoint_url / contract_version / event types are guaranteed correct.
setup_reporting() {
    local assistant_id="$1"
    local slug="$2"
    local upper_slug
    upper_slug=$(echo "$slug" | tr '[:lower:]-' '[:upper:]_')
    local var_name="MGP_REPORTING_SECRET_${upper_slug}"
    local env_secret="${!var_name:-}"

    local current_secret
    current_secret=$(run_sql "SELECT COALESCE(runtime_metadata::jsonb->'reporting'->'auth'->>'secret','') FROM assistants WHERE id='${assistant_id}';" || true)
    current_secret=$(printf '%s' "$current_secret" | tr -d '\r\n')

    local secret=""
    local source_marker=""

    if [ -n "$env_secret" ]; then
        secret="$env_secret"
        source_marker="from-env(${var_name})"
        if [ -n "$current_secret" ] && [ "$current_secret" != "$env_secret" ]; then
            log "⚠️  Reporting secret in DB differs from ${var_name} — overwriting with env value."
        fi
    elif [ -n "$current_secret" ]; then
        secret="$current_secret"
        source_marker="kept-existing"
    else
        secret=$(openssl rand -base64 32 | tr -d '=+/' | cut -c1-43)
        source_marker="generated-locally"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "⚠️  Reporting secret for ${slug} was missing — generated a new one."
        log "   Mirror it on the LK side (lk_navylet) NOW or PUSH will 401."
        log "   ${var_name}=${secret}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    if [[ ! "$secret" =~ ^[A-Za-z0-9_-]+$ ]]; then
        err "Reporting secret for ${slug} contains unsupported characters; refuse to embed it in SQL"
    fi

    docker compose exec -T postgres psql -U mgp -d mgp -v ON_ERROR_STOP=1 <<EOSQL
UPDATE assistants
SET runtime_metadata = jsonb_set(
    COALESCE(runtime_metadata::jsonb, '{}'::jsonb),
    '{reporting}',
    jsonb_build_object(
        'mode', 'batch_snapshot',
        'contract_version', '${REPORTING_CONTRACT_VERSION}',
        'endpoint_url', '${REPORTING_ENDPOINT_URL}',
        'accepted_event_types', jsonb_build_array('conversation_snapshot'),
        'auth', jsonb_build_object(
            'type', 'shared_secret',
            'header_name', '${REPORTING_AUTH_HEADER}',
            'secret', '${secret}'
        )
    ),
    true
)
WHERE id = '${assistant_id}';
EOSQL
    log "Reporting configured for ${slug} (source: ${source_marker}, endpoint: ${REPORTING_ENDPOINT_URL})"
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

    log "Configuring runtime_metadata.reporting (PUSH → LK)..."
    setup_reporting "$ASSISTANT_ID" "mgp-shelkovo"

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

    log "Configuring runtime_metadata.reporting (PUSH → LK)..."
    setup_reporting "$ASSISTANT_ID" "mgp-krasnogorsk"

    log ""
    log "✅ МГП Красногорск — provisioned (assistant: ${ASSISTANT_ID})"
    log "   U-ON API key: ghh8Fw63d4lY9J5ZNy6M (set)"
    log "   ⚠️  Verify U-ON IP whitelist includes this server's IP"
    echo ""
}

# ── Vyhino ────────────────────────────────────────────────────────────────────

provision_vyhino() {
    log "════════════════════════════════════════════════"
    log "  Provisioning: МГП Выхино"
    log "════════════════════════════════════════════════"

    local EXISTING_AID
    EXISTING_AID=$(get_assistant_id "mgp-vyhino" 2>/dev/null || true)

    if [ -n "$EXISTING_AID" ]; then
        log "Company mgp-vyhino already exists (assistant: $EXISTING_AID) — updating config"
    else
        local PASSWORD
        PASSWORD=$(openssl rand -base64 12)

        log "Creating company + user + assistant..."
        run_cli create-user \
            --email "Mgp-vyhino@mail.ru" \
            --password "${PASSWORD}" \
            --company "МГП Выхино" \
            --slug "mgp-vyhino" \
            --assistant-name "МГП Выхино AI Assistant" \
            --widget-title "Горящие туры" \
            --widget-subtitle "Турагентство" \
            --widget-primary-color "#E30613" \
            --uon-api-key "Hy7CFjPZ28akdnr5V09M1777458672" \
            --uon-source "AI-Ассистент" \
            --role admin

        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "📋 CREDENTIALS (save now!):"
        log "   Email:    Mgp-vyhino@mail.ru"
        log "   Password: ${PASSWORD}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    local ASSISTANT_ID
    ASSISTANT_ID=$(get_assistant_id "mgp-vyhino")
    [ -n "$ASSISTANT_ID" ] || err "Failed to find assistant for mgp-vyhino"
    log "Assistant ID: ${ASSISTANT_ID}"

    log "Setting widget_config personalization..."
    update_widget_config "$ASSISTANT_ID" '{
        "title": "Горящие туры",
        "subtitle": "Турагентство",
        "primary_color": "#E30613",
        "welcome_message": "👋 Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\nЯ помогу вам:\n• 🔍 Подобрать тур по вашим параметрам\n• 🔥 Найти горящие предложения\n• ❓ Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
        "company_name": "Горящие туры (МГП Выхино)",
        "website": "https://mgp-volna.ru",
        "booking_base_url": "https://mgp-volna.ru",
        "contact_phone": "+7 916 168-47-10",
        "office_address": "г. Москва, ул. Вешняковская, д. 20Б. Режим работы: Пн-Пт 10:00-20:00, Сб 10:00-18:00, Вс выходной"
    }'

    log "Setting allowed_domains..."
    run_sql "UPDATE assistants SET allowed_domains = 'mgp-volna.ru,www.mgp-volna.ru' WHERE id = '${ASSISTANT_ID}';"

    log "Ensuring U-ON CRM credentials (per-tenant Vyhino key)..."
    run_sql "UPDATE assistants SET uon_api_key = 'Hy7CFjPZ28akdnr5V09M1777458672', uon_source = 'AI-Ассистент' WHERE id = '${ASSISTANT_ID}';"

    log "Note: Vyhino uses common faq.md (no per-tenant FAQ override) — like Кириши/Тамбов"

    log "Configuring runtime_metadata.reporting (PUSH → LK)..."
    setup_reporting "$ASSISTANT_ID" "mgp-vyhino"

    log ""
    log "✅ МГП Выхино — provisioned (assistant: ${ASSISTANT_ID})"
    log "   U-ON API key: Hy7CFjPZ28akdnr5V09M1777458672 (set, per-tenant)"
    log "   ⚠️  Verify U-ON whitelist for this server's IP (POST + GET) for the Vyhino key"
    echo ""
}

# ── Belgorod ──────────────────────────────────────────────────────────────────

provision_belgorod() {
    log "════════════════════════════════════════════════"
    log "  Provisioning: МГП Белгород"
    log "════════════════════════════════════════════════"

    local EXISTING_AID
    EXISTING_AID=$(get_assistant_id "mgp-belgorod" 2>/dev/null || true)

    if [ -n "$EXISTING_AID" ]; then
        log "Company mgp-belgorod already exists (assistant: $EXISTING_AID) — updating config"
    else
        local PASSWORD
        PASSWORD=$(openssl rand -base64 12)

        log "Creating company + user + assistant..."
        run_cli create-user \
            --email "Belg@mgp.ru" \
            --password "${PASSWORD}" \
            --company "МГП Белгород" \
            --slug "mgp-belgorod" \
            --assistant-name "МГП Белгород AI Assistant" \
            --widget-title "Горящие туры" \
            --widget-subtitle "Турагентство" \
            --widget-primary-color "#E30613" \
            --uon-api-key "DkRQ339sbeWQdU92P8tv1777547148" \
            --uon-source "AI-Ассистент" \
            --role admin

        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "📋 CREDENTIALS (save now!):"
        log "   Email:    Belg@mgp.ru"
        log "   Password: ${PASSWORD}"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    local ASSISTANT_ID
    ASSISTANT_ID=$(get_assistant_id "mgp-belgorod")
    [ -n "$ASSISTANT_ID" ] || err "Failed to find assistant for mgp-belgorod"
    log "Assistant ID: ${ASSISTANT_ID}"

    log "Setting widget_config personalization..."
    update_widget_config "$ASSISTANT_ID" '{
        "title": "Горящие туры",
        "subtitle": "Турагентство",
        "primary_color": "#E30613",
        "welcome_message": "👋 Здравствуйте! Я — ИИ-ассистент туристического агентства.\n\nЯ помогу вам:\n• 🔍 Подобрать тур по вашим параметрам\n• 🔥 Найти горящие предложения\n• ❓ Ответить на вопросы о визах, оплате, документах\n\nКуда бы вы хотели поехать?",
        "company_name": "Горящие туры (МГП Белгород)",
        "website": "https://mgp-belgorod.ru",
        "booking_base_url": "https://mgp-belgorod.ru",
        "contact_phone": "+7 910 741-57-00",
        "office_address": "г. Белгород, ул. Щорса, д. 64, ТЦ \"Ситимолл\". Режим работы: ежедневно 10:00-22:00"
    }'

    log "Setting allowed_domains..."
    run_sql "UPDATE assistants SET allowed_domains = 'mgp-belgorod.ru,www.mgp-belgorod.ru' WHERE id = '${ASSISTANT_ID}';"

    log "Ensuring U-ON CRM credentials (per-tenant Belgorod key)..."
    run_sql "UPDATE assistants SET uon_api_key = 'DkRQ339sbeWQdU92P8tv1777547148', uon_source = 'AI-Ассистент' WHERE id = '${ASSISTANT_ID}';"

    log "Note: Belgorod uses common faq.md (no per-tenant FAQ override) — like Vyhino/Kirishi/Tambov"

    log "Configuring runtime_metadata.reporting (PUSH → LK)..."
    setup_reporting "$ASSISTANT_ID" "mgp-belgorod"

    log ""
    log "✅ МГП Белгород — provisioned (assistant: ${ASSISTANT_ID})"
    log "   U-ON API key: DkRQ339sbeWQdU92P8tv1777547148 (set, per-tenant)"
    log "   ⚠️  Verify U-ON whitelist for this server's IP (POST + GET) for the Belgorod key"
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
    vyhino)
        run_migration
        provision_vyhino
        ;;
    belgorod)
        run_migration
        provision_belgorod
        ;;
    all)
        run_migration
        provision_shelkovo
        provision_krasnogorsk
        provision_vyhino
        provision_belgorod
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
        log "3. [Выхино] Verify U-ON IP whitelist + activate POST/GET:"
        log "   - Log into Vyhino's U-ON, Settings > Integrations > API"
        log "   - Activate POST and GET methods for key Hy7CFjPZ28akdnr5V09M1777458672"
        log "   - Add server IP to U-ON whitelist"
        log ""
        log "4. [Белгород] Verify U-ON IP whitelist + activate POST/GET:"
        log "   - Log into Belgorod's U-ON, Settings > Integrations > API"
        log "   - Activate POST and GET methods for key DkRQ339sbeWQdU92P8tv1777547148"
        log "   - Add server IPs to U-ON whitelist (72.56.88.193 + 5.129.202.189)"
        log ""
        log "5. LK setup (lk.navilet.ru) — for each company:"
        log "   - Create widget linked to assistant_id (same UUID as in MGP DB)"
        log "   - Enable pre-chat start form (name + phone) where requested"
        log "   - Set allowed_domains"
        log "   - Mirror reporting secret (auth.shared_secret) on the LK side."
        log "     If the script logged 'generated-locally' for a tenant, copy that"
        log "     MGP_REPORTING_SECRET_<UPPER_SLUG>=… into LK runtime_metadata.reporting."
        log "     If the LK side already has a secret you want to keep, re-run this"
        log "     script with MGP_REPORTING_SECRET_<UPPER_SLUG>=<value> exported."
        log ""
        log "6. Embed code — install on client websites:"
        log "   - c-mgp.ru (Щёлково)"
        log "   - mgput.ru (Красногорск)"
        log "   - mgp-volna.ru (Выхино)"
        log "   - mgp-belgorod.ru (Белгород)"
        log ""
        log "7. Test full flow for each company:"
        log "   - Widget opens with correct branding"
        log "   - Start form collects name + phone"
        log "   - Tour search works, booking links go to correct site"
        log "   - CRM lead created in correct U-ON instance"
        ;;
    *)
        echo "Usage: $0 [shelkovo|krasnogorsk|vyhino|belgorod|all]"
        echo ""
        echo "Options:"
        echo "  shelkovo     — provision МГП Щёлково only"
        echo "  krasnogorsk  — provision МГП Красногорск only"
        echo "  vyhino       — provision МГП Выхино only"
        echo "  belgorod     — provision МГП Белгород only"
        echo "  all          — provision all four (default)"
        exit 1
        ;;
esac
