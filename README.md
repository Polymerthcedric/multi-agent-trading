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

The project is experimental. Backtest results depend on the data, costs, and assumptions used. The included live exchange connector is a stub; changing an environment variable does not enable live orders.

## Docker

Copy `.env.example` to `.env`, generate a value for `TRADINGVIEW_WEBHOOK_SECRET` if you plan to use the webhook, then run:

```sh
docker compose up --build
```

The dashboard and webhook server should not be exposed to the public internet without access controls. Hosting and data-provider costs depend on the services and plans you choose.
