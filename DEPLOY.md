# Deployment Guide — Multi-Agent Trading Bot

## Live Dashboard
**Your trading bot is live:** [https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/](https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/)

## Quick Start (5 minutes)

### Option A: Local (any machine)
```bash
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
python3 start.py
```

### Option B: Docker
```bash
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
cp .env.example .env  # edit with your keys
docker compose up -d
```

---

## Get a Public Link (Free)

### Method 1: Streamlit Community Cloud (Easiest — No Credit Card)

1. Push your code to GitHub
2. Go to https://share.streamlit.io
3. Sign in with GitHub
4. Select your repo, set main file to `dashboard.py`
5. Click Deploy

You get a public URL like `https://yourapp.streamlit.app`

**Free tier:** 1GB RAM, app sleeps after 7 days of inactivity
**Best for:** Dashboard viewing, no webhook server

### Method 2: Ping Africa Cloud (Kenya-Friendly — No Credit Card)

1. Go to https://cloud.ping.africa
2. Sign up with GitHub or .edu email
3. Get free credits
4. Deploy as Docker container
5. Pay with M-Pesa if needed

**Free tier:** Free credits, M-Pesa available
**Best for:** Kenya developers, always-on deployment

### Method 3: Oracle Cloud Free Tier (Most Powerful)

1. Go to https://cloud.oracle.com/free
2. Sign up (requires debit card for identity verification — not charged)
3. Create an ARM instance: 2 OCPU, 12GB RAM — free forever
4. SSH in, run the bot

**Free tier:** 2 OCPU, 12GB RAM, 200GB storage — free forever
**Catch:** Requires credit/debit card for signup

### Method 4: Google Cloud Free Tier

1. Go to https://cloud.google.com/free
2. Sign up (requires credit card for identity verification — not charged)
3. Create an e2-micro instance (1GB RAM) — free forever
4. SSH in, run the bot

**Free tier:** 1 shared vCPU, 1GB RAM — free forever
**Catch:** Only 1GB RAM, requires credit card

---

## Add Authentication

### Cloudflare Zero Trust (Free for ≤50 users)

1. Go to [Zero Trust Dashboard](https://one.dash.cloudflare.com)
2. Create Access Policy for your domain
3. Add email verification or one-time PIN
4. Anyone with the link must authenticate

### Simple HTTP Auth

Already configured via `.env`:
```
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=your-secure-password
```

---

## WhatsApp Alerts (Kenya)

1. Save +254 798 348 449 (CallMeBot) in your phone contacts
2. Send `I allow callmebot to send me notifications`
3. Get API key in reply
4. Add to `.env`:
```
WHATSAPP_API_KEY=123456
WHATSAPP_PHONE=254712345678
```

You'll get alerts for:
- Trade executions
- Daily P&L summaries
- Kill switch triggers
- Bot start/stop

---

## Zero-Cost Architecture Options

### Option 1: Local + Streamlit Cloud (Dashboard Only)
```
Your Laptop → Streamlit Community Cloud → Public URL
```
- Dashboard: public URL
- Bot: runs locally
- Cost: $0
- Best for: Personal use, testing

### Option 2: Oracle Cloud Free Tier (Full System)
```
Oracle Cloud ARM (12GB RAM) → Cloudflare Tunnel → Public URL
```
- Dashboard + Bot + Webhooks: all on Oracle
- Cost: $0 forever
- Best for: Always-on, full system

### Option 3: Ping Africa Cloud (Kenya)
```
Ping Africa Cloud → Docker → Public URL
```
- Dashboard + Bot + Webhooks: all on cloud
- Cost: Free credits, then M-Pesa
- Best for: Kenya developers, local support

---

## Troubleshooting

### Check logs
```bash
docker compose logs -f
# Or for local:
tail -f trading_bot.log
```

### Restart
```bash
docker compose restart
# Or for local: Ctrl+C, then python3 start.py
```

### Kill switch activated
Check `config/learned_parameters.json` or `logs/trade_ledger.json`.
Reset by deleting the file and restarting.

### Health check
```bash
curl http://localhost:8000/health
```

### yfinance not working
The bot uses xfinance with automatic failover (Yahoo→Stooq→Binance).
If one source is down, it falls back automatically. No action needed.

### tradingview-ta archived
The library still works (v3.3.0) but is no longer maintained.
The bot handles failures gracefully — cached data is used when API fails.
