"""Deterministic, offline tests for the walk-forward validator.

All bars are generated with closed-form formulas: no randomness, no network,
no wall clock.  The synthetic series are only test fixtures, not evidence of
real-market performance.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.evaluator import StateEvaluator  # noqa: E402
from engine.walk_forward import (  # noqa: E402
    DEFAULT_EVALUATOR_GRID,
    WalkForwardConfig,
    WalkForwardValidator,
    build_folds,
    run_backtest,
)


def test_legacy_evaluator_grid_does_not_vary_an_inactive_parameter():
    risk_settings = {params.risk_aversion for params in DEFAULT_EVALUATOR_GRID}
    decision_settings = {
        (params.drawdown_penalty, params.position_conviction_bonus)
        for params in DEFAULT_EVALUATOR_GRID
    }

    assert risk_settings == {3.0}
    assert len(decision_settings) == len(DEFAULT_EVALUATOR_GRID)


def _trend_bars(n: int, *, trend: float = 0.002, amp: float = 0.005, base: float = 100.0) -> List[Dict[str, Any]]:
    """Smooth uptrend with a fixed sine wave: deterministic and tradable."""
    bars: List[Dict[str, Any]] = []
    price = base
    for i in range(n):
        open_price = price
        ret = trend + amp * math.sin(2.0 * math.pi * i / 25.0)
        price *= 1.0 + ret
        bars.append({
            "timestamp": float(1_700_000_000 + i * 3600),
            "open": open_price,
            "high": max(open_price, price) * (1.002 + abs(ret)),
            "low": min(open_price, price) * (0.998 - abs(ret)),
            "close": price,
            "volume": float(1000 + i * 7),
        })
    return bars


def _regime_bars(n: int, *, up: float = 0.002, down: float = -0.006, base: float = 100.0) -> List[Dict[str, Any]]:
    """Uptrend then downtrend: creates drawdowns that make the grid discriminate."""
    bars: List[Dict[str, Any]] = []
    price = base
    for i in range(n):
        open_price = price
        ret = (up if i < n // 2 else down) + 0.003 * math.sin(2.0 * math.pi * i / 30.0)
        price *= 1.0 + ret
        bars.append({
            "timestamp": float(1_700_000_000 + i * 3600),
            "open": open_price,
            "high": max(open_price, price) * (1.002 + abs(ret)),
            "low": min(open_price, price) * (0.998 - abs(ret)),
            "close": price,
            "volume": float(1000 + i * 7),
        })
    return bars


def test_fold_boundaries_are_chronological_and_test_windows_non_overlapping():
    config = WalkForwardConfig(train_window=40, test_window=10, step=10, warmup=20)
    bars = _trend_bars(130)
    folds = build_folds(len(bars), config)
    assert len(folds) >= 3

    for expected_index, window in enumerate(folds):
        assert window.fold == expected_index
        assert window.train_start >= config.warmup
        assert window.train_end - window.train_start == config.train_window
        assert window.test_start == window.train_end
        assert window.test_end - window.test_start == config.test_window
        assert window.test_end <= len(bars)
        assert window.train_start < window.train_end <= window.test_start < window.test_end

    for earlier, later in zip(folds, folds[1:]):
        assert later.test_start >= earlier.test_end
        assert later.train_start >= earlier.train_start

    expanding = WalkForwardConfig(
        train_window=40, test_window=10, step=10, warmup=20, mode="expanding"
    )
    exp_folds = build_folds(len(bars), expanding)
    assert len(exp_folds) == len(folds)
    assert all(w.train_start == expanding.warmup for w in exp_folds)
    assert [w.train_end for w in exp_folds] == sorted(w.train_end for w in exp_folds)
    for earlier, later in zip(exp_folds, exp_folds[1:]):
        assert later.test_start >= earlier.test_end

    # A step larger than the test window leaves gaps but never overlaps tests.
    gapped = WalkForwardConfig(train_window=40, test_window=10, step=15, warmup=20)
    gap_folds = build_folds(200, gapped)
    assert len(gap_folds) >= 2
    for earlier, later in zip(gap_folds, gap_folds[1:]):
        assert later.test_start == earlier.test_start + gapped.step
        assert later.test_start >= earlier.test_end
        assert later.train_start == earlier.train_start + gapped.step

    # Bad configs cannot produce overlapping test windows.
    with pytest.raises(ValueError):
        WalkForwardConfig(train_window=40, test_window=10, step=5)


def test_test_window_prices_do_not_change_chosen_train_params():
    config = WalkForwardConfig(train_window=60, test_window=20, step=20, warmup=30)
    bars = _regime_bars(140)
    original = WalkForwardValidator(config).validate(bars, symbol="SYN", data_source="fixture")
    assert original.folds
    first = original.folds[0]

    # The grid must actually discriminate on the train window, otherwise the
    # no-lookahead assertion would be vacuous.
    assert len({c.train_sharpe for c in first.tuning_trace}) > 1
    assert first.train.trade_count > 0

    mutated = copy.deepcopy(bars)
    test_start, test_end = first.window.test_start, first.window.test_end
    assert mutated[:test_start] == bars[:test_start]  # train bars unchanged
    price = mutated[test_start]["close"]
    for i in range(test_start, test_end):
        open_price = price
        price *= 1.02  # force a strong move only inside the test window
        mutated[i].update({
            "open": open_price,
            "high": max(open_price, price) * 1.003,
            "low": min(open_price, price) * 0.997,
            "close": price,
        })
    assert mutated[test_end:] == bars[test_end:]  # later folds' bars unchanged

    changed = WalkForwardValidator(config).validate(mutated, symbol="SYN", data_source="fixture")
    assert changed.folds[0].chosen_params == first.chosen_params
    assert changed.folds[0].train == first.train
    assert changed.folds[0].tuning_trace == first.tuning_trace
    assert changed.folds[0].test.net_pnl != first.test.net_pnl  # mutation did reach test


def test_turnover_and_costs_reduce_net_pnl():
    bars = _trend_bars(100)
    evaluator = StateEvaluator()

    frictionless = run_backtest(
        bars, evaluator,
        config=WalkForwardConfig(slippage_bps=0.0, commission_pct=0.0),
        start=30, end=80,
    )
    costed = run_backtest(bars, evaluator, start=30, end=80)
    expensive = run_backtest(
        bars, evaluator,
        config=WalkForwardConfig(slippage_bps=20.0, commission_pct=0.005),
        start=30, end=80,
    )

    assert costed.trade_count > 0
    assert frictionless.total_costs == 0.0
    assert costed.total_costs > 0.0
    assert costed.net_pnl == pytest.approx(costed.gross_pnl - costed.total_costs, abs=1e-6)
    assert costed.net_pnl < frictionless.net_pnl
    assert expensive.net_pnl < costed.net_pnl
    assert expensive.total_costs > costed.total_costs

    cheap_report = WalkForwardValidator(
        WalkForwardConfig(slippage_bps=0.0, commission_pct=0.0)
    ).validate(bars)
    expensive_report = WalkForwardValidator(
        WalkForwardConfig(slippage_bps=20.0, commission_pct=0.005)
    ).validate(bars)
    assert expensive_report.aggregate.mean_test_sharpe <= cheap_report.aggregate.mean_test_sharpe


def test_evaluator_sees_current_bar_drawdown_and_unrealized_pnl():
    class SpyEvaluator:
        def __init__(self) -> None:
            self.vectors: List[List[float]] = []

        def evaluate(self, vector):
            self.vectors.append([float(value) for value in vector])
            # Buy once at the first bar, then hold through the price break.
            return 2.0 if len(self.vectors) == 1 else 0.0

    bars = _trend_bars(40)
    price = bars[-1]["close"]
    for i in range(40, 60):
        open_price = price
        close = price * 0.6 if i == 40 else price
        bars.append({
            "timestamp": float(1_700_000_000 + i * 3600),
            "open": open_price,
            "high": max(open_price, close) * 1.001,
            "low": min(open_price, close) * 0.999,
            "close": close,
            "volume": 1000.0,
        })
        price = close

    spy = SpyEvaluator()
    result = run_backtest(bars, spy, start=0, end=60)
    assert result.trade_count >= 1
    assert len(spy.vectors) == 60

    # Index 40 is the first break bar. A one-bar-stale portfolio would still
    # report drawdown 0 and the old unrealized PnL there.
    assert spy.vectors[40][16] < -0.01
    assert spy.vectors[40][17] < 0.0


def test_empty_and_short_series_return_safe_empty_result():
    config = WalkForwardConfig(train_window=60, test_window=20, step=20, warmup=30)
    validator = WalkForwardValidator(config)
    empty = validator.validate([], symbol="EMPTY")
    one_bar = validator.validate(_trend_bars(1), symbol="ONE")
    short = validator.validate(_trend_bars(79), symbol="SHORT")

    for report in (empty, one_bar, short):
        assert report.folds == []
        assert report.aggregate.fold_count == 0
        assert report.aggregate.mean_sharpe_degradation == 0.0
        assert report.aggregate.median_sharpe_degradation == 0.0
        assert report.reason.startswith("insufficient_bars")
        payload = report.as_dict()
        json.dumps(payload)  # JSON-report friendly even when empty

    assert build_folds(0, config) == []
    assert run_backtest([], StateEvaluator()).trade_count == 0
    assert run_backtest([], StateEvaluator()).net_pnl == 0.0


def test_validate_oos_labels_synthetic_demo_data_and_accepts_local_bars(tmp_path):
    from tests.validate_oos import (
        DISCLAIMER, disclaimer_for, generate_demo_bars, parse_args, run_validation,
    )

    assert "SYNTHETIC" in DISCLAIMER
    assert "NOT evidence of real-market performance" in DISCLAIMER
    assert disclaimer_for(None) == DISCLAIMER
    assert "series.csv" in disclaimer_for("series.csv")
    assert "SYNTHETIC" not in disclaimer_for("series.csv")
    assert parse_args(["--bars", "series.csv"]).bars == "series.csv"
    assert generate_demo_bars("AAPL", 60) == generate_demo_bars("AAPL", 60)

    demo_report = run_validation(parse_args([
        "--symbols", "AAPL", "--demo-bars", "160", "--no-write",
    ]))
    assert demo_report["data_source"] == "SYNTHETIC_DEMO"
    assert demo_report["disclaimer"] == DISCLAIMER
    json.dumps(demo_report)  # report writer can serialize it

    bars_path = tmp_path / "daily_bars.json"
    bars_path.write_text(json.dumps(generate_demo_bars("AAPL", 160)), encoding="utf-8")
    args = parse_args([
        "--bars", str(bars_path), "--symbols", "AAPL",
        "--annual-factor", "252", "--no-write",
    ])
    local_report = run_validation(args)
    assert local_report["data_source"] == f"LOCAL_FILE:{bars_path}"
    assert local_report["disclaimer"] == disclaimer_for(str(bars_path))
    assert "SYNTHETIC" not in local_report["disclaimer"]
    assert local_report["config"]["annual_factor"] == 252.0
    json.dumps(local_report)


def test_report_is_deterministic_and_json_serializable():
    config = WalkForwardConfig(train_window=60, test_window=20, step=20, warmup=30)
    bars = _regime_bars(140)
    validator = WalkForwardValidator(config)
    first = validator.validate(bars, symbol="SYN", data_source="fixture").as_dict()
    second = validator.validate(bars, symbol="SYN", data_source="fixture").as_dict()
    assert first == second
    json.dumps(first)

    aggregate = first["aggregate"]
    assert {"mean_sharpe_degradation", "median_sharpe_degradation"} <= aggregate.keys()
    for fold in first["folds"]:
        assert {"train", "test", "chosen_params", "sharpe_degradation"} <= fold.keys()
        assert {"sharpe", "net_pnl", "max_drawdown", "trade_count"} <= fold["test"].keys()
