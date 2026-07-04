# Multi-Agent Trading Framework

Autonomous multi-agent trading system with MCTS look-ahead search, realistic transaction costs, and hard risk guardrails.

**Built by [Fidel Cedric Odoyo](https://github.com/Polymerthcedric)**
- Portfolio: [polymerthcedric.github.io/portfolio](https://polymerthcedric.github.io/portfolio)
- LinkedIn: [linkedin.com/in/fidel-odoyo](https://linkedin.com/in/fidel-odoyo)
- Certifications: [linkedin.com/in/fidel-odoyo/details/certifications](https://linkedin.com/in/fidel-odoyo/details/certifications)

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   Market Data                    │
│   TradingView · IBKR · yfinance                 │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│               Agent Pipeline                     │
│  ┌────────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Predictive │ │ Context  │ │ Volatility   │   │
│  │  (trend)   │ │ (regime) │ │  (risk)      │   │
│  └─────┬──────┘ └────┬─────┘ └──────┬───────┘   │
│        │             │              │            │
│  ┌─────▼─────────────▼──────────────▼───────┐   │
│  │            Risk Manager                  │   │
│  │      (gatekeeper — immutable caps)       │   │
│  └─────────────────┬────────────────────────┘   │
│                    │                             │
│  ┌─────────────────▼────────────────────────┐   │
│  │           MCTS Search Engine             │   │
│  │    UCB1 tree · 80+ rollouts · depth=5    │   │
│  │    direction-matching accuracy tracked    │   │
│  └─────────────────┬────────────────────────┘   │
└────────────────────┼────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│       Execution Layer                            │
│   Paper Trading · IBKR Live/Paper                │
│   Slippage(2bps)+Spread(1bps)+Commission(0.1%)  │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│       Ledger + Feedback Loop                     │
│   Runtime JSON · Trade History · Self-Learning   │
└─────────────────────────────────────────────────┘
```

## Quick Start

```bash
pip install -r requirements.txt

# Dashboard (browser UI)
streamlit run dashboard.py

# Paper trading with live TV data
python main.py --tv

# Backtest validation
python tests/validate_oos.py
```

## Features

- **4-agent consensus** — predictive (SMA/EMA crossover + RSI), context (regime detection), volatility (z-score regimes), risk manager (immutable guardrails)
- **MCTS look-ahead search** — UCB1 tree search with 80+ simulations, direction-matching accuracy tracking
- **Realistic execution** — configurable slippage (2bps), spread (1bps), commission (0.1%) applied to every fill
- **Data integrity** — LIVE/PAPER mode raises `DataUnavailableError` on missing data; no silent synthetic fallback
- **Risk guardrails** — 2% max per trade, 2% trailing stop, 5% daily drawdown → 24h lockdown; all constants immutable at runtime
- **24-dim state vectors** — price, position, cash, RSI, SMA, EMA, ATR, momentum, ADX, volume, order book imbalance, pairs Z-score, volatility index, drawdown, P&L
- **Comprehensive logging** — every agent's reasoning, fill costs, MCTS metrics logged to JSON ledgers
- **Out-of-sample validation** — `tests/validate_oos.py` measures Sharpe degradation across train/test splits
- **IBKR integration** — live/paper execution via `ib_insync` with disconnected-safe mock fallback
- **Streamlit dashboard** — 4 tabs (Market, Agents+Search, Portfolio, Backtest) with data-quality watchdog

## Project Structure

```
├── agents/              # Agent modules (predictive, context, volatility, risk_manager)
├── config/              # Settings (frozen dataclass)
├── connectors/          # Data feeds (TradingView, IBKR, yfinance, paper platform)
├── engine/              # Core engine (state, evaluator, MCTS search tree, environment, watchdog)
├── execution/           # Broker and search engine orchestration
├── memory/              # Trade ledger and self-learning critic
├── tests/               # OOS validation, IBKR kill-switch tests
├── dashboard.py         # Streamlit UI
├── main.py              # Orchestration entry point
└── requirements.txt     # Dependencies
```

## Configuration

All risk limits are in `agents/risk_manager.py` as module-level constants. They are **immutable at runtime** — the self-learning loop and dashboard sliders cannot override them.

Settings are in `config/settings.py` (frozen dataclass).

## Modes

- **DEMO** — allows synthetic data fallback for development
- **PAPER** — paper trading with real data; raises errors on data failure (default)
- **LIVE** — same as PAPER but flagged for IBKR live account

## Dependencies

- `numpy`, `pandas` — data processing
- `tradingview-ta` — free live market data
- `yfinance` — historical backtesting data
- `streamlit`, `plotly` — dashboard
- `ib_insync` — IBKR integration (optional)
