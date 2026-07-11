# Kenya Simple Setup Guide

## Live Dashboard (No Setup Required)
**View the trading bot in action now:** [https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/](https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/)

Share this link with anyone. It's always live and updates automatically.

## What You Need
- A laptop or desktop computer (or even a phone with Termux)
- Internet connection
- That's it. No credit card. No VPS. No Docker.

## Step 1: Install Python (if not already installed)
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip -y

# Or check if you already have it
python3 --version
```

## Step 2: Get the Bot
```bash
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
```

## Step 3: Start
```bash
python3 start.py
```

That's it. Dashboard opens at http://localhost:8501

## Step 4: WhatsApp Alerts (Optional but Recommended)

1. Save this number in your phone: **+34 644 10 55 84** (CallMeBot - Spain)
2. Open WhatsApp, find "CallMeBot" in your contacts
3. Send this exact message: `I allow callmebot to send me messages`
4. Wait 2-3 minutes, you'll get an API key as a reply
5. Edit the `.env` file:
```bash
nano .env
```
Add your phone number and API key:
```
WHATSAPP_API_KEY=123456
WHATSAPP_PHONE=254712345678
```
6. Restart the bot (Ctrl+C, then run `python3 start.py` again)

## Step 5: Phone Access (Optional)

If you want to access the dashboard from your phone on the same WiFi:

1. Find your computer's IP address:
```bash
hostname -I
```
2. Open phone browser, go to: `http://<your-ip>:8501`
3. Bookmark it or "Add to Home Screen"

## Step 6: Public Access (Free, No Credit Card)

### Option A: Streamlit Community Cloud (Easiest)
1. Push your code to GitHub
2. Go to https://share.streamlit.io
3. Sign in with GitHub
4. Select your repo, set file to `dashboard.py`
5. Click Deploy — you get a public URL instantly

**Free tier:** 1GB RAM, app sleeps after 7 days of inactivity
**Limitation:** No webhook server (dashboard only)

### Option B: Ping Africa Cloud (Kenya-Friendly)
1. Go to https://cloud.ping.africa
2. Sign up with GitHub or .edu email
3. Get free credits (no credit card needed!)
4. Deploy your bot as a Docker container
5. Pay with M-Pesa if you need more

**Free tier:** Free credits, M-Pesa payment available
**Best for:** Kenya developers, local support

### Option C: Oracle Cloud Free Tier (Most Powerful)
1. Go to https://cloud.oracle.com/free
2. Sign up (requires debit card for identity verification)
3. Create an ARM instance: 2 OCPU, 12GB RAM — free forever
4. SSH in, run `python3 start.py`
5. Share the public IP

**Free tier:** 2 OCPU, 12GB RAM, 200GB storage — free forever
**Catch:** Requires credit/debit card for signup (not charged)

## Trading Modes

- **PAPER mode** (default): Safe, no real money, just practice
- **LIVE mode**: Real money! Only switch when you know what you're doing

To switch: edit `.env` and change `MODE=PAPER` to `MODE=LIVE`

## What You'll See

- **Market tab**: Live prices for gold, silver, forex, stocks
- **Agents tab**: AI analysis of each market
- **Portfolio tab**: Your trades and positions
- **Risk tab**: Safety circuit breakers

## Troubleshooting

**"Port already in use"**
```bash
# Kill any running instances
pkill -f streamlit
pkill -f webhook_server
# Try again
python3 start.py
```

**"Module not found"**
```bash
# Reinstall dependencies
.venv/bin/pip install -r requirements.txt
```

**WhatsApp alerts not working?**
- Make sure you sent the exact message to CallMeBot
- Check your phone number format: 254XXXXXXXXX (no + or spaces)
- API key takes 2-3 minutes to activate
- CallMeBot is free and works in Kenya (Safaricom, Airtel, Telkom)

**yfinance not working?**
- The bot uses xfinance with automatic failover
- If Yahoo Finance is down, it falls back to Stooq or Binance
- No action needed — it handles this automatically

## Cost: KES 0
Everything is free:
- Bot: free
- Data: TradingView free tier + xfinance failover
- Alerts: CallMeBot free WhatsApp API
- Dashboard: runs on your own machine
- Hosting: Streamlit Community Cloud or Ping Africa Cloud (free)
