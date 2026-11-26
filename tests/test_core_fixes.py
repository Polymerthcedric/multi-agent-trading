"""Regression tests for verified trading-core fixes.

These tests use asyncio.run explicitly so they do not depend on pytest-asyncio
configuration. No network calls are made.
"""
from __future__ import annotations

import asyncio
import math
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, ".")

from agents.debate import BullBearDebate
from agents.risk_manager import RiskManager
from connectors.platform import MIN_QUANTITY, PaperTradingConnector
from connectors.tv_datafeed import DataUnavailableError
from execution.broker import Broker
from memory.feedback_loop import TradeLedger, TradeRecord


class FixedFeed:
    """Deterministic price feed for paper-connector tests."""

    def __init__(self, price: float) -> None:
        self.price = price

    async def get_snapshot(self, symbol: str):
        return SimpleNamespace(price=self.price)

    def to_market_data(self, symbol: str, snap) -> dict:
        return {
            "symbol": symbol,
            "price": snap.price,
            "sma": snap.price,
            "ema": snap.price,
            "rsi": 50.0,
            "high": snap.price,
            "low": snap.price,
        }


def test_total_drawdown_triggers_kill_switch():
    risk = RiskManager(initial_portfolio_value=100_000.0)
    risk.update_portfolio_value(92_000.0)
    risk.update_daily_pnl(0.0)
    assert risk._current_portfolio_value == 92_000.0
    assert risk._kill_switch is True


def test_small_daily_loss_does_not_trigger_kill_switch():
    risk = RiskManager(initial_portfolio_value=100_000.0)
    risk.update_portfolio_value(100_000.0)
    risk.update_daily_pnl(-1_000.0)
    assert risk._kill_switch is False


def test_large_daily_loss_still_triggers_kill_switch():
    risk = RiskManager(initial_portfolio_value=100_000.0)
    risk.update_daily_pnl(-8_000.0)
    assert risk._kill_switch is True


def test_bear_case_flags_price_below_sma():
    argument = BullBearDebate()._build_bear_case(
        {}, {}, {}, None, {"price": 100.0, "sma": 110.0, "rsi": 50.0},
    )
    assert any("below SMA" in point for point in argument.points)
    assert argument.strength >= 0.1


def test_bear_case_ignores_missing_sma():
    argument = BullBearDebate()._build_bear_case(
        {}, {}, {}, None, {"price": 100.0, "sma": 0.0, "rsi": 50.0},
    )
    assert not any("SMA" in point for point in argument.points)


def test_bull_case_flags_price_above_sma():
    argument = BullBearDebate()._build_bull_case(
        {}, {}, {}, None, {"price": 110.0, "sma": 100.0, "rsi": 50.0},
    )
    assert any("above SMA" in point for point in argument.points)


def test_paper_rejects_tiny_quantity():
    connector = PaperTradingConnector(tv_feed=FixedFeed(100.0))
    result = asyncio.run(connector.execute_order("BTC/USD", "buy", MIN_QUANTITY / 10))
    assert result.status == "rejected"
    assert result.filled_quantity == 0.0
    assert result.quantity == MIN_QUANTITY / 10


def test_paper_rejects_unknown_side():
    connector = PaperTradingConnector(tv_feed=FixedFeed(100.0))
    result = asyncio.run(connector.execute_order("BTC/USD", "hold", 1.0))
    assert result.status == "rejected"
    assert "unsupported side" in (result.error or "")


def test_paper_rejects_nonfinite_quantity():
    connector = PaperTradingConnector(tv_feed=FixedFeed(100.0))
    for quantity in (float("nan"), float("inf"), "1.0"):
        result = asyncio.run(connector.execute_order("BTC/USD", "buy", quantity))
        assert result.status == "rejected"
        assert result.filled_quantity == 0.0


def test_paper_rejects_invalid_price():
    connector = PaperTradingConnector(tv_feed=FixedFeed(0.0))
    result = asyncio.run(connector.execute_order("BTC/USD", "buy", 1.0))
    assert result.status == "rejected"
    assert "Market-data price is invalid" in (result.error or "")


def test_paper_market_data_without_a_feed_fails_closed():
    connector = PaperTradingConnector()
    with pytest.raises(DataUnavailableError, match="No market-data feed"):
        asyncio.run(connector.get_market_data("AAPL"))


