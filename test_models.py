from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import asdict

from config.settings import Settings
from agents.predictive import PredictiveAgent
from agents.context import ContextAgent
from agents.volatility import VolatilityAgent
from agents.risk_manager import RiskManager

logger = logging.getLogger(__name__)


async def test_with_live_data() -> None:
    from connectors.tv_datafeed import TradingViewFeed
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    feed = TradingViewFeed(symbols=("BTC/USD", "ETH/USD", "SOL/USD"))
    if not feed.is_available():
        logger.error("tradingview_ta not installed. Run: pip install tradingview-ta")
        sys.exit(1)

    predictive = PredictiveAgent()
    context = ContextAgent()
    volatility_map = {sym: VolatilityAgent() for sym in settings.symbols}
    risk = RiskManager()

    for symbol in settings.symbols:
        logger.info("=" * 60)
        logger.info("Testing %s with LIVE TradingView data", symbol)
        logger.info("=" * 60)

        snap = await feed.get_snapshot(symbol)
        market_data = feed.to_market_data(symbol, snap)
        logger.info(
            "Data: price=%.2f rsi=%.1f sma20=%.2f ema20=%.2f rec=%s",
            market_data["price"], market_data["rsi"],
            market_data["sma"], market_data["ema"],
            market_data["recommendation"],
        )

        prediction = await predictive.analyze(market_data)
        pr = asdict(prediction)
        logger.info("Predictive: direction=%s confidence=%.4f", pr["direction"], pr["confidence"])

        context_result = await context.analyze(market_data)
        cr = asdict(context_result)
        logger.info("Context: regime=%s alignment=%s", cr["regime"], cr["signal_alignment"])

        vol_agent = volatility_map[symbol]
        volatility_result = await vol_agent.analyze(market_data)
        vr = asdict(volatility_result)
        logger.info("Volatility: atr=%.4f regime=%s z_score=%.4f mult=%.4f",
                     vr["atr"], vr["volatility_regime"], vr["z_score"], vr["risk_multiplier"])

        decision = await risk.evaluate(
            prediction=pr,
            context=cr,
            volatility=vr,
            market_data=market_data,
        )
        logger.info("Risk Decision: action=%s alloc=%.2f%% stop=%.2f",
                     decision.action, decision.allocation_pct * 100, decision.stop_loss)

        logger.info("")

    logger.info("All live tests complete.")


async def test_with_simulation() -> None:
    from connectors.platform import PaperTradingConnector
    from execution.broker import Broker, ACTION_LABEL_TO_INT
    from engine.environment import TradingEnvironment
    from engine.ledger import RuntimeLedger
    from memory.feedback_loop import TradeLedger, TradeRecord, SelfLearningCritic
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    connector = PaperTradingConnector(initial_balance=10000.0)
    broker = Broker(connector)
    env = TradingEnvironment(initial_balance=10000.0)
    runtime_ledger = RuntimeLedger()
    trade_ledger = TradeLedger()
    critic = SelfLearningCritic(cadence=5)

    predictive = PredictiveAgent()
    context = ContextAgent()
    volatility_map = {sym: VolatilityAgent() for sym in settings.symbols}
    risk = RiskManager(initial_portfolio_value=10000.0)
    trade_count = 0

    logger.info("Running 10-step simulation with simulated data...")
    for step in range(10):
        for symbol in settings.symbols:
            market_data = await connector.get_market_data(symbol)

            prediction = await predictive.analyze(market_data)
            context_result = await context.analyze(market_data)
            vol_agent = volatility_map[symbol]
            volatility_result = await vol_agent.analyze(market_data)

            decision = await risk.evaluate(
                prediction=asdict(prediction),
                context=asdict(context_result),
                volatility=asdict(volatility_result),
                market_data=market_data,
            )

            if decision.action != "HOLD":
                trade_count += 1
                action_int = ACTION_LABEL_TO_INT.get(decision.action, 0)
                pr = asdict(prediction)
                logger.info(
                    "TRADE %d | %s %s alloc=%.2f%% conf=%.4f",
                    trade_count, symbol, decision.action,
                    decision.allocation_pct * 100, pr["confidence"],
                )

    logger.info("Simulation complete — %d potential trades detected", trade_count)
    runtime_ledger.save()


async def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        await test_with_live_data()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sim":
        await test_with_simulation()
    else:
        print("Usage: python test_models.py [--live | --sim]")
        print("  --live  Test all agents with live TradingView data")
        print("  --sim   Run a simulation with random data")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
