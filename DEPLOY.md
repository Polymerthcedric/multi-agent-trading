# Deployment Guide — Multi-Agent Trading Bot

## Quick Start (5 minutes)

### Option A: Docker (any machine)
```bash
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
cp .env.example .env  # edit with your keys
docker compose up -d
```

### Option B: One-Click VPS Install
```bash
# On an Ubuntu VPS (Oracle Cloud free tier, DigitalOcean, etc.)
curl -sL https://raw.githubusercontent.com/Polymerthcedric/multi-agent-trading/main/deploy/install.sh | sudo bash
```

---

## Get a Public HTTPS Link (Free)

### Method 1: Cloudflare Tunnel (Recommended — Zero Cost)

1. **Install cloudflared:**
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

2. **Authenticate:**
```bash
cloudflared tunnel login
# Opens browser → log in to Cloudflare → pick a domain
```

3. **Create tunnel:**
```bash
cloudflared tunnel create trading-bot
# Note the tunnel ID from output
```

4. **Configure DNS:**
```bash
cloudflared tunnel route dns trading-bot trading.yourdomain.com
cloudflared tunnel route dns trading-bot dashboard.yourdomain.com
```

5. **Run tunnel:**
```bash
cloudflared tunnel run --url http://localhost:8000 trading-bot
```

Now anyone with the link can access:
- Dashboard: `https://dashboard.yourdomain.com`
- Webhooks: `https://trading.yourdomain.com`

### Method 2: Tailscale (Private Network)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
# Share dashboard at: http://<tailscale-ip>:8501
```

### Method 3: ngrok (Temporary)

```bash
ngrok http 8501
# Copy the https://xxx.ngrok.io link
```

---

## Add Authentication

### Cloudflare Zero Trust (Free for ≤50 users)

1. Go to [Zero Trust Dashboard](https://one.dash.cloudflare.com)
2. Create Access Policy for your domain
3. Add email verification or one-time PIN
4. Anyone with the link must authenticate

### Simple HTTP Auth (Docker)

Already configured via `.env`:
```
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=your-secure-password
```

---

## Mobile Access (PWA)

The dashboard is a Progressive Web App:
1. Open dashboard URL on your phone
2. Tap "Add to Home Screen" (iOS) or "Install" (Android)
3. Works like a native app, shows trade alerts

---

## Telegram Alerts

1. Message [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the bot token
3. Message [@userinfobot](https://t.me/userinfobot) → get your chat ID
4. Add to `.env`:
```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
```
5. Restart: `docker compose restart`

You'll get alerts for:
- Trade executions
- Daily P&L summaries
- Kill switch triggers
- Bot start/stop

---

## Zero-Cost Always-On Architecture

```
┌─────────────────────────────────────────────┐
│          Oracle Cloud Free Tier              │
│          (24GB RAM, forever)                 │
│                                             │
│  ┌─────────┐  ┌──────────────┐  ┌────────┐ │
│  │ Streamlit│  │ Webhook Srv  │  │ Bot    │ │
│  │ :8501   │  │ :8000        │  │ Worker │ │
│  └────┬────┘  └──────┬───────┘  └────┬───┘ │
│       └───────────────┴───────────────┘     │
└───────────────────┬─────────────────────────┘
                    │
         Cloudflare Tunnel (free)
                    │
            ┌───────┴───────┐
            │  Public URL   │
            │  trading.*.com│
            │  (free HTTPS) │
            └───────────────┘
```

**Total cost: $0/month**

---

## Troubleshooting

### Check logs
```bash
docker compose logs -f
journalctl -u trading-bot -f  # if using systemd
```

### Restart
```bash
docker compose restart
systemctl restart trading-bot  # if using systemd
```

### Kill switch activated
Check `config/learned_parameters.json` or `logs/trade_ledger.json`.
Reset by deleting the file and restarting.

### Health check
```bash
curl http://localhost:8000/health
```