def test_paper_market_data_rejects_stale_feed():
    class StaleFeed(FixedFeed):
        async def get_snapshot(self, symbol: str):
            return SimpleNamespace(price=self.price, is_stale=True)

    connector = PaperTradingConnector(tv_feed=StaleFeed(100.0))
    with pytest.raises(DataUnavailableError, match="Fresh market data unavailable"):
        asyncio.run(connector.get_market_data("AAPL"))


def test_paper_buy_is_limited_by_available_cash():
    connector = PaperTradingConnector(initial_balance=100.0, tv_feed=FixedFeed(100.0))
    result = asyncio.run(connector.execute_order("BTC/USD", "buy", 2.0))
    assert result.status == "filled"
    assert math.isclose(result.filled_quantity, 1.0, rel_tol=1e-9)
    assert result.quantity == 2.0
    balance = asyncio.run(connector.get_balance())
    assert math.isclose(balance.cash, 0.0, abs_tol=1e-9)
    assert math.isclose(balance.positions["BTC/USD"], 1.0, rel_tol=1e-9)


def test_paper_sell_cannot_exceed_position():
    connector = PaperTradingConnector(initial_balance=1_000.0, tv_feed=FixedFeed(100.0))
    asyncio.run(connector.execute_order("BTC/USD", "buy", 0.5))
    result = asyncio.run(connector.execute_order("BTC/USD", "sell", 1.0))
    assert result.status == "filled"
    assert math.isclose(result.filled_quantity, 0.5, rel_tol=1e-9)
    second = asyncio.run(connector.execute_order("BTC/USD", "sell", 0.1))
    assert second.status == "rejected"
    positions = asyncio.run(connector.get_positions())
    assert "BTC/USD" not in positions


def test_broker_quantity_is_not_capped_at_one_unit():
    connector = PaperTradingConnector(initial_balance=100_000.0, tv_feed=FixedFeed(100.0))
    broker = Broker(connector)
    result = asyncio.run(broker.execute_action(
        action=1, symbol="SOL/USD", price=100.0,
        allocation_pct=0.1, portfolio_value=100_000.0,
    ))
    assert result is not None and result.status == "filled"
    assert result.filled_quantity > 1.0
    assert 90.0 <= result.filled_quantity <= 110.0


def test_broker_max_order_size_caps_notional_not_units():
    connector = PaperTradingConnector(initial_balance=100_000.0, tv_feed=FixedFeed(100.0))
    from execution.broker import ExecutionConstraints

    broker = Broker(connector, ExecutionConstraints(max_order_size=0.01))
    result = asyncio.run(broker.execute_action(
        action=1, symbol="SOL/USD", price=100.0,
        allocation_pct=0.5, portfolio_value=100_000.0,
    ))
    assert result is not None and result.status == "filled"
    assert math.isclose(result.filled_quantity, 10.0, rel_tol=0.02)


def test_broker_applies_its_cost_model_to_the_actual_paper_fill():
    connector = PaperTradingConnector(initial_balance=100_000.0, tv_feed=FixedFeed(100.0))
    broker = Broker(connector)
    estimated = broker.estimate_fill_price("buy", 100.0)

    result = asyncio.run(broker.execute_action(
        action=1,
        symbol="AAPL",
        price=100.0,
        allocation_pct=0.1,
        portfolio_value=100_000.0,
    ))

    assert result is not None and result.status == "filled"
    assert result.avg_fill_price == estimated.fill_price
    assert result.commission > 0
    balance = asyncio.run(connector.get_balance())
    assert balance.cash == pytest.approx(
        100_000.0 - result.filled_quantity * result.avg_fill_price - result.commission,
    )


def test_trade_ledger_pnl_includes_entry_and_exit_commissions(tmp_path):
    ledger = TradeLedger(str(tmp_path / "trades.json"))
    trade = TradeRecord(
        symbol="AAPL",
        direction="BUY",
        entry_price=100.0,
        quantity=2.0,
        entry_fee=1.0,
    )
    ledger.record_trade(trade)

    closed = ledger.close_trade("AAPL", 110.0, exit_fee=1.0)

    assert closed is trade
    assert trade.pnl == pytest.approx(18.0)
    assert trade.pnl_pct == pytest.approx(18.0 / 201.0)
