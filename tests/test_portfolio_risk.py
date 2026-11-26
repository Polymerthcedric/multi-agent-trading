"""Offline tests for cross-asset portfolio risk monitoring and its trading gate."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from agents.decision_log import DecisionRecord
from agents.portfolio_risk import PortfolioRiskMonitor
from engine.policy import PolicyDecision

try:
    import main as main_module
except ImportError as exc:  # optional engine dependencies may be absent
    main_module = None
    MAIN_IMPORT_ERROR = exc


CORRELATED_RETURNS = [0.003 if i % 2 == 0 else -0.002 for i in range(20)]


def test_correlated_pair_warning_and_concentration_denial():
    monitor = PortfolioRiskMonitor(portfolio_value=100_000.0)
    monitor.record_returns_batch("GOLD/USD", CORRELATED_RETURNS)
    monitor.record_returns_batch("SILVER/USD", CORRELATED_RETURNS)
    monitor.set_position("GOLD/USD", 25_000.0)
    monitor.set_position("SILVER/USD", 25_000.0)

    assessment = monitor.check_portfolio_risk()

    assert len(assessment.correlation_warnings) == 1
    assert "GOLD/USD" in assessment.correlation_warnings[0]
    assert "SILVER/USD" in assessment.correlation_warnings[0]
    assert assessment.concentrated_exposure is True
    assert "concentrated_correlated_exposure" in assessment.reasoning["deny_reasons"]
    assert assessment.allow_new_position is False


def test_total_exposure_denial():
    monitor = PortfolioRiskMonitor(portfolio_value=100_000.0)
    monitor.set_position("SPY", 90_000.0)

    assessment = monitor.check_portfolio_risk()

    assert assessment.total_exposure_pct == pytest.approx(0.9)
    assert "total_exposure_exceeded" in assessment.reasoning["deny_reasons"]
    assert assessment.allow_new_position is False


def test_var_on_deterministic_returns():
    monitor = PortfolioRiskMonitor(portfolio_value=1_000.0)
    # Sorted returns: [-0.04, -0.02, 0.001 x19]; n=21, so the 5th percentile
    # is the 2nd value (-0.02) and the 1st percentile is -0.036.
    returns = [-0.02, -0.04] + [0.001] * 19
    monitor.record_returns_batch("SPY", returns)
    monitor.set_position("SPY", 500.0)  # 50% weight

    assessment = monitor.check_portfolio_risk()

    assert assessment.portfolio_var_95 == pytest.approx(0.01)
    assert assessment.portfolio_var_99 == pytest.approx(0.018)


def test_non_finite_input_ignored():
    monitor = PortfolioRiskMonitor(portfolio_value=100_000.0)
    for bad in (float("nan"), float("inf"), -float("inf")):
        monitor.update_portfolio_value(bad)
        monitor.set_position("SPY", bad)
        monitor.record_return("SPY", bad)
    monitor.update_portfolio_value(-5_000.0)  # negative equity is invalid too
    monitor.record_returns_batch("SPY", [float("nan"), -float("inf")])

    assessment = monitor.check_portfolio_risk()
    assert assessment.total_exposure_pct == 0.0
    assert assessment.portfolio_var_95 == 0.0
    assert assessment.portfolio_var_99 == 0.0
    assert assessment.reasoning["portfolio_value"] == 100_000.0

    # Valid observations after the bad ones are still accepted.
    monitor.set_position("SPY", 1_000.0)
    monitor.record_returns_batch("SPY", [0.01, 0.02])
    recovered = monitor.check_portfolio_risk()
    assert math.isfinite(recovered.portfolio_var_95)
    assert math.isfinite(recovered.portfolio_var_99)
    assert recovered.total_exposure_pct == pytest.approx(0.01)


def test_small_long_is_allowed():
    monitor = PortfolioRiskMonitor(portfolio_value=100_000.0)
    monitor.set_position("AAPL", 1_000.0)

    assessment = monitor.check_portfolio_risk()

    assert assessment.allow_new_position is True
    assert assessment.reasoning["deny_reasons"] == []
    assert assessment.total_exposure_pct == pytest.approx(0.01)


def test_signed_positions_use_absolute_exposure_but_signed_var():
    monitor = PortfolioRiskMonitor(portfolio_value=100_000.0)
    monitor.record_returns_batch("GOLD/USD", CORRELATED_RETURNS)
    monitor.record_returns_batch("SILVER/USD", CORRELATED_RETURNS)
    monitor.set_position("GOLD/USD", 20_000.0)
    monitor.set_position("SILVER/USD", -5_000.0)  # short

    assessment = monitor.check_portfolio_risk()

    assert assessment.total_exposure_pct == pytest.approx(0.25)
    assert assessment.sector_exposures["commodities"] == pytest.approx(0.25)
    # Opposing signs hedge each other: no concentration denial.
    assert assessment.concentrated_exposure is False
    assert assessment.allow_new_position is True


def test_close_returns_helper_uses_history_and_snapshot_only_once():
    if main_module is None:
        pytest.skip(f"main.py imports unavailable: {MAIN_IMPORT_ERROR}")

    helper = main_module.TradingOrchestrator._close_returns

    returns, last = helper([100.0, 101.0, 101.0, 102.0])
    assert returns == pytest.approx([0.01, 1.0 / 101.0])
    assert last == 102.0

    # Replaying the same rolling history must not duplicate old returns.
    replay, _ = helper([100.0, 101.0, 101.0, 102.0], previous_close=last)
    assert replay == []

    # Only the current snapshot close is available: derive one return.
    snapshot_return, last = helper([103.0], previous_close=last)
    assert snapshot_return == pytest.approx([1.0 / 102.0])
    assert last == 103.0

    # Bad prices are ignored entirely.
    bad_returns, last = helper(["bad", float("nan"), 0.0, -1.0, 100.0])
    assert bad_returns == []
    assert last == 100.0


class _FakeMonitor:
    def __init__(self, assessment=None, error: Exception | None = None) -> None:
        self.assessment = assessment
        self.error = error
        self.calls = 0

    def check_portfolio_risk(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.assessment


class _FakeDecisionLog:
    def __init__(self) -> None:
        self.records = [
            DecisionRecord(symbol="GOLD/USD", action="BUY", execution_status="pending"),
        ]
        self.updates: list[tuple[str, str]] = []

    def update_execution(self, symbol: str, status: str, fill_price: float = 0.0, quantity: float = 0.0) -> None:
        self.updates.append((symbol, status))
        for record in reversed(self.records):
            if record.symbol == symbol and record.execution_status == "pending":
                record.execution_status = status
                break


def _orchestrator_with_fake_monitor(monitor) -> tuple[object, _FakeDecisionLog]:
    orch = object.__new__(main_module.TradingOrchestrator)
    orch.portfolio_risk = monitor
    decision_log = _FakeDecisionLog()
    orch.decision_log = decision_log
    return orch, decision_log


def test_new_long_gate_rejects_denied_position_and_logs_reasons(caplog):
    if main_module is None:
        pytest.skip(f"main.py imports unavailable: {MAIN_IMPORT_ERROR}")

    assessment = SimpleNamespace(
        allow_new_position=False,
        reasoning={"deny_reasons": ["concentrated_correlated_exposure"]},
        correlation_warnings=["GOLD/USD and SILVER/USD correlation 0.95"],
    )
    monitor = _FakeMonitor(assessment)
    orch, decision_log = _orchestrator_with_fake_monitor(monitor)
    balance = SimpleNamespace(positions={})

    assert orch._reject_new_long_if_risky("GOLD/USD", balance) is True
    assert monitor.calls == 1
    assert decision_log.updates == [("GOLD/USD", "rejected")]
    record = decision_log.records[0]
    assert record.execution_status == "rejected"
    assert "concentrated_correlated_exposure" in record.reasoning_chain[-1]
    assert record.risk_check["portfolio_risk"]["deny_reasons"] == ["concentrated_correlated_exposure"]
    assert "concentrated_correlated_exposure" in caplog.text


def test_new_long_gate_checks_additions_and_fails_closed(caplog):
    if main_module is None:
        pytest.skip(f"main.py imports unavailable: {MAIN_IMPORT_ERROR}")

    monitor = _FakeMonitor(SimpleNamespace(
        allow_new_position=False,
        reasoning={"deny_reasons": ["total_exposure_exceeded"]},
        correlation_warnings=[],
    ))
    orch, decision_log = _orchestrator_with_fake_monitor(monitor)
    balance = SimpleNamespace(positions={"GOLD/USD": 1.5})

    # An addition to an existing long also increases exposure and is checked.
    assert orch._reject_new_long_if_risky("GOLD/USD", balance) is True
    assert monitor.calls == 1
    assert decision_log.updates == [("GOLD/USD", "rejected")]

    # A monitor failure blocks new risk instead of failing open.
    orch.portfolio_risk = _FakeMonitor(error=RuntimeError("monitor bug"))
    assert orch._reject_new_long_if_risky("GOLD/USD", balance) is True
    assert "monitor bug" in caplog.text
    assert decision_log.updates[-1] == ("GOLD/USD", "rejected")


def test_sell_execution_never_calls_portfolio_gate():
    if main_module is None:
        pytest.skip(f"main.py imports unavailable: {MAIN_IMPORT_ERROR}")

    class _Connector:
        async def get_balance(self):
            return SimpleNamespace(total_equity=100_000.0, positions={"GOLD/USD": 1.0})

    class _Broker:
        def __init__(self):
            self.actions = []

        async def execute_action(self, **kwargs):
            self.actions.append(kwargs["action"])
            return SimpleNamespace(
                status="filled", avg_fill_price=100.0,
                filled_quantity=1.0, commission=0.0,
            )

    class _Environment:
        portfolio_value = 100_000.0
        cash = 100_000.0
        tc_pct = 0.001
        slippage_pct = 0.0005

        def apply_trade(self, action, fill_price, quantity):
            return 0.0

    class _Ledger:
        def record(self, entry):
            pass

    class _TradeLedger:
        def close_trade(self, symbol, price, *, exit_fee=0.0):
            return None

    monitor = _FakeMonitor(SimpleNamespace(
        allow_new_position=False,
        reasoning={"deny_reasons": ["total_exposure_exceeded"]},
        correlation_warnings=[],
    ))
    broker = _Broker()
    orch = object.__new__(main_module.TradingOrchestrator)
    orch.portfolio_risk = monitor
    orch.connector = _Connector()
    orch.broker = broker
    orch.decision_log = _FakeDecisionLog()
    orch.environments = {"GOLD/USD": _Environment()}
    orch.runtime_ledger = _Ledger()
    orch.trade_ledger = _TradeLedger()
    orch._trade_count = 0
    orch._daily_trade_count = 0
    orch._risk_day_key = ""
    orch._risk_week_key = ""
    orch._equity_peak = 100_000.0
    orch._day_start_equity = 100_000.0
    orch._week_start_equity = 100_000.0
    orch._active_stops = {}
    sync_calls = []

    async def _fake_sync(*args, **kwargs):
        sync_calls.append((args, kwargs))

    orch._sync_portfolio_risk = _fake_sync
    asyncio.run(orch._execute_trade(
        symbol="GOLD/USD",
        decision=PolicyDecision(
            action="SELL",
            allocation_pct=1.0,
            agent_outputs={
                "prediction": {"confidence": 0.8},
                "context": {},
                "volatility": {"atr": 1.0, "z_score": 0.0},
            },
        ),
        market_data={"price": 100.0},
    ))

    assert broker.actions == [2]
    assert monitor.calls == 0
    assert ("GOLD/USD", "rejected") not in orch.decision_log.updates
