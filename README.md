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
- A market-only replay of the paper runner's prediction, context, volatility, debate, and consensus gate

The project is experimental. Backtest results depend on the data, costs, and assumptions used. `LiveExchangeConnector` is a stub. The IBKR adapter reads market data only: it rejects live ports and never places an order. Orders run through `PaperTradingConnector` with a virtual balance.

## Validation

Run the offline tests with the optional test dependencies:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

`python3 -m pytest` runs the local suite. It does not call a data provider. The scripts `test_models.py` and `test_tv_symbols.py` are manual checks and need explicit flags or a direct run.

For walk-forward validation:

```sh
python3 tests/validate_oos.py --strategy multi_agent --demo-bars 240 --no-write
python3 tests/validate_oos.py --strategy multi_agent --bars data/bars.csv --output logs/oos.json
python3 tests/validate_oos.py --strategy state_evaluator --bars data/bars.csv --no-write
```

The default `multi_agent` strategy replays the market-data-only prediction, context, volatility, debate, and shared confidence/consensus gate used by the paper runner. Historical news sentiment is excluded because this repository does not provide timestamped historical sentiment. It is a fixed policy, not a trained or tuned model; each test fold is compared with buy-and-hold and cash baselines. Signals use the bar close and simulated fills occur at the next bar's open with configured slippage and commission. The simulation is long/flat, uses a fixed per-trade notional cap, and does not model every live paper-runner control.

The optional `state_evaluator` strategy is the legacy heuristic evaluator; it tunes only on each train window, then scores the following test window once. No test bar is used for parameter selection. Both strategies use one chronological series and causal features. Demo mode generates deterministic synthetic bars, which are not evidence of real-market performance. Use `--bars` with one genuine chronological series to test an idea. Sharpe uses an annual factor of 1638 by default (hourly bars); pass `--annual-factor 252` for daily bars.

A demo report is labelled `SYNTHETIC_DEMO`. A `--bars` report names the local file and does not make a performance claim. Both labels say that the numbers are not evidence of real-market performance.

Portfolio risk numbers are indicative. Return inputs come from bar or snapshot closes, not uniform daily bars. The gate blocks a long entry or an addition to a long when exposure, correlated concentration, or 99% VaR exceeds its limit. It does not block sells or position reductions.

## Known limitation

The drawdown kill switch in `agents/risk_manager.py` latches until the runner restarts. It halts new paper orders and does not flatten open positions. I have not wired a forced-close path because this project is for research, not live risk management.

## Docker

Copy `.env.example` to `.env`, generate a value for `TRADINGVIEW_WEBHOOK_SECRET` if you plan to use the webhook, then run:

```sh
docker compose up --build
```

The dashboard and webhook server should not be exposed to the public internet without access controls. Hosting and data-provider costs depend on the services and plans you choose.
