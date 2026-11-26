from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.research_policy import MultiAgentResearchPolicy  # noqa: E402
from agents.risk_manager import consensus_action  # noqa: E402
from engine.walk_forward import (  # noqa: E402
    PolicyWalkForwardValidator,
    WalkForwardConfig,
)


def _trend_bars(n: int) -> List[Dict[str, Any]]:
    bars: List[Dict[str, Any]] = []
    price = 100.0
    for index in range(n):
        open_price = price
        price *= 1.002 + 0.003 * math.sin(index * 0.23)
        bars.append({
            "timestamp": float(1_700_000_000 + index * 3600),
            "open": open_price,
            "high": max(open_price, price) * 1.003,
            "low": min(open_price, price) * 0.997,
            "close": price,
            "volume": float(1000 + index),
        })
    return bars


def test_consensus_action_is_the_shared_confidence_and_alignment_gate():
    assert consensus_action("Bullish", "bullish", 0.8, 0.55) == "BUY"
    assert consensus_action("bearish", "bearish", 0.8, 0.55) == "SELL"
    assert consensus_action("Bullish", "neutral", 0.8, 0.55) == "HOLD"
    assert consensus_action("Bullish", "bullish", 0.5, 0.55) == "HOLD"
    assert consensus_action("Bullish", "bullish", float("nan"), 0.55) == "HOLD"


def test_multi_agent_walk_forward_is_deterministic_and_benchmarked():
    bars = _trend_bars(150)
    config = WalkForwardConfig(
        warmup=20,
        train_window=40,
        test_window=10,
        step=10,
        annual_factor=252,
    )
    validator = PolicyWalkForwardValidator(
        lambda: MultiAgentResearchPolicy("SYN"),
        config,
        strategy=MultiAgentResearchPolicy.name,
    )

    first = validator.validate(bars, symbol="SYN", data_source="fixture").as_dict()
    second = validator.validate(bars, symbol="SYN", data_source="fixture").as_dict()

    assert first == second
    assert first["strategy"] == MultiAgentResearchPolicy.name
    assert first["fold_count"] > 0
    assert first["benchmarks"]["buy_and_hold"]["total_trades"] > 0
    assert first["benchmarks"]["cash"]["total_trades"] == 0
    assert first["tuning"] == "none; the policy remains fixed across all folds"


def test_out_of_sample_prices_cannot_change_prior_in_sample_results():
    bars = _trend_bars(150)
    config = WalkForwardConfig(
        warmup=20,
        train_window=40,
        test_window=10,
        step=10,
        annual_factor=252,
    )
    validator = PolicyWalkForwardValidator(
        lambda: MultiAgentResearchPolicy("SYN"),
        config,
        strategy=MultiAgentResearchPolicy.name,
    )
    original = validator.validate(bars, symbol="SYN").as_dict()
    mutated_bars = [dict(bar) for bar in bars]
    first_test = original["folds"][0]
    start, end = first_test["test_start"], first_test["test_end"]
    for index in range(start, end):
        mutated_bars[index]["close"] *= 1.5
        mutated_bars[index]["high"] *= 1.5
        mutated_bars[index]["low"] *= 1.5

    changed = validator.validate(mutated_bars, symbol="SYN").as_dict()

    assert changed["folds"][0]["in_sample"] == first_test["in_sample"]
    assert (
        changed["folds"][0]["benchmarks"]["buy_and_hold"]["net_pnl"]
        != first_test["benchmarks"]["buy_and_hold"]["net_pnl"]
    )
