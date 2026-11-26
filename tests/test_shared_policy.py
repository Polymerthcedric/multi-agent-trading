from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from agents.research_policy import MultiAgentResearchPolicy
from engine.policy import PolicyRiskConfig, PortfolioSnapshot


@dataclass
class _Prediction:
    direction: str = "Bullish"
    confidence: float = 0.9
    reasoning: dict = field(default_factory=dict)


@dataclass
class _Context:
    regime: str = "bullish"
    signal_alignment: str = "bullish"
    reasoning: dict = field(default_factory=dict)


@dataclass
class _Volatility:
    volatility_regime: str = "normal"
    risk_multiplier: float = 1.0
    atr: float = 2.0
    reasoning: dict = field(default_factory=dict)


def _policy(
    *,
    direction: str = "Bullish",
    alignment: str = "bullish",
    atr: float = 2.0,
    risk_multiplier: float = 1.0,
) -> MultiAgentResearchPolicy:
    policy = MultiAgentResearchPolicy(
        "TEST",
        PolicyRiskConfig(
            max_asset_allocation=0.20,
            max_risk_per_trade=0.015,
            stop_atr_multiple=2.0,
        ),
    )
    policy.predictive = SimpleNamespace(
        analyze_sync=lambda _: _Prediction(direction=direction),
    )
    policy.context = SimpleNamespace(
        analyze_sync=lambda _: _Context(
            regime=alignment,
            signal_alignment=alignment,
        ),
    )
    policy.volatility = SimpleNamespace(
        analyze_sync=lambda _: _Volatility(
            atr=atr,
            risk_multiplier=risk_multiplier,
        ),
    )
    policy.debate = SimpleNamespace(
        debate=lambda **_: SimpleNamespace(reasoning={"winner": "explanatory-only"}),
    )
    return policy


def _market_data(**overrides):
    return {
        "symbol": "TEST",
        "price": 100.0,
        "high": 102.0,
        "low": 98.0,
        "atr": 2.0,
        **overrides,
    }


def test_policy_sizes_from_stop_distance_and_limits_not_confidence_as_kelly():
    decision = _policy(atr=10.0).decide(_market_data(atr=10.0), PortfolioSnapshot())

    assert decision.action == "BUY"
    assert decision.allocation_pct == pytest.approx(0.075)
    assert decision.stop_loss == pytest.approx(80.0)
    assert decision.stop_distance == pytest.approx(20.0)
    assert decision.allocation_pct * decision.stop_distance / 100.0 == pytest.approx(0.015)


def test_policy_blocks_entries_on_risk_halt_but_allows_exits():
    bullish = _policy().decide(
        _market_data(),
        PortfolioSnapshot(daily_pnl_pct=-0.04),
    )
    bearish_exit = _policy(direction="Bearish", alignment="bearish").decide(
        _market_data(),
        PortfolioSnapshot(
            position_quantity=5.0,
            cash=50_000.0,
            daily_pnl_pct=-0.04,
            allow_new_positions=False,
        ),
    )

    assert bullish.action == "HOLD"
    assert bullish.reasons == ("daily_loss_limit",)
    assert bearish_exit.action == "SELL"
    assert bearish_exit.reasons == ("bearish_consensus_exit",)


def test_policy_fails_closed_on_stale_data_and_triggers_existing_stop():
    stale = _policy().decide(_market_data(is_stale=True), PortfolioSnapshot())
    stopped = _policy(direction="Neutral", alignment="neutral").decide(
        _market_data(low=94.0),
        PortfolioSnapshot(position_quantity=5.0, active_stop_loss=95.0),
    )

    assert stale.action == "HOLD"
    assert stale.reasons == ("stale_market_data",)
    assert stopped.action == "SELL"
    assert stopped.reasons == ("protective_stop_triggered",)


def test_policy_does_not_process_duplicate_or_out_of_order_snapshots():
    policy = _policy()

    first = policy.decide(_market_data(timestamp=100.0), PortfolioSnapshot())
    duplicate = policy.decide(_market_data(timestamp=100.0), PortfolioSnapshot())
    out_of_order = policy.decide(_market_data(timestamp=99.0), PortfolioSnapshot())
    newer = policy.decide(_market_data(timestamp=101.0), PortfolioSnapshot())

    assert first.action == "BUY"
    assert duplicate.reasons == ("duplicate_or_out_of_order_market_snapshot",)
    assert out_of_order.reasons == ("duplicate_or_out_of_order_market_snapshot",)
    assert newer.action == "BUY"


def test_each_symbol_policy_owns_independent_context_history():
    first = MultiAgentResearchPolicy("FIRST")
    second = MultiAgentResearchPolicy("SECOND")

    first.context.analyze_sync(_market_data(price=100.0))

    assert first.context is not second.context
    assert first.context._price_history == [100.0]
    assert second.context._price_history == []
