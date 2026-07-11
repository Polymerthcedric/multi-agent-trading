FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl tini && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/config /app/static

EXPOSE 8501 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["tini", "--"]

CMD ["sh", "-c", "\
    echo 'Starting TradingView Webhook Bridge...' && \
    python webhook_server.py & \
    echo 'Starting Dashboard...' && \
    streamlit run dashboard.py \
        --server.headless true \
        --server.port 8501 \
        --server.address 0.0.0.0 \
        --browser.serverAddress 0.0.0.0 \
        --server.enableCORS false \
        --server.enableXsrfProtection false \
"]
