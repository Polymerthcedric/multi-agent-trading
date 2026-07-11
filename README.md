# Multi-Agent Trading Framework

Autonomous multi-agent trading system for **gold, silver, commodities, forex, stocks, and ETFs** with MCTS look-ahead search, sentiment analysis, bull/bear debate, realistic transaction costs, and self-learning feedback loops.

**Live Dashboard:** [https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/](https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/)

**Built by [Fidel Cedric Odoyo](https://github.com/Polymerthcedric)**
- Portfolio: [polymerthcedric.github.io/portfolio](https://polymerthcedric.github.io/portfolio)
- LinkedIn: [linkedin.com/in/fidel-odoyo](https://linkedin.com/in/fidel-odoyo)

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Market Data Layer                     │
│    yfinance (primary) · TradingView (optional) · Webhooks│
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   Agent Pipeline (6 Agents)               │
│  ┌────────────┐  ┌──────────┐  ┌──────────────┐          │
│  │ Predictive │  │ Context  │  │  Volatility  │          │
│  │ RSI+MACD+  │  │ Regime   │  │  ATR+Z-score │          │
│  │ EMA+ADX+BB │  │ Detection│  │  +IV regimes │          │
│  └─────┬──────┘  └────┬─────┘  └──────┬───────┘          │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼────────────┐     │
│  │         Sentiment Agent (yfinance news)          │     │
│  │    Keyword scoring · Bullish/Bearish/Neutral     │     │
│  └───────────────────┬─────────────────────────────┘     │
│                      │                                    │
│  ┌───────────────────▼─────────────────────────────┐     │
│  │      Bull/Bear Debate (TradingAgents-inspired)  │     │
│  │  Two researchers argue for/against trades        │     │
│  │  Confidence adjustment based on debate outcome   │     │
│  └───────────────────┬─────────────────────────────┘     │
│                      │                                    │
│  ┌───────────────────▼─────────────────────────────┐     │
│  │           Risk Manager (Constitutional)          │     │
│  │  Circuit Breakers · Kill Switch · Kelly Sizing   │     │
│  │  Learned params from self-learning feedback      │     │
│  └───────────────────┬─────────────────────────────┘     │
│                      │                                    │
│  ┌───────────────────▼─────────────────────────────┐     │
│  │          MCTS Search Engine (UCB1)              │     │
│  │   80+ rollouts · depth=5 · direction tracking   │     │
│  └───────────────────┬─────────────────────────────┘     │
└──────────────────────┼───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│               Execution Layer                             │
│   Paper Trading · IBKR · Slippage(2bps) + Spread(1bps)   │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│          Ledger + Self-Learning Feedback                  │
│   Runtime JSON · Trade History · Auto-tuning params       │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│         Alerts + Decision Logging                         │
│   WhatsApp (CallMeBot) · Telegram · Decision Audit Trail  │
└──────────────────────────────────────────────────────────┘
```

## Features

### Multi-Agent Consensus (6 Agents)
- **Predictive Agent** — RSI, MACD, EMA/SMA crossover, ADX trend strength, Bollinger Band position, momentum
- **Context Agent** — Market regime detection (bullish/bearish/neutral), support/resistance proximity, trend strength
- **Volatility Agent** — ATR, implied volatility, z-score regimes (high_vol_chaos, low_vol_trend, mean_reverting)
- **Sentiment Agent** — Yahoo Finance news analysis with keyword-based bullish/bearish scoring (free, no API key)
- **Bull/Bear Debate** — Two virtual researchers argue for/against trades, adjusting confidence based on debate outcome
- **Risk Manager** — Constitutional limits, Kelly criterion sizing, circuit breakers, self-learning parameter tuning

### Circuit Breakers (Industry Standard)
| Level | Trigger | Action |
|-------|---------|--------|
| Level 1 | Daily loss > 3% | Pause trading 12 hours |
| Level 2 | Weekly loss > 5% | Extended halt |
| Level 3 | Drawdown > 7% | **KILL SWITCH** — full shutdown |
| Level 4 | Trades > 15/day | Block new entries |

### Decision Reasoning Logger
Every trade decision includes full reasoning chain:
- Individual agent outputs and confidence scores
- Sentiment analysis results
- Bull/Bear debate arguments and outcome
- Risk manager decision with circuit breaker status
- MCTS search results

### Alerts (Free)
- **WhatsApp** — CallMeBot API (works in Kenya: Safaricom/Airtel/Telkom)
- **Telegram** — Trade execution, daily summaries, kill switch alerts

### Data Source
- **yfinance** (primary) — Free, no API key, real-time data for all 10 symbols
- **TradingView** (optional fallback) — Archived library, rate-limited

### Self-Learning Feedback Loop
- Performance metrics computed every 25 trades (Sharpe, win rate, profit factor)
- Confidence threshold auto-adjusts based on win rate
- Kelly criterion position sizing adapts to recent performance
- Learned parameters persist to `config/learned_parameters.json` and feed back to risk manager

### MCTS Look-Ahead Search
- UCB1 tree search with 80+ simulations per symbol
- Direction-matching accuracy tracked across rollouts
- Heuristic simulator with RSI mean-reversion and momentum bias

## Quick Start

### One-Command (Kenya-friendly)
```bash
python start.py
```
Automatically installs dependencies, launches dashboard + paper trading.

### Local
```bash
pip install -r requirements.txt

# Dashboard (browser UI at http://localhost:8501)
streamlit run dashboard.py

# Paper trading with live yfinance data
python main.py

# Start webhook receiver (for TradingView alerts)
python webhook_server.py
```

### Docker
```bash
docker compose up --build
```
Exposes port 8501 (dashboard) and port 8000 (webhook receiver).

## Tracked Assets

| Category | Symbols | Source |
|----------|---------|--------|
| **Commodities** | GOLD/USD, SILVER/USD | yfinance |
| **Forex** | EUR/USD, GBP/USD, USD/JPY | yfinance |
| **US Stocks** | AAPL, MSFT, GOOGL | yfinance |
| **ETFs** | SPY, QQQ | yfinance |

## WhatsApp Setup (Kenya)

1. Open WhatsApp on your phone
2. Save **+34 644 10 55 84** (CallMeBot) in your contacts
3. Send this exact message: `I allow callmebot to send me messages`
4. Wait 2-3 minutes for API key reply
5. Add to `.env`:
   ```
   WHATSAPP_PHONE=254XXXXXXXXX
   WHATSAPP_API_KEY=your_api_key_here
   ```

## Telegram Setup

1. Create bot via @BotFather on Telegram
2. Get your chat ID via @userinfobot
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

## Project Structure

```
├── agents/                  # Agent modules
│   ├── predictive.py        # Trend prediction (RSI, MACD, EMA, ADX, BB)
│   ├── context.py           # Market regime detection
│   ├── volatility.py        # Volatility analysis and risk scaling
│   ├── sentiment.py         # Yahoo Finance news sentiment analysis
│   ├── debate.py            # Bull/Bear structured debate engine
│   ├── decision_log.py      # Full decision reasoning audit trail
│   └── risk_manager.py      # Constitutional risk gatekeeper + circuit breakers
├── config/                  # Configuration
│   ├── settings.py          # Frozen dataclass settings
│   └── learned_parameters.json  # Auto-tuned risk parameters
├── connectors/              # Data feeds and bridges
│   ├── tv_datafeed.py       # yfinance primary, TradingView optional fallback
│   ├── platform.py          # Paper/Live exchange connector
│   ├── ibkr.py              # Interactive Brokers integration
│   ├── historical.py        # Historical data (xfinance/yfinance)
│   └── webhooks/            # TradingView webhook bridge
│       └── receiver.py      # FastAPI webhook receiver + signal monitor
├── engine/                  # Core engine
│   ├── state.py             # 24-dim market state vectors
│   ├── evaluator.py         # State scoring for MCTS
│   ├── search_tree.py       # UCB1 Monte Carlo Tree Search
│   ├── environment.py       # Trading environment simulation
│   ├── ledger.py            # Runtime JSON ledger
│   ├── self_learner.py      # PPO/RL scaffold
│   └── watchdog.py          # Data quality monitoring
├── execution/               # Order execution
│   ├── broker.py            # Slippage/spread/commission modeling
│   └── engine.py            # MCTS search orchestration
├── memory/                  # Trade recording and learning
│   └── feedback_loop.py     # Trade ledger + self-learning critic
├── monitoring/              # Alerts and notifications
│   ├── whatsapp.py          # CallMeBot WhatsApp alerts (Kenya)
│   ├── telegram.py          # Telegram trade/kill switch alerts
│   └── __init__.py          # Unified alert dispatcher
├── pinescript/              # TradingView integration
│   └── multi_agent_indicator.pine  # Full agent overlay indicator
├── tests/                   # Validation tests
│   ├── test_ibkr_killswitch.py  # 5 kill-switch safety tests
│   └── validate_oos.py      # Out-of-sample backtest validation
├── static/                  # PWA assets
│   └── manifest.json        # Mobile home-screen install
├── deploy/                  # Deployment configs
│   ├── install.sh           # One-click VPS installer
│   ├── trading-bot.service  # Systemd service
│   └── cloudflared-config.yml  # Free HTTPS tunnel
├── dashboard.py             # Streamlit dashboard (5 tabs)
├── main.py                  # Paper trading orchestrator (6 agents)
├── start.py                 # One-command Kenya launcher
├── webhook_server.py        # TradingView webhook bridge server
├── Dockerfile               # Container build
├── docker-compose.yml       # Orchestrated deployment
├── .env.example             # Configuration template
├── requirements.txt         # Dependencies
├── KENYA.md                 # Kenya-specific setup guide
└── DEPLOY.md                # Comprehensive deployment guide
```

## Configuration

### Environment Variables (.env)
```bash
# Data Source
DATA_SOURCE=yfinance  # primary (free, no API key)

# WhatsApp (Kenya)
WHATSAPP_PHONE=+2547XXXXXXXX
WHATSAPP_API_KEY=your_api_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Trading (optional)
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
TRADINGVIEW_WEBHOOK_SECRET=your-secret-token
```

### Risk Parameters (Immutable at Runtime)
All risk limits in `agents/risk_manager.py` as module-level constants:
- `MAX_RISK_PER_TRADE = 0.015` (1.5% of portfolio)
- `TRAILING_STOP_LOSS = 0.02` (2% below fill)
- `DAILY_DRAWDOWN_HALT = 0.03` (3% daily loss → 12h lockdown)
- `KILL_SWITCH_DRAWDOWN = 0.07` (7% → full halt)
- `MAX_TRADES_PER_DAY = 15`

### Modes
- **DEMO** — synthetic data fallback for development
- **PAPER** — real data, simulated execution (default)
- **LIVE** — same as PAPER but flagged for IBKR live accounts

## Deployment

### Free Options (No Credit Card)
1. **Streamlit Cloud** — Dashboard only (https://share.streamlit.io)
2. **Ping Africa Cloud** — Full system, M-Pesa payment (Kenya-based)

### Free Tier (Card Required for Verification)
- **Oracle Cloud** — Always-free VM, 24/7 uptime

See [DEPLOY.md](DEPLOY.md) for comprehensive deployment guide.

## Dependencies

- `numpy`, `pandas` — data processing
- `yfinance`, `xfinance` — market data (free, no API key)
- `streamlit`, `plotly` — interactive dashboard
- `ib_insync` — Interactive Brokers integration (optional)
- `fastapi`, `uvicorn` — webhook receiver server
- `pydantic` — data validation
- `scipy` — statistical analysis
- `requests` — WhatsApp/Telegram alerts

## License

MIT License — Copyright 2026 Fidel Cedric Odoyo
