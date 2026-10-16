# Local setup

The public Streamlit page is a demo dashboard. It uses paper trading and a virtual balance; it does not place live orders. Market data can be delayed or unavailable, and a hosted demo may sleep when unused.

## Run on your computer

You need Python 3.10 or newer and an internet connection for market data.

```sh
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
python3 start.py
```

The first run installs the Python packages and creates `.env`. Add alert credentials only if you plan to use those integrations. The dashboard opens at `http://localhost:8501`.

## Open it on your phone

To view the dashboard on another device on the same Wi-Fi, set `DASHBOARD_ADDRESS=0.0.0.0` in `.env` before starting the app, then open your computer's local IP address on port `8501` from the phone. This exposes the unauthenticated dashboard to devices on that network. Do not forward the port to the public internet.

## Hosting

You can host the dashboard with Streamlit Community Cloud or another provider that supports Streamlit. Check the provider's current limits and pricing before deploying. This project also starts a webhook server; do not expose it publicly until you have configured and reviewed its access controls.

## Trading mode

The current dashboard and main runner use simulated trades. The `MODE=LIVE` setting described in older versions is not supported by the main runner. Do not use this project to trade real money.
