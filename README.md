# Multi-Agent Trading

A Python research project for exploring trading signals, search, and risk controls. The dashboard reads market data where available and uses a paper-trading connector with a virtual balance. It does not make live trades or promise returns.

## Run locally

Use Python 3.10 or newer:

```sh
python3 start.py
```

The first run creates a virtual environment, installs dependencies, and creates a local `.env` file for optional alerts. The dashboard opens at `http://localhost:8501`.

## What is in the repo

- Signal and risk modules under `agents/`
- Monte Carlo Tree Search experiments under `engine/` and `execution/`
- Market-data adapters under `connectors/`
- A Streamlit dashboard and historical evaluation scripts
- A paper-trading connector used by the main runner and dashboard
- A portfolio risk monitor that checks correlation, exposure, and historical VaR before a new long position
- A walk-forward validator in `engine/walk_forward.py`

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
python3 tests/validate_oos.py --demo-bars 240 --no-write
python3 tests/validate_oos.py --bars data/bars.csv --output logs/oos.json
```

The demo mode generates deterministic synthetic bars. Those results are not evidence of real-market performance. Use `--bars` with one real chronological series to test an idea. Each fold tunes the evaluator on its train window only, then scores the following test window once. The validator never feeds test bars into parameter choice. Sharpe uses an annual factor of 1638 by default, which assumes hourly bars. Pass `--annual-factor 252` for daily bars.

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
