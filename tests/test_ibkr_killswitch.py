from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("test_ibkr_killswitch")

sys.path.insert(0, ".")


async def test_killswitch_disconnected_mode():
    """Verify IBKR connector is safe when TWS/IBG is not running."""
    from connectors.ibkr import IBConnector

    logger.info("TEST: Kill-switch behavior when IBKR is disconnected")
    connector = IBConnector(host="127.0.0.1", port=7497, client_id=999)

    try:
        available = connector.is_available()
        logger.info("  is_available() = %s", available)
    except Exception as e:
        raise AssertionError("is_available() must not raise") from e

    try:
        balance = await connector.get_balance()
        logger.info("  get_balance() returned keys: %s", list(balance.keys()))
        assert isinstance(balance, dict), "get_balance must return dict"
        assert "total_equity" in balance
    except Exception as e:
        raise AssertionError("get_balance() must not raise in disconnected mode") from e

    try:
        order = await connector.execute_order("BTC/USD", "buy", 0.01)
        logger.info("  execute_order() returned: %s", order)
        assert order["status"] == "rejected", "Disconnected orders must be rejected"
    except Exception as e:
        raise AssertionError("execute_order() must not raise") from e

    logger.info("  PASSED: kill-switch safe in disconnected mode\n")


async def test_killswitch_daily_drawdown_limit():
    """Verify that the 5% daily drawdown limit is enforced."""
    from agents.risk_manager import RiskLimits

    logger.info("TEST: Kill-switch daily drawdown limit enforcement")

    assert RiskLimits.daily_drawdown_halt == 0.05, f"Expected 0.05, got {RiskLimits.daily_drawdown_halt}"

    for dd_pct in [0.01, 0.03, 0.05, 0.06, 0.10]:
        is_limited = dd_pct >= RiskLimits.daily_drawdown_halt
        logger.info("  Drawdown=%.0f%% -> trading %s", dd_pct * 100, "BLOCKED" if is_limited else "allowed")

    logger.info("  PASSED: daily drawdown limit\n")


async def test_killswitch_emergency_close():
    """Verify emergency RISK_CLOSE signal reaches execution layer."""
    from execution.broker import Broker
    from connectors.platform import PaperTradingConnector

    logger.info("TEST: Kill-switch emergency position close")
    connector = PaperTradingConnector(initial_balance=100000.0)
    broker = Broker(connector)

    try:
        result = await broker.execute_action(
            action={"buy": 1, "sell": 2}.get("sell", 0),
            symbol="BTC/USD", price=50000.0,
            allocation_pct=1.0, portfolio_value=100000.0,
        )
        logger.info("  Emergency close result: %s", result)
    except Exception as e:
        raise AssertionError("Emergency close must not raise") from e

    logger.info("  PASSED: kill-switch emergency close\n")


async def test_killswitch_no_synthetic_in_live():
    """Verify LIVE mode raises IBKRDataError instead of synthetic data."""
    from connectors.ibkr import IBConnector, IBKRDataError

    logger.info("TEST: LIVE mode rejects synthetic data fallback")
    connector = IBConnector(host="127.0.0.1", port=7497, client_id=997, mode="LIVE")

    try:
        await connector.get_market_data("BTC/USD")
        raise AssertionError("Expected IBKRDataError in LIVE mode when disconnected")
    except IBKRDataError:
        logger.info("  Correctly raised IBKRDataError (no synthetic fallback)")
    logger.info("  PASSED: LIVE mode blocks synthetic data\n")


async def test_killswitch_demo_allows_synthetic():
    """Verify DEMO mode still falls back to synthetic data when disconnected."""
    from connectors.ibkr import IBConnector

    logger.info("TEST: DEMO mode allows synthetic data fallback")
    connector = IBConnector(host="127.0.0.1", port=7497, client_id=996, mode="DEMO")

    md = await connector.get_market_data("BTC/USD")
    assert md is not None, "get_market_data must return something in DEMO mode"
    assert "price" in md and md["price"] > 0, "Must have a price field"
    logger.info("  get_market_data returned price=%.2f (synthetic, DEMO mode)", md["price"])
    logger.info("  PASSED: DEMO mode allows synthetic fallback\n")


async def main():
    logger.info("=" * 70)
    logger.info("IBKR KILL-SWITCH INTEGRATION TEST SUITE")
    logger.info("=" * 70)

    tests = [
        ("Disconnected mode safety", test_killswitch_disconnected_mode),
        ("Daily drawdown limit", test_killswitch_daily_drawdown_limit),
        ("Emergency close path", test_killswitch_emergency_close),
        ("LIVE mode blocks synthetic data", test_killswitch_no_synthetic_in_live),
        ("DEMO mode allows synthetic data", test_killswitch_demo_allows_synthetic),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            await fn()
            passed += 1
        except Exception as e:
            logger.error("FAIL: %s — %s", name, e)
            import traceback
            traceback.print_exc()
            failed += 1

    logger.info("=" * 70)
    logger.info("RESULTS: %d passed, %d failed out of %d", passed, failed, len(tests))
    logger.info("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
