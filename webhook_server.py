from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connectors.webhooks.receiver import app, signal_store, register_trading_callback
from config.settings import Settings

logger = logging.getLogger(__name__)


async def process_tv_signal(signal):
    logger.info("Processing TV signal: %s %s @ %.2f", signal.action, signal.symbol, signal.price)

    from agents.predictive import PredictiveAgent
    from agents.context import ContextAgent
    from agents.volatility import VolatilityAgent
    from agents.risk_manager import RiskManager
    from dataclasses import asdict

    predictive = PredictiveAgent()
    context = ContextAgent()
    volatility = VolatilityAgent()
    risk = RiskManager()

    market_data = {
        "symbol": signal.symbol,
        "price": signal.price,
        "sma": signal.price,
        "ema": signal.price,
        "rsi": 50.0,
        "high": signal.price * 1.01,
        "low": signal.price * 0.99,
        "historical_support": signal.stop_loss if signal.stop_loss > 0 else signal.price * 0.97,
        "historical_resistance": signal.take_profit if signal.take_profit > 0 else signal.price * 1.03,
        "volume": signal.volume,
        "adx": 0.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "bb_upper": signal.price * 1.05,
        "bb_lower": signal.price * 0.95,
        "atr": signal.price * 0.01,
        "momentum": 0.0,
    }

    prediction = await predictive.analyze(market_data)
    context_result = await context.analyze(market_data)
    volatility_result = await volatility.analyze(market_data)

    decision = await risk.evaluate(
        prediction=asdict(prediction),
        context=asdict(context_result),
        volatility=asdict(volatility_result),
        market_data=market_data,
    )

    logger.info(
        "Agent analysis for %s: pred=%s/%.2f ctx=%s vol=%s -> risk=%s",
        signal.symbol, prediction.direction, prediction.confidence,
        context_result.signal_alignment, volatility_result.volatility_regime,
        decision.action,
    )

    if decision.action != "HOLD":
        logger.info("EXECUTE: %s %s (alloc=%.2f%%)", decision.action, signal.symbol, decision.allocation_pct * 100)


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


HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.getenv("WEBHOOK_PORT", "8000"))

if __name__ == "__main__":
    main()
