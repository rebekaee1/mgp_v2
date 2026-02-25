#!/bin/sh
# Cloud-init скрипт для Timeweb Cloud
# Вставить в поле "Cloud-init" при создании сервера
# Автоматически настраивает: swap, Docker, firewall, git
set -eu
exec > /var/log/mgp-init.log 2>&1

echo "=== MGP Cloud-Init Start: $(date) ==="

apt-get update -qq && apt-get upgrade -y -qq

# Swap 2GB
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

# Docker
apt-get install -y -qq ca-certificates curl gnupg git htop
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker && systemctl start docker

# Firewall
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable

mkdir -p /opt/mgp
echo "=== MGP Cloud-Init Done: $(date) ==="
echo "Лог: /var/log/mgp-init.log"
