from __future__ import annotations

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connectors.webhooks.receiver import app, register_trading_callback
from config.settings import Settings

logger = logging.getLogger(__name__)


async def process_tv_signal(signal):
    logger.info(
        "External signal received: %s %s @ %.2f; observation only, no order submitted",
        signal.action,
        signal.symbol,
        signal.price,
    )


register_trading_callback(process_tv_signal)


def main():
    import uvicorn
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    logger.info("=" * 60)
    logger.info("TradingView Webhook Bridge")
    logger.info("Endpoint: http://%s:%d/webhook", HOST, PORT)
    logger.info("Monitor:  http://%s:%d/", HOST, PORT)
    logger.info("=" * 60)

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


HOST = os.getenv("WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.getenv("WEBHOOK_PORT", "8000"))

if __name__ == "__main__":
    main()
