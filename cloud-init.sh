#!/bin/sh
set -eu

# ===================================================================
# Cloud-init для Timeweb Cloud — ЛК AIMpact
# Ubuntu 24.04, 2GB RAM, 30GB NVMe, Москва MSK-1
#
# ВАЖНО: Все секреты передаются через переменные окружения Timeweb
# или вручную в .env после клонирования. НЕ ХРАНИТЬ СЕКРЕТЫ ЗДЕСЬ.
# ===================================================================

export DEBIAN_FRONTEND=noninteractive
LOG="/var/log/cloud-init-custom.log"
exec > "$LOG" 2>&1
echo "=== Cloud-init started at $(date -u) ==="

# -------------------------------------------------------------------
# 1. SWAP (подстраховка при Docker build)
# -------------------------------------------------------------------
if [ ! -f /swapfile ]; then
    echo ">>> Creating 2GB swap..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    echo ">>> Swap created"
fi

# -------------------------------------------------------------------
# 2. System update + essentials
# -------------------------------------------------------------------
echo ">>> Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    ca-certificates curl gnupg lsb-release \
    git ufw fail2ban htop ncdu \
    logrotate unattended-upgrades

# -------------------------------------------------------------------
# 3. Docker Engine + Docker Compose (official repo)
# -------------------------------------------------------------------
echo ">>> Installing Docker..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable docker
systemctl start docker
echo ">>> Docker installed"

# -------------------------------------------------------------------
# 4. Firewall (UFW)
# -------------------------------------------------------------------
echo ">>> Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# -------------------------------------------------------------------
# 5. Fail2ban (SSH brute force protection)
# -------------------------------------------------------------------
echo ">>> Configuring fail2ban..."
cat > /etc/fail2ban/jail.local <<'JAILEOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
findtime = 600
JAILEOF
systemctl enable fail2ban
systemctl restart fail2ban

# -------------------------------------------------------------------
# 6. Docker logging defaults
# -------------------------------------------------------------------
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'DAEMONEOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
DAEMONEOF
systemctl restart docker

# -------------------------------------------------------------------
# 7. Kernel tuning
# -------------------------------------------------------------------
cat >> /etc/sysctl.conf <<'SYSEOF'
net.core.somaxconn = 512
net.ipv4.tcp_max_syn_backlog = 512
vm.overcommit_memory = 1
SYSEOF
sysctl -p

# -------------------------------------------------------------------
# 8. Clone repository
# -------------------------------------------------------------------
APP_DIR="/opt/lk-aimpact"
echo ">>> Cloning repository..."
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull origin main || true
else
    rm -rf "$APP_DIR"
    git clone https://github.com/rebekaee1/lk_navylet.git "$APP_DIR" || {
        echo ">>> Clone failed (private repo). Clone manually:"
        echo "    git clone https://<TOKEN>@github.com/rebekaee1/lk_navylet.git $APP_DIR"
        mkdir -p "$APP_DIR"
    }
fi
mkdir -p "$APP_DIR/logs"

# -------------------------------------------------------------------
# 9. Create .env — ЗАПОЛНИ ВРУЧНУЮ!
# -------------------------------------------------------------------
GENERATED_PG_PASS=$(openssl rand -hex 16)
GENERATED_JWT=$(openssl rand -hex 32)

if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" <<ENVEOF
# === LLM Provider ===
LLM_PROVIDER=openai
OPENAI_API_KEY=REPLACE_ME
OPENAI_MODEL=openai/gpt-5-mini
OPENAI_BASE_URL=https://openrouter.ai/api/v1

# === TourVisor API ===
TOURVISOR_AUTH_LOGIN=REPLACE_ME
TOURVISOR_AUTH_PASS=REPLACE_ME
TOURVISOR_BASE_URL=https://tourvisor.ru/xml

# === PostgreSQL ===
POSTGRES_DB=mgp
POSTGRES_USER=mgp
POSTGRES_PASSWORD=${GENERATED_PG_PASS}

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === Server ===
LOG_LEVEL=INFO
LOG_FORMAT=text
SESSION_TTL_SECONDS=1800

# === Dashboard Auth ===
JWT_SECRET=${GENERATED_JWT}

# === Auto-Seed ===
SEED_ADMIN_EMAIL=REPLACE_ME
SEED_ADMIN_PASSWORD=REPLACE_ME
SEED_COMPANY_NAME=REPLACE_ME
SEED_COMPANY_SLUG=REPLACE_ME

# === MGP Bot Sync ===
SYNC_MGP_ENABLED=true
SYNC_MGP_INTERVAL_MINUTES=5
MGP_SSH_HOST=REPLACE_ME
MGP_SSH_PORT=22
MGP_SSH_USER=root
MGP_SSH_PASSWORD=REPLACE_ME
MGP_PG_USER=mgp
MGP_PG_PASSWORD=REPLACE_ME
MGP_PG_DB=mgp
MGP_PG_PORT=5432

# === CORS ===
CORS_ORIGINS=REPLACE_ME

# === Resource Tuning (2GB RAM) ===
PG_SHARED_BUFFERS=64MB
PG_EFFECTIVE_CACHE=256MB
PG_MAX_CONN=20
REDIS_MAXMEMORY=64mb
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
APP_PORT=80
ENVEOF
    chmod 600 "$APP_DIR/.env"
    echo ">>> .env created — FILL IN SECRETS MANUALLY: nano $APP_DIR/.env"
else
    echo ">>> .env already exists, skipping"
fi

# -------------------------------------------------------------------
# 10. Log rotation
# -------------------------------------------------------------------
cat > /etc/logrotate.d/lk-aimpact <<'LREOF'
/opt/lk-aimpact/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LREOF

# -------------------------------------------------------------------
# 11. Auto security updates
# -------------------------------------------------------------------
dpkg-reconfigure -plow unattended-upgrades

# -------------------------------------------------------------------
# 12. Weekly Docker prune
# -------------------------------------------------------------------
echo "0 3 * * 0 root docker system prune -f >> /var/log/docker-prune.log 2>&1" \
    > /etc/cron.d/docker-prune

# -------------------------------------------------------------------
# 13. Build and start (only if .env is filled)
# -------------------------------------------------------------------
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    if grep -q "REPLACE_ME" "$APP_DIR/.env" 2>/dev/null; then
        echo ">>> .env contains REPLACE_ME placeholders!"
        echo ">>> Fill in secrets first: nano $APP_DIR/.env"
        echo ">>> Then run: cd $APP_DIR && docker compose up -d --build"
    else
        echo ">>> Building and starting..."
        cd "$APP_DIR"
        docker compose up -d --build 2>&1 | tail -50
        echo ">>> Waiting 30s for startup..."
        sleep 30
        docker compose ps
        curl -sf http://localhost/api/health || echo ">>> Health check pending..."
    fi
fi

echo "=== Cloud-init finished at $(date -u) ==="
