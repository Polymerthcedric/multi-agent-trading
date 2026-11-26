# Multi-Agent Trading

A Python research project for exploring trading signals, search, and risk controls. The dashboard reads market data where available and uses a paper-trading connector with a virtual balance. The project is paper trading only. It does not make live trades or promise returns.

## Research dashboard

The hosted dashboard is a demo of this research prototype: [https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/](https://multi-agent-trading-epvurxxuzcdm3j3opza3tu.streamlit.app/).

It shows simulated orders and a virtual balance. It places no live exchange orders. Synthetic demo data is not market evidence. The app may require Streamlit account access.

## Run locally

Use Python 3.10 or newer:

```sh
python3 start.py
```

The first run creates a virtual environment, installs dependencies, and creates a local `.env` file for optional alerts. The dashboard opens at `http://localhost:8501`.

## What is in the repo

- Signal and risk modules under `agents/`
- A Monte Carlo Tree Search experiment in the dashboard, clearly separated from the paper runner and the OOS research policy
- Market-data adapters under `connectors/`
- A Streamlit dashboard and historical evaluation scripts
- A paper-trading connector used by the main runner and dashboard
- A portfolio risk monitor that checks correlation, exposure, and historical VaR before a new long position
- A walk-forward validator in `engine/walk_forward.py`
- One market-only policy used by both paper mode and OOS research, with risk-sized targets and protective stops

The project is experimental. Backtest results depend on the data, costs, and assumptions used. `LiveExchangeConnector` is a stub. The IBKR adapter reads market data only: it rejects live ports and never places an order. Orders run through `PaperTradingConnector` with a virtual balance.

## Validation

Install the runtime and test dependencies, then run the offline suite:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

`requirements-dev.txt` includes the runtime dependencies. `python3 -m pytest` runs the local suite and does not call a data provider. `python3 test_models.py --sim` is a deterministic synthetic smoke check; `python3 test_models.py --live` fetches public market data but never submits orders.
`yfinance` is the primary free market-data adapter; paper mode refuses missing or stale feed data rather than manufacturing prices.

For walk-forward validation:

```sh
python3 tests/validate_oos.py --strategy multi_agent --demo-bars 240 --no-write
python3 tests/validate_oos.py --strategy multi_agent --bars data/bars.csv --output logs/oos.json
python3 tests/validate_oos.py --strategy state_evaluator --bars data/bars.csv --no-write
```

The default `multi_agent` policy is the same decision module used by the paper runner. It combines predictive direction and context alignment, then sizes long-only positions from an ATR stop distance, a per-trade loss budget, cash, and exposure caps. Daily and weekly loss limits, a drawdown liquidation rule, daily trade limits, and protective stops are applied in the shared policy. Debate output is explanatory only; its correlated heuristic inputs do not increase the strategy's confidence. Historical news sentiment is excluded because there is no timestamped sentiment dataset. The policy is fixed, not trained or tuned; each test fold is compared with buy-and-hold and cash baselines. Signals use the bar close, fills occur at the next bar's open, and spread, slippage, and commission are modeled.

The paper runner also applies the cross-asset portfolio monitor before opening a long. The walk-forward validator is currently single-symbol, so it cannot validate cross-asset correlation or portfolio VaR. Paper orders execute at the current quote while research fills at the next bar's open; this execution-timing difference must be considered when interpreting results. A policy stop is simulated in research and polled in paper mode; it is not an exchange-hosted stop order.

The optional `state_evaluator` strategy is the legacy heuristic evaluator; it tunes only on each train window, then scores the following test window once. No test bar is used for parameter selection. Both strategies use one chronological series and causal features. Demo mode generates deterministic synthetic bars, which are not evidence of real-market performance. Use `--bars` with one genuine chronological series to test an idea. Sharpe uses an annual factor of 1638 by default (hourly bars); pass `--annual-factor 252` for daily bars.

A demo report is labelled `SYNTHETIC_DEMO`. A `--bars` report names the local file and does not make a performance claim. Both labels say that the numbers are not evidence of real-market performance.

Portfolio risk numbers are indicative. Return inputs come from bar or snapshot closes, not uniform daily bars. The gate blocks a long entry or an addition to a long when exposure, correlated concentration, or 99% VaR exceeds its limit; risk-assessment failures block new entries. Sells and risk-reducing orders remain allowed.

## Readiness

This is suitable for offline research and monitored paper experiments, not live trading. Prediction confidence is heuristic, free market data may be delayed or incomplete, cross-asset risk is not yet represented in OOS results, and no real-market edge is established. Do not connect live execution.

## Docker

Copy `.env.example` to `.env`, generate a value for `TRADINGVIEW_WEBHOOK_SECRET` if you plan to use the webhook, then run:

```sh
docker compose up --build
```

The dashboard and webhook server should not be exposed to the public internet without access controls. Hosting and data-provider costs depend on the services and plans you choose.
