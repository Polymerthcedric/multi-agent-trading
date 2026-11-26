"""Manual agent smoke checks.

Run with ``python test_models.py --sim`` or ``--live``. The live mode calls an
external data provider, so pytest does not collect these functions as tests.
"""
from __future__ import annotations

import asyncio
import logging
import math
import sys

from config.settings import Settings
from agents.research_policy import MultiAgentResearchPolicy
from engine.policy import PortfolioSnapshot

logger = logging.getLogger(__name__)


async def run_live_check() -> None:
    from connectors.tv_datafeed import TradingViewFeed
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    feed = TradingViewFeed(symbols=settings.symbols)
    if not feed.is_available():
        logger.error("No supported market-data provider is installed.")
        sys.exit(1)

    policies = {
        symbol: MultiAgentResearchPolicy(symbol) for symbol in settings.symbols
    }

    for symbol in settings.symbols:
        logger.info("=" * 60)
        logger.info("Testing %s with public market data", symbol)
        logger.info("=" * 60)

        snap = await feed.get_snapshot(symbol)
        market_data = feed.to_market_data(symbol, snap)
        if market_data.get("is_stale"):
            logger.warning("Skipping %s: feed returned stale data", symbol)
            continue
        logger.info(
            "Data: price=%.2f rsi=%.1f sma20=%.2f ema20=%.2f rec=%s",
            market_data["price"], market_data["rsi"],
            market_data["sma"], market_data["ema"],
            market_data["recommendation"],
        )

        decision = policies[symbol].decide(market_data, PortfolioSnapshot())
        logger.info(
            "Policy preview: signal=%s action=%s allocation=%.2f%% stop=%.2f reasons=%s",
            decision.signal,
            decision.action,
            decision.allocation_pct * 100,
            decision.stop_loss,
            ",".join(decision.reasons),
        )

        logger.info("")

    logger.info("All market-data policy previews complete; no orders were submitted.")


async def run_simulation_check() -> None:
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    policies = {
        symbol: MultiAgentResearchPolicy(symbol) for symbol in settings.symbols
    }

    logger.info("Running deterministic synthetic policy smoke check; no orders are possible.")
    for step in range(10):
        for symbol in settings.symbols:
            price = 100.0 + step * 0.5 + math.sin(step * 0.4)
            market_data = {
                "symbol": symbol,
                "price": price,
                "sma": price * 0.995,
                "ema": price * 0.997,
                "rsi": 55.0,
                "high": price * 1.01,
                "low": price * 0.99,
                "historical_support": price * 0.98,
                "historical_resistance": price * 1.02,
                "atr": price * 0.01,
                "momentum": 0.5,
                "macd": 0.1,
                "macd_signal": 0.0,
                "volume": 1000.0,
            }
            decision = policies[symbol].decide(market_data, PortfolioSnapshot())
            if decision.action != "HOLD":
                logger.info(
                    "PREVIEW step=%d | %s signal=%s action=%s allocation=%.2f%%",
                    step, symbol, decision.signal, decision.action,
                    decision.allocation_pct * 100,
                )

    logger.info("Synthetic policy smoke check complete; its output is not performance evidence.")


async def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        await run_live_check()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sim":
        await run_simulation_check()
    else:
        print("Usage: python test_models.py [--live | --sim]")
        print("  --live  Test all agents with live TradingView data")
        print("  --sim   Run a simulation with random data")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
