#!/bin/bash
set -e

echo "================================================"
echo "  Multi-Agent Trading Bot — Production Deploy"
echo "================================================"
echo ""

REPO_URL="https://github.com/Polymerthcedric/multi-agent-trading.git"
INSTALL_DIR="/opt/multi-agent-trading"

# --- System Check ---
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run as root (sudo bash deploy/install.sh)"
    exit 1
fi

echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose git curl ufw fail2ban > /dev/null 2>&1
systemctl enable docker
systemctl start docker

echo "[2/8] Configuring firewall..."
ufw --force reset > /dev/null 2>&1
ufw default deny incoming > /dev/null 2>&1
ufw default allow outgoing > /dev/null 2>&1
ufw allow ssh > /dev/null 2>&1
ufw allow 80/tcp > /dev/null 2>&1
ufw allow 443/tcp > /dev/null 2>&1
ufw --force enable > /dev/null 2>&1

echo "[3/8] Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

echo "[4/8] Creating environment file..."
if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
# Exchange API Keys
EXCHANGE_API_KEY=your-api-key-here
EXCHANGE_SECRET=your-secret-here
EXCHANGE_PASSPHRASE=

# TradingView Webhook Secret (change this!)
TRADINGVIEW_WEBHOOK_SECRET=$(openssl rand -hex 16)

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Dashboard Auth (change these!)
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=changeme123
DASHBOARD_HASH_KEY=$(openssl rand -hex 32)
DASHBOARD_COOKIE_KEY=$(openssl rand -hex 32)

# Webhook
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
ENVEOF
    chmod 600 .env
    echo "  Created .env — EDIT IT with your actual keys!"
    echo "  nano $INSTALL_DIR/.env"
else
    echo "  .env already exists, skipping"
fi

echo "[5/8] Building Docker images..."
docker compose build --quiet

echo "[6/8] Installing systemd service..."
cp deploy/trading-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable trading-bot

echo "[7/8] Installing Cloudflare Tunnel (optional)..."
if ! command -v cloudflared &> /dev/null; then
    curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb > /dev/null 2>&1
    dpkg -i /tmp/cloudflared.deb > /dev/null 2>&1
fi
echo "  Cloudflared installed. Run 'cloudflared tunnel login' to authenticate."

echo "[8/8] Starting services..."
systemctl start trading-bot

echo ""
echo "================================================"
echo "  DEPLOYMENT COMPLETE"
echo "================================================"
echo ""
echo "Dashboard:  http://localhost:8501"
echo "Webhooks:   http://localhost:8000"
echo "Logs:       journalctl -u trading-bot -f"
echo ""
echo "NEXT STEPS:"
echo "  1. Edit .env:  nano $INSTALL_DIR/.env"
echo "  2. Restart:    systemctl restart trading-bot"
echo "  3. Public URL: cloudflared tunnel login && cloudflared tunnel create trading-bot"
echo "  4. Mobile:     Open dashboard URL → Add to Home Screen"
echo ""
echo "Zero-cost public access:"
echo "  Oracle Cloud ARM Free (24GB RAM forever)"
echo "  + Cloudflare Tunnel (free HTTPS + DDoS protection)"
echo "  + Cloudflare Zero Trust (free auth for 50 users)"
echo ""
