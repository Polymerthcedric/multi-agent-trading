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

echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose git curl ufw > /dev/null 2>&1
systemctl enable docker
systemctl start docker

echo "[2/7] Configuring firewall..."
ufw --force reset > /dev/null 2>&1
ufw default deny incoming > /dev/null 2>&1
ufw default allow outgoing > /dev/null 2>&1
ufw allow ssh > /dev/null 2>&1
ufw allow 80/tcp > /dev/null 2>&1
ufw allow 443/tcp > /dev/null 2>&1
ufw --force enable > /dev/null 2>&1

echo "[3/7] Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR" && git pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

echo "[4/7] Creating environment file..."
if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
# Exchange API Keys
EXCHANGE_API_KEY=your-api-key-here
EXCHANGE_SECRET=your-secret-here
EXCHANGE_PASSPHRASE=

# TradingView Webhook Secret (change this!)
TRADINGVIEW_WEBHOOK_SECRET=change-me

# WhatsApp Alerts (Kenya-friendly)
WHATSAPP_API_KEY=
WHATSAPP_PHONE=254

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Dashboard Auth (change these!)
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=changeme123

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

echo "[5/7] Building Docker images..."
docker compose build --quiet

echo "[6/7] Installing systemd service..."
cp deploy/trading-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable trading-bot

echo "[7/7] Starting services..."
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
echo ""
echo "FREE PUBLIC ACCESS OPTIONS:"
echo "  1. Streamlit Cloud: push to GitHub → share.streamlit.io → deploy"
echo "  2. Ping Africa: cloud.ping.africa → sign up → deploy (M-Pesa!)"
echo "  3. Oracle Cloud: cloud.oracle.com/free → ARM instance → free forever"
echo ""
