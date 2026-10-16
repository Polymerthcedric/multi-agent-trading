# Run and deploy the research dashboard

This project uses a paper-trading connector. It does not place live exchange orders. The dashboard and webhook server do not include user authentication, so keep them on a trusted network and do not expose them directly to the public internet.

## Run locally

```bash
git clone https://github.com/Polymerthcedric/multi-agent-trading.git
cd multi-agent-trading
python3 start.py
```

The launcher creates a virtual environment and `.env` file, installs the listed Python packages, then starts the dashboard on `http://localhost:8501`. The dashboard and webhook bind to `127.0.0.1` by default. The `.env` file is loaded by the launcher; keep secrets there and out of Git.

To let devices on your home network open the dashboard, set `DASHBOARD_ADDRESS=0.0.0.0` in `.env`. The page has no login, so use this only on a trusted private network. Do not forward its port to the public internet.

## Run with Docker Compose

```bash
cp .env.example .env
# Edit .env and replace any placeholder secrets
docker compose up --build
```

Review the Compose port mappings and webhook settings before hosting the service. The dashboard and webhook endpoint also have no built-in login. Compose binds their published ports to localhost by default; keep them there or put them behind an authenticated gateway before allowing network access. Set a unique webhook secret before accepting requests. Requests receive a 503 response until one is configured.

## Host the dashboard

The app can be deployed to a Python or Docker hosting service that supports Streamlit. Follow that provider's current setup and pricing instructions, set `dashboard.py` as the app entry point, and add only the environment variables the project uses. Free plans, instance sizes, availability, and pricing change, so check the provider directly before choosing a host.

A hosted dashboard is public unless you add access control at the hosting or network layer. Do not add exchange credentials: the included connector simulates orders and does not use exchange keys to trade.

## Troubleshooting

- Check local logs in the terminal running `start.py` or `docker compose logs -f`.
- If market data is unavailable, check the selected data source and its current service status. The dashboard may have no fresh prices to show.
- Stop the local process with Ctrl+C, or stop Compose with `docker compose down`.
- The dashboard uses virtual balances and simulated orders; displayed results are not evidence of future performance.
