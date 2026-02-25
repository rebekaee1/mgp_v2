#!/bin/bash
# ─────────────────────────────────────────────────────────────
# MGP AI Travel Bot — Server Setup Script (Ubuntu 24.04)
# Использование: curl -sL <URL>/setup-server.sh | sudo bash
# Или: sudo bash setup-server.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

echo "=== MGP Server Setup ==="
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
echo "RAM: $(free -h | awk '/Mem:/ {print $2}')"
echo ""

# ─── 1. System update ────────────────────────────────────────
echo "[1/6] Обновление системы..."
apt-get update -qq && apt-get upgrade -y -qq

# ─── 2. Swap (критично для ≤2 GB RAM) ────────────────────────
SWAP_SIZE="2G"
if [ ! -f /swapfile ]; then
    echo "[2/6] Создание swap ($SWAP_SIZE)..."
    fallocate -l $SWAP_SIZE /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    echo "  Swap создан: $(swapon --show | tail -1)"
else
    echo "[2/6] Swap уже существует, пропуск"
fi

# ─── 3. Docker Engine ────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[3/6] Установка Docker..."
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "  Docker $(docker --version)"
else
    echo "[3/6] Docker уже установлен: $(docker --version)"
fi

# ─── 4. Firewall ─────────────────────────────────────────────
echo "[4/6] Настройка firewall..."
apt-get install -y -qq ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS (для будущего SSL)
ufw --force enable
echo "  UFW статус: $(ufw status | head -1)"

# ─── 5. Git + utilities ──────────────────────────────────────
echo "[5/6] Установка утилит..."
apt-get install -y -qq git htop

# ─── 6. Рабочая директория ───────────────────────────────────
echo "[6/6] Подготовка..."
mkdir -p /opt/mgp
echo ""
echo "════════════════════════════════════════════════════════"
echo "  Сервер готов!"
echo ""
echo "  Следующие шаги:"
echo "  1. cd /opt/mgp"
echo "  2. git clone <ваш-репозиторий> ."
echo "  3. cp .env.example .env"
echo "  4. nano .env  (заполнить API ключи, сменить POSTGRES_PASSWORD)"
echo "  5. docker compose up -d --build"
echo "  6. docker compose logs -f  (наблюдать за запуском)"
echo ""
echo "  Проверка: curl http://localhost/api/health"
echo "════════════════════════════════════════════════════════"
