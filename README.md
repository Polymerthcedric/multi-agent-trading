# Multi-Agent Trading Framework

Autonomous multi-agent trading system for **gold, silver, commodities, forex, stocks, and ETFs** with MCTS look-ahead search, TradingView integration, realistic transaction costs, and self-learning feedback loops.

**Built by [Fidel Cedric Odoyo](https://github.com/Polymerthcedric)**
- Portfolio: [polymerthcedric.github.io/portfolio](https://polymerthcedric.github.io/portfolio)
- LinkedIn: [linkedin.com/in/fidel-odoyo](https://linkedin.com/in/fidel-odoyo)

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Market Data Layer                     │
│    TradingView (live) · IBKR · yfinance · Webhooks        │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   Agent Pipeline                          │
│  ┌────────────┐  ┌──────────┐  ┌──────────────┐          │
│  │ Predictive │  │ Context  │  │  Volatility  │          │
│  │ RSI+MACD+  │  │ Regime   │  │  ATR+Z-score │          │
│  │ EMA+ADX+BB │  │ Detection│  │  +IV regimes │          │
│  └─────┬──────┘  └────┬─────┘  └──────┬───────┘          │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼────────────┐     │
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
│         TradingView Integration                           │
│   Pine Script indicators · Webhook alerts · Dashboard     │
└──────────────────────────────────────────────────────────┘
```

## Features

### Multi-Agent Consensus
- **Predictive Agent** — RSI, MACD, EMA/SMA crossover, ADX trend strength, Bollinger Band position, momentum
- **Context Agent** — Market regime detection (bullish/bearish/neutral), support/resistance proximity, trend strength
- **Volatility Agent** — ATR, implied volatility, z-score regimes (high_vol_chaos, low_vol_trend, mean_reverting)
- **Risk Manager** — Constitutional limits, Kelly criterion sizing, circuit breakers, self-learning parameter tuning

### Circuit Breakers (Industry Standard)
| Level | Trigger | Action |
|-------|---------|--------|
| Level 1 | Daily loss > 3% | Pause trading 12 hours |
| Level 2 | Weekly loss > 5% | Extended halt |
| Level 3 | Drawdown > 7% | **KILL SWITCH** — full shutdown |
| Level 4 | Trades > 15/day | Block new entries |

### TradingView Integration
- **Live data feed** via `tradingview_ta` — gold, silver, forex, stocks
- **Pine Script indicator** — full agent analysis overlay with buy/sell signals
- **Webhook bridge** (FastAPI) — receives TradingView alerts, routes through agent pipeline
- **Signal monitor** — real-time web dashboard for incoming signals

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

### Local
```bash
pip install -r requirements.txt

# Dashboard (browser UI at http://localhost:8501)
streamlit run dashboard.py

# Paper trading with live TradingView data
python main.py --tv

# Start webhook receiver (for TradingView alerts)
python webhook_server.py

# Backtest validation
python tests/validate_oos.py
```

### Docker
```bash
docker compose up --build
```
Exposes port 8501 (dashboard) and port 8000 (webhook receiver).

## Tracked Assets

| Category | Symbols | Source |
|----------|---------|--------|
| **Commodities** | GOLD/USD, SILVER/USD | TradingView (TVC) |
| **Forex** | EUR/USD, GBP/USD, USD/JPY | TradingView (FX_IDC) |
| **US Stocks** | AAPL, MSFT, GOOGL | TradingView (NASDAQ) |
| **ETFs** | SPY, QQQ | TradingView (AMEX/NASDAQ) |

## TradingView Setup

### 1. Import Pine Script Indicator
1. Open TradingView → Pine Editor
2. Paste contents of `pinescript/multi_agent_indicator.pine`
3. Add to your chart
4. Configure alerts on the indicator

### 2. Configure Webhook Alerts
In your Pine Script alert settings:
- **Webhook URL**: `https://your-server:8000/webhook`
- **Message template**:
```json
{
  "passphrase": "your-secret-token",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "price": {{close}},
  "volume": {{strategy.order.contracts}},
  "strategy_id": "multi_agent_v1",
  "timeframe": "{{interval}}"
}
```

### 3. Set Environment Variables
```bash
export TRADINGVIEW_WEBHOOK_SECRET="your-secret-token"
```

## Project Structure

```
├── agents/                  # Agent modules
│   ├── predictive.py        # Trend prediction (RSI, MACD, EMA, ADX, BB)
│   ├── context.py           # Market regime detection
│   ├── volatility.py        # Volatility analysis and risk scaling
│   └── risk_manager.py      # Constitutional risk gatekeeper + circuit breakers
├── config/                  # Configuration
│   ├── settings.py          # Frozen dataclass settings
│   └── learned_parameters.json  # Auto-tuned risk parameters
├── connectors/              # Data feeds and bridges
│   ├── tv_datafeed.py       # TradingView live data (10 symbols)
│   ├── platform.py          # Paper/Live exchange connector
│   ├── ibkr.py              # Interactive Brokers integration
│   ├── historical.py        # yfinance historical data
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
├── pinescript/              # TradingView integration
│   └── multi_agent_indicator.pine  # Full agent overlay indicator
├── tests/                   # Validation tests
│   ├── test_ibkr_killswitch.py  # 5 kill-switch safety tests
│   └── validate_oos.py      # Out-of-sample backtest validation
├── dashboard.py             # Streamlit dashboard (5 tabs)
├── main.py                  # Paper trading orchestrator
├── webhook_server.py        # TradingView webhook bridge server
├── Dockerfile               # Container build
├── docker-compose.yml       # Orchestrated deployment
└── requirements.txt         # Dependencies
```

## Configuration

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

## Dependencies

- `numpy`, `pandas` — data processing
- `tradingview-ta` — live market data from TradingView
- `yfinance` — historical backtesting data
- `streamlit`, `plotly` — interactive dashboard
- `ib_insync` — Interactive Brokers integration (optional)
- `fastapi`, `uvicorn` — webhook receiver server
- `pydantic` — data validation
- `scipy` — statistical analysis

## License

MIT License — Copyright 2026 Fidel Cedric Odoyo
