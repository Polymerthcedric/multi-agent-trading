"""Deterministic, offline walk-forward validation for fixed policies and evaluators.

Both validators take ONE chronological series of bar dicts and slice it into
folds. ``WalkForwardValidator`` tunes ``StateEvaluator`` on each TRAIN window;
``PolicyWalkForwardValidator`` keeps the supplied decision policy fixed and
compares it with baselines. Neither path uses test bars for parameter choice.

Folds are ROLLING by default (the train window slides forward by ``step``).
``mode="expanding"`` keeps the train start fixed and grows the train window.
Test windows are non-overlapping because ``step >= test_window`` is enforced.
``warmup`` bars of history precede the first train window and are used only to
seed causal indicators; they are never traded or tuned on.

Signals are computed from a bar's close (using trailing features only) and
filled at the NEXT bar's open, avoiding same-bar execution lookahead. The
shared kernel is long/flat with a per-position notional cap and tracks
slippage and commission separately so gross and net PnL can be reconciled.

Known limitation: ``StateEvaluator.risk_aversion`` is currently accepted by
the evaluator but not used inside ``evaluate()``.  It is exposed in the grid
for API completeness; only ``drawdown_penalty`` and
``position_conviction_bonus`` can change trade decisions today.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from engine.evaluator import StateEvaluator
from engine.state import MarketState

SLIPPAGE_BPS = 2.0
COMMISSION_PCT = 0.001
DEFAULT_ANNUAL_FACTOR = 252.0 * 6.5  # hourly bars, as used by the old OOS script


class DecisionPolicy(Protocol):
    def decide(self, market_data: Dict[str, float]) -> str: ...


@dataclass(frozen=True)
class EvaluatorParams:
    """The tunable subset of ``StateEvaluator`` constructor arguments."""

    risk_aversion: float = 3.0
    drawdown_penalty: float = 2.0
    position_conviction_bonus: float = 0.3

    def as_dict(self) -> Dict[str, float]:
        return {
            "risk_aversion": float(self.risk_aversion),
            "drawdown_penalty": float(self.drawdown_penalty),
            "position_conviction_bonus": float(self.position_conviction_bonus),
        }

    def make_evaluator(self) -> StateEvaluator:
        return StateEvaluator(
            risk_aversion=self.risk_aversion,
            drawdown_penalty=self.drawdown_penalty,
            position_conviction_bonus=self.position_conviction_bonus,
        )


DEFAULT_EVALUATOR_GRID: Tuple[EvaluatorParams, ...] = (
    EvaluatorParams(3.0, 2.0, 0.3),
    EvaluatorParams(3.0, 0.0, 0.3),
    EvaluatorParams(3.0, 8.0, 0.3),
    EvaluatorParams(3.0, 2.0, 0.0),
    EvaluatorParams(3.0, 2.0, 2.0),
)


@dataclass(frozen=True)
class WalkForwardConfig:
    train_window: int = 120
    test_window: int = 30
    step: int = 30
    warmup: int = 50
    mode: str = "rolling"  # "rolling" | "expanding"
    initial_capital: float = 100_000.0
    position_size_pct: float = 0.20
    slippage_bps: float = SLIPPAGE_BPS
    commission_pct: float = COMMISSION_PCT
    buy_threshold: float = 1.5
    sell_threshold: float = -1.0
    annual_factor: float = DEFAULT_ANNUAL_FACTOR
    evaluator_grid: Tuple[EvaluatorParams, ...] = DEFAULT_EVALUATOR_GRID

    def __post_init__(self) -> None:
        if self.train_window < 2:
            raise ValueError("train_window must be >= 2")
        if self.test_window < 1:
            raise ValueError("test_window must be >= 1")
        if self.step < self.test_window:
            raise ValueError("step must be >= test_window so test windows do not overlap")
        if self.warmup < 0:
            raise ValueError("warmup must be >= 0")
        if self.mode not in ("rolling", "expanding"):
            raise ValueError("mode must be 'rolling' or 'expanding'")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be > 0")
        if not 0 < self.position_size_pct <= 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        if self.slippage_bps < 0 or self.slippage_bps >= 10_000:
            raise ValueError("slippage_bps must be in [0, 10000)")
        if self.commission_pct < 0 or self.commission_pct >= 1:
            raise ValueError("commission_pct must be in [0, 1)")
        if not math.isfinite(self.annual_factor) or self.annual_factor <= 0:
            raise ValueError("annual_factor must be finite and > 0")
        if not self.evaluator_grid:
            object.__setattr__(self, "evaluator_grid", (EvaluatorParams(),))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "train_window": self.train_window,
            "test_window": self.test_window,
            "step": self.step,
            "warmup": self.warmup,
            "initial_capital": self.initial_capital,
            "position_size_pct": self.position_size_pct,
            "slippage_bps": self.slippage_bps,
            "commission_pct": self.commission_pct,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "annual_factor": self.annual_factor,
            "evaluator_grid": [p.as_dict() for p in self.evaluator_grid],
        }


@dataclass(frozen=True)
class BacktestResult:
    """Metrics for one in-sample or out-of-sample window."""

    sharpe: float = 0.0
    net_pnl: float = 0.0
    gross_pnl: float = 0.0
    total_costs: float = 0.0
    max_drawdown: float = 0.0  # negative fraction, 0.0 means no drawdown
    trade_count: int = 0
    final_equity: float = 0.0
    bars: int = 0
    signals: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sharpe": round(self.sharpe, 6),
            "net_pnl": round(self.net_pnl, 6),
            "gross_pnl": round(self.gross_pnl, 6),
            "total_costs": round(self.total_costs, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "trade_count": self.trade_count,
            "final_equity": round(self.final_equity, 6),
            "bars": self.bars,
            "signals": list(self.signals),
        }


@dataclass(frozen=True)
class FoldWindow:
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "fold": self.fold,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


@dataclass(frozen=True)
class TuningCandidate:
    params: EvaluatorParams
    train_sharpe: float
    train_net_pnl: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "params": self.params.as_dict(),
            "train_sharpe": round(self.train_sharpe, 6),
            "train_net_pnl": round(self.train_net_pnl, 6),
        }


@dataclass(frozen=True)
class FoldResult:
    window: FoldWindow
    chosen_params: EvaluatorParams
    train: BacktestResult
    test: BacktestResult
    tuning_trace: Tuple[TuningCandidate, ...] = ()

    @property
    def sharpe_degradation(self) -> float:
        """test minus train; negative means the out-of-sample window was worse."""
        return self.test.sharpe - self.train.sharpe

    @property
    def net_pnl_degradation(self) -> float:
        return self.test.net_pnl - self.train.net_pnl

    def as_dict(self) -> Dict[str, Any]:
        return {
            **self.window.as_dict(),
            "chosen_params": self.chosen_params.as_dict(),
            "train": self.train.as_dict(),
            "test": self.test.as_dict(),
            "sharpe_degradation": round(self.sharpe_degradation, 6),
            "net_pnl_degradation": round(self.net_pnl_degradation, 6),
            "tuning_trace": [c.as_dict() for c in self.tuning_trace],
        }


@dataclass(frozen=True)
class AggregateMetrics:
    fold_count: int = 0
    mean_train_sharpe: float = 0.0
    mean_test_sharpe: float = 0.0
    mean_sharpe_degradation: float = 0.0
    median_sharpe_degradation: float = 0.0
    mean_net_pnl_degradation: float = 0.0
    median_net_pnl_degradation: float = 0.0
    mean_train_max_drawdown: float = 0.0
    mean_test_max_drawdown: float = 0.0
    total_trades: int = 0
    total_costs: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "fold_count": self.fold_count,
            "mean_train_sharpe": round(self.mean_train_sharpe, 6),
            "mean_test_sharpe": round(self.mean_test_sharpe, 6),
            "mean_sharpe_degradation": round(self.mean_sharpe_degradation, 6),
            "median_sharpe_degradation": round(self.median_sharpe_degradation, 6),
            "mean_net_pnl_degradation": round(self.mean_net_pnl_degradation, 6),
            "median_net_pnl_degradation": round(self.median_net_pnl_degradation, 6),
            "mean_train_max_drawdown": round(self.mean_train_max_drawdown, 6),
            "mean_test_max_drawdown": round(self.mean_test_max_drawdown, 6),
            "total_trades": self.total_trades,
            "total_costs": round(self.total_costs, 6),
        }


@dataclass(frozen=True)
class WalkForwardReport:
    config: WalkForwardConfig
    folds: List[FoldResult] = field(default_factory=list)
    aggregate: AggregateMetrics = field(default_factory=AggregateMetrics)
    symbol: str = ""
    data_source: str = ""
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "data_source": self.data_source,
            "reason": self.reason,
            "config": self.config.as_dict(),
            "fold_count": len(self.folds),
            "folds": [f.as_dict() for f in self.folds],
            "aggregate": self.aggregate.as_dict(),
        }


@dataclass(frozen=True)
class PolicyFoldResult:
    window: FoldWindow
    in_sample: BacktestResult
    out_of_sample: BacktestResult
    benchmarks: Dict[str, BacktestResult] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            **self.window.as_dict(),
            "in_sample": self.in_sample.as_dict(),
            "out_of_sample": self.out_of_sample.as_dict(),
            "benchmarks": {
                name: result.as_dict() for name, result in self.benchmarks.items()
            },
        }


@dataclass(frozen=True)
class PolicyWalkForwardReport:
    config: WalkForwardConfig
    folds: List[PolicyFoldResult] = field(default_factory=list)
    symbol: str = ""
    data_source: str = ""
    strategy: str = ""
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        results = [fold.out_of_sample for fold in self.folds]
        in_sample = [fold.in_sample for fold in self.folds]
        in_sample_summary = _summarize_results(in_sample)
        out_of_sample_summary = _summarize_results(results)
        sharpe_degradations = [
            fold.out_of_sample.sharpe - fold.in_sample.sharpe for fold in self.folds
        ]
        pnl_degradations = [
            fold.out_of_sample.net_pnl - fold.in_sample.net_pnl for fold in self.folds
        ]
        benchmark_results: Dict[str, List[BacktestResult]] = {}
        for fold in self.folds:
            for name, result in fold.benchmarks.items():
                benchmark_results.setdefault(name, []).append(result)
        total_costs = sum(r.total_costs for r in in_sample + results)
        config = self.config.as_dict()
        config.pop("buy_threshold", None)
        config.pop("sell_threshold", None)
        config.pop("evaluator_grid", None)
        return {
            "symbol": self.symbol,
            "data_source": self.data_source,
            "strategy": self.strategy,
            "reason": self.reason,
            "config": config,
            "tuning": "none; the policy remains fixed across all folds",
            "fold_count": len(self.folds),
            "in_sample": in_sample_summary,
            "out_of_sample": out_of_sample_summary,
            "aggregate": {
                "fold_count": len(self.folds),
                "mean_train_sharpe": in_sample_summary["mean_sharpe"],
                "mean_test_sharpe": out_of_sample_summary["mean_sharpe"],
                "mean_sharpe_degradation": (
                    round(statistics.fmean(sharpe_degradations), 6)
                    if sharpe_degradations else 0.0
                ),
                "median_sharpe_degradation": (
                    round(statistics.median(sharpe_degradations), 6)
                    if sharpe_degradations else 0.0
                ),
                "mean_net_pnl_degradation": (
                    round(statistics.fmean(pnl_degradations), 6)
                    if pnl_degradations else 0.0
                ),
                "median_net_pnl_degradation": (
                    round(statistics.median(pnl_degradations), 6)
                    if pnl_degradations else 0.0
                ),
                "mean_train_max_drawdown": in_sample_summary["mean_max_drawdown"],
                "mean_test_max_drawdown": out_of_sample_summary["mean_max_drawdown"],
                "total_trades": sum(r.trade_count for r in in_sample + results),
                "total_costs": round(total_costs, 6),
            },
            "benchmarks": {
                name: _summarize_results(values)
                for name, values in benchmark_results.items()
            },
            "folds": [fold.as_dict() for fold in self.folds],
        }


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _coerce_timestamp(value: Any) -> Optional[float]:
    ts = _as_float(value)
    if ts is not None:
        return ts
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _prepare_bars(bars: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
    """Normalize and validate one chronological series; never reorders bars."""
    if not bars:
        return []

    prepared: List[Dict[str, float]] = []
    previous_ts: Optional[float] = None
    saw_timestamp = False
    for index, raw in enumerate(bars):
        if not isinstance(raw, dict):
            raise ValueError(f"bar {index} must be a dict")

        close = _as_float(raw.get("close"))
        if close is None or close <= 0:
            raise ValueError(f"bar {index} has no positive 'close'")

        open_price = _as_float(raw.get("open"), close)
        assert open_price is not None  # fallback above is always finite
        if open_price <= 0:
            open_price = close

        high = _as_float(raw.get("high"), max(open_price, close))
        low = _as_float(raw.get("low"), min(open_price, close))
        assert high is not None and low is not None
        high = max(high, open_price, close)
        low = min(low, open_price, close)
        if low <= 0:
            low = close

        volume = _as_float(raw.get("volume"), 0.0) or 0.0

        raw_ts = raw.get("timestamp")
        if raw_ts is not None:
            ts = _coerce_timestamp(raw_ts)
            if ts is None:
                raise ValueError(f"bar {index} has an unparseable timestamp")
            saw_timestamp = True
            if previous_ts is not None and ts < previous_ts:
                raise ValueError("bars must be chronological by timestamp")
            previous_ts = ts

        prepared.append({
            "timestamp": float(previous_ts or 0.0) if saw_timestamp else 0.0,
            "open": float(open_price),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume),
        })
    return prepared


def _build_features(bars: Sequence[Dict[str, float]]) -> List[Dict[str, float]]:
    """Causal indicators: bar i only ever uses closes/highs/lows up to i."""
    closes = [b["close"] for b in bars]
    features: List[Dict[str, float]] = []
    macd_values: List[float] = []
    for i, bar in enumerate(bars):
        prior = closes[max(0, i - 50):i]
        window20 = closes[max(0, i - 20):i] or [bar["close"]]
        window10 = closes[max(0, i - 10):i] or [bar["close"]]
        current_window20 = closes[max(0, i - 19):i + 1]
        fast_window = closes[max(0, i - 11):i + 1]
        slow_window = closes[max(0, i - 25):i + 1]
        macd = sum(fast_window) / len(fast_window) - sum(slow_window) / len(slow_window)
        macd_values.append(macd)
        macd_signal_window = macd_values[max(0, i - 8):i + 1]
        band_mean = sum(current_window20) / len(current_window20)
        band_std = math.sqrt(
            sum((close - band_mean) ** 2 for close in current_window20)
            / len(current_window20)
        )
        current_bars = bars[max(0, i - 19):i + 1]

        deltas = [closes[j] - closes[j - 1] for j in range(max(1, i - 13), i + 1)]
        gains = sum(d for d in deltas if d > 0) / len(deltas) if deltas else 0.0
        losses = sum(-d for d in deltas if d < 0) / len(deltas) if deltas else 0.0
        rsi = 100.0 - 100.0 / (1.0 + gains / losses) if losses > 0 else (100.0 if gains > 0 else 50.0)

        atr_window = bars[max(0, i - 13):i + 1]
        atr = sum(b["high"] - b["low"] for b in atr_window) / len(atr_window)
        momentum = ((bar["close"] / closes[i - 10] - 1.0) * 100.0) if i >= 10 and closes[i - 10] > 0 else 0.0

        features.append({
            "price": bar["close"],
            "high": bar["high"],
            "low": bar["low"],
            "sma": sum(window20) / len(window20),
            "ema": sum(window10) / len(window10),
            "rsi": min(100.0, max(0.0, rsi)),
            "atr": atr,
            "momentum": momentum,
            "macd": macd,
            "macd_signal": sum(macd_signal_window) / len(macd_signal_window),
            "bb_upper": band_mean + 2.0 * band_std,
            "bb_lower": band_mean - 2.0 * band_std,
            "historical_support": min(b["low"] for b in current_bars),
            "historical_resistance": max(b["high"] for b in current_bars),
            "adx": 20.0,
            "volume": bar["volume"],
            "prior_closes": prior,
        })
    return features


def _safe_sharpe(returns: Sequence[float], annual_factor: float) -> float:
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    if variance <= 0 or not math.isfinite(variance):
        return 0.0
    sharpe = (mean_r / math.sqrt(variance)) * math.sqrt(annual_factor)
    return sharpe if math.isfinite(sharpe) else 0.0


def _max_drawdown(equity: Sequence[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst


def _empty_result() -> BacktestResult:
    return BacktestResult(final_equity=0.0)


def _run_kernel(
    bars: Sequence[Dict[str, float]],
    features: Sequence[Dict[str, float]],
    start: int,
    end: int,
    evaluator: Optional[StateEvaluator],
    config: WalkForwardConfig,
    symbol: str,
    policy: Optional[DecisionPolicy] = None,
) -> BacktestResult:
    """Long/flat backtest over ``bars[start:end]`` with next-open execution."""
    if evaluator is None and policy is None:
        raise ValueError("an evaluator or decision policy is required")
    if end <= start or start < 0 or end > len(bars):
        return _empty_result()

    cash = config.initial_capital
    position = 0.0
    entry_price = 0.0  # effective (slipped + commission-inclusive) cost basis
    total_costs = 0.0
    trade_count = 0
    signals: List[str] = []
    equity = [cash]
    returns: List[float] = []
    peak = cash
    pending: Optional[str] = None

    seed_closes = features[start]["prior_closes"]
    state = MarketState(symbol=symbol, price=seed_closes[-1] if seed_closes else bars[start]["close"])
    state.price_history = list(seed_closes)

    slippage = config.slippage_bps / 10_000.0

    if policy is not None:
        for index in range(start):
            warmup_data = dict(features[index])
            warmup_data.pop("prior_closes", None)
            action = policy.decide(warmup_data)
            if action not in ("BUY", "SELL", "HOLD"):
                raise ValueError(f"policy returned unsupported action: {action!r}")

    for i in range(start, end):
        bar = bars[i]
        current_price = bar["close"]

        # Execute the signal formed on the previous close at this bar's open.
        if pending == "BUY" and position <= 0:
            fill = bar["open"]
            exec_price = fill * (1.0 + slippage)
            budget = min(equity[-1] * config.position_size_pct, cash / (1.0 + config.commission_pct))
            qty = budget / exec_price if exec_price > 0 else 0.0
            if qty > 0:
                commission = qty * exec_price * config.commission_pct
                slip_cost = qty * fill * slippage
                cash -= qty * exec_price + commission
                position = qty
                entry_price = exec_price + commission / qty
                total_costs += commission + slip_cost
                trade_count += 1
                signals.append("BUY")
        elif pending == "SELL" and position > 0:
            fill = bar["open"]
            exec_price = fill * (1.0 - slippage)
            if exec_price > 0:  # defensive; config caps slippage below 100%
                notional = position * exec_price
                commission = notional * config.commission_pct
                slip_cost = position * fill * slippage
                cash += notional - commission
                position = 0.0
                entry_price = 0.0
                total_costs += commission + slip_cost
                trade_count += 1
                signals.append("SELL")
        pending = None

        current_equity = cash + position * current_price
        peak = max(peak, current_equity)
        previous_equity = equity[-1]
        if previous_equity > 0 and current_equity > 0:
            returns.append((current_equity - previous_equity) / previous_equity)
        equity.append(current_equity)

        # Publish the post-fill portfolio before MarketState derives
        # drawdown_pct and unrealized_pnl. Otherwise the evaluator sees the
        # previous bar's values and decisions lag one bar behind the mark.
        state.cash = cash
        state.position = position
        state.avg_entry = entry_price if position > 0 else 0.0
        state.portfolio_value = current_equity
        state.peak_value = peak

        md = dict(features[i])
        md.pop("prior_closes", None)
        new_state = MarketState.from_market_data(symbol, md, state=state)
        if policy is not None:
            action = policy.decide(md)
            if action not in ("BUY", "SELL", "HOLD"):
                raise ValueError(f"policy returned unsupported action: {action!r}")
            if action == "BUY" and position <= 0:
                pending = "BUY"
            elif action == "SELL" and position > 0:
                pending = "SELL"
        else:
            assert evaluator is not None
            score = evaluator.evaluate(new_state.to_vector())
            if score > config.buy_threshold and position <= 0:
                pending = "BUY"
            elif score < config.sell_threshold and position > 0:
                pending = "SELL"
        state = new_state

    final_equity = equity[-1]
    net_pnl = final_equity - config.initial_capital
    return BacktestResult(
        sharpe=_safe_sharpe(returns, config.annual_factor),
        net_pnl=net_pnl,
        gross_pnl=net_pnl + total_costs,
        total_costs=total_costs,
        max_drawdown=_max_drawdown(equity),
        trade_count=trade_count,
        final_equity=final_equity,
        bars=end - start,
        signals=tuple(signals[:10]),
    )


def run_backtest(
    bars: Sequence[Dict[str, Any]],
    evaluator: StateEvaluator,
    *,
    config: Optional[WalkForwardConfig] = None,
    symbol: str = "",
    start: int = 0,
    end: Optional[int] = None,
) -> BacktestResult:
    """Reusable kernel over an explicit slice of one bar series."""
    cfg = config or WalkForwardConfig()
    prepared = _prepare_bars(bars)
    if not prepared:
        return _empty_result()
    features = _build_features(prepared)
    stop = len(prepared) if end is None else min(end, len(prepared))
    return _run_kernel(prepared, features, max(0, start), stop, evaluator, cfg, symbol)


def run_policy_backtest(
    bars: Sequence[Dict[str, Any]],
    policy_factory: Callable[[], DecisionPolicy],
    *,
    config: Optional[WalkForwardConfig] = None,
    symbol: str = "",
    start: int = 0,
    end: Optional[int] = None,
) -> BacktestResult:
    """Run a deterministic decision policy through the same cost/fill kernel."""
    cfg = config or WalkForwardConfig()
    prepared = _prepare_bars(bars)
    if not prepared:
        return _empty_result()
    features = _build_features(prepared)
    stop = len(prepared) if end is None else min(end, len(prepared))
    return _run_kernel(
        prepared, features, max(0, start), stop, None, cfg, symbol,
        policy=policy_factory(),
    )


def build_folds(n_bars: int, config: Optional[WalkForwardConfig] = None) -> List[FoldWindow]:
    """Chronological, non-overlapping test folds; empty list if data is short."""
    cfg = config or WalkForwardConfig()
    required = cfg.warmup + cfg.train_window + cfg.test_window
    if n_bars < required:
        return []

    folds: List[FoldWindow] = []
    k = 0
    while True:
        if cfg.mode == "rolling":
            train_start = cfg.warmup + k * cfg.step
            train_end = train_start + cfg.train_window
        else:
            train_start = cfg.warmup
            train_end = cfg.warmup + cfg.train_window + k * cfg.step
        test_start = train_end
        test_end = test_start + cfg.test_window
        if test_end > n_bars:
            break
        folds.append(FoldWindow(k, train_start, train_end, test_start, test_end))
        k += 1
    return folds


def _aggregate(folds: Sequence[FoldResult]) -> AggregateMetrics:
    if not folds:
        return AggregateMetrics()

    def mean_of(values: List[float]) -> float:
        return statistics.fmean(values) if values else 0.0

    def median_of(values: List[float]) -> float:
        return statistics.median(values) if values else 0.0

    degradations = [f.sharpe_degradation for f in folds]
    pnl_degradations = [f.net_pnl_degradation for f in folds]
    return AggregateMetrics(
        fold_count=len(folds),
        mean_train_sharpe=mean_of([f.train.sharpe for f in folds]),
        mean_test_sharpe=mean_of([f.test.sharpe for f in folds]),
        mean_sharpe_degradation=mean_of(degradations),
        median_sharpe_degradation=median_of(degradations),
        mean_net_pnl_degradation=mean_of(pnl_degradations),
        median_net_pnl_degradation=median_of(pnl_degradations),
        mean_train_max_drawdown=mean_of([f.train.max_drawdown for f in folds]),
        mean_test_max_drawdown=mean_of([f.test.max_drawdown for f in folds]),
        total_trades=sum(f.train.trade_count + f.test.trade_count for f in folds),
        total_costs=sum(f.train.total_costs + f.test.total_costs for f in folds),
    )


def _summarize_results(results: Sequence[BacktestResult]) -> Dict[str, Any]:
    return {
        "fold_count": len(results),
        "mean_sharpe": round(statistics.fmean(r.sharpe for r in results), 6) if results else 0.0,
        "median_sharpe": round(statistics.median(r.sharpe for r in results), 6) if results else 0.0,
        "mean_net_pnl": round(statistics.fmean(r.net_pnl for r in results), 6) if results else 0.0,
        "median_net_pnl": round(statistics.median(r.net_pnl for r in results), 6) if results else 0.0,
        "mean_max_drawdown": round(statistics.fmean(r.max_drawdown for r in results), 6) if results else 0.0,
        "total_trades": sum(r.trade_count for r in results),
        "total_costs": round(sum(r.total_costs for r in results), 6),
    }


class BuyAndHoldPolicy:
    def decide(self, market_data: Dict[str, float]) -> str:
        return "BUY"


class CashPolicy:
    def decide(self, market_data: Dict[str, float]) -> str:
        return "HOLD"


class PolicyWalkForwardValidator:
    """Evaluate one fixed policy on chronological folds without fitting on test bars."""

    def __init__(
        self,
        policy_factory: Callable[[], DecisionPolicy],
        config: Optional[WalkForwardConfig] = None,
        *,
        strategy: str = "",
        benchmark_factories: Optional[Dict[str, Callable[[], DecisionPolicy]]] = None,
    ) -> None:
        self.policy_factory = policy_factory
        self.config = config or WalkForwardConfig()
        self.strategy = strategy or getattr(policy_factory, "__name__", "fixed-policy")
        self.benchmark_factories = (
            benchmark_factories
            if benchmark_factories is not None
            else {"buy_and_hold": BuyAndHoldPolicy, "cash": CashPolicy}
        )

    def validate(
        self,
        bars: Optional[Sequence[Dict[str, Any]]],
        *,
        symbol: str = "",
        data_source: str = "",
    ) -> PolicyWalkForwardReport:
        prepared = _prepare_bars(bars)
        windows = build_folds(len(prepared), self.config)
        if not windows:
            required = (
                self.config.warmup
                + self.config.train_window
                + self.config.test_window
            )
            return PolicyWalkForwardReport(
                config=self.config,
                symbol=symbol,
                data_source=data_source,
                strategy=self.strategy,
                reason=f"insufficient_bars: need {required}, got {len(prepared)}",
            )

        features = _build_features(prepared)
        folds: List[PolicyFoldResult] = []
        for window in windows:
            in_sample = _run_kernel(
                prepared, features, window.train_start, window.train_end,
                None, self.config, symbol, policy=self.policy_factory(),
            )
            out_of_sample = _run_kernel(
                prepared, features, window.test_start, window.test_end,
                None, self.config, symbol, policy=self.policy_factory(),
            )
            benchmarks = {
                name: _run_kernel(
                    prepared, features, window.test_start, window.test_end,
                    None, self.config, symbol, policy=factory(),
                )
                for name, factory in self.benchmark_factories.items()
            }
            folds.append(PolicyFoldResult(
                window=window,
                in_sample=in_sample,
                out_of_sample=out_of_sample,
                benchmarks=benchmarks,
            ))
        return PolicyWalkForwardReport(
            config=self.config,
            folds=folds,
            symbol=symbol,
            data_source=data_source,
            strategy=self.strategy,
        )


class WalkForwardValidator:
    """Tune on train, evaluate once on test, for every fold."""

    def __init__(self, config: Optional[WalkForwardConfig] = None) -> None:
        self.config = config or WalkForwardConfig()

    def validate(
        self,
        bars: Optional[Sequence[Dict[str, Any]]],
        *,
        symbol: str = "",
        data_source: str = "",
    ) -> WalkForwardReport:
        cfg = self.config
        prepared = _prepare_bars(bars)
        windows = build_folds(len(prepared), cfg)
        if not windows:
            required = cfg.warmup + cfg.train_window + cfg.test_window
            return WalkForwardReport(
                config=cfg,
                symbol=symbol,
                data_source=data_source,
                reason=f"insufficient_bars: need {required}, got {len(prepared)}",
            )

        # Features are causal, so compute them once for the whole series.  No
        # test bar can affect a train feature used for parameter selection.
        features = _build_features(prepared)
        fold_results: List[FoldResult] = []

        for window in windows:
            trace: List[TuningCandidate] = []
            best_params: Optional[EvaluatorParams] = None
            best_train: Optional[BacktestResult] = None
            best_key: Optional[Tuple[float, float, float, int]] = None

            for index, params in enumerate(cfg.evaluator_grid):
                train_result = _run_kernel(
                    prepared, features,
                    window.train_start, window.train_end,
                    params.make_evaluator(), cfg, symbol,
                )
                trace.append(TuningCandidate(params, train_result.sharpe, train_result.net_pnl))
                # Deterministic tie-break: Sharpe, then PnL, then drawdown,
                # then earlier grid entry wins.  Test data is never consulted.
                key = (train_result.sharpe, train_result.net_pnl, train_result.max_drawdown, -index)
                if best_key is None or key > best_key:
                    best_key = key
                    best_params = params
                    best_train = train_result

            assert best_params is not None and best_train is not None  # grid is non-empty
            test_result = _run_kernel(
                prepared, features,
                window.test_start, window.test_end,
                best_params.make_evaluator(), cfg, symbol,
            )
            fold_results.append(FoldResult(
                window=window,
                chosen_params=best_params,
                train=best_train,
                test=test_result,
                tuning_trace=tuple(trace),
            ))

        return WalkForwardReport(
            config=cfg,
            folds=fold_results,
            aggregate=_aggregate(fold_results),
            symbol=symbol,
            data_source=data_source,
        )


__all__ = [
    "SLIPPAGE_BPS",
    "COMMISSION_PCT",
    "AggregateMetrics",
    "BacktestResult",
    "BuyAndHoldPolicy",
    "CashPolicy",
    "DecisionPolicy",
    "EvaluatorParams",
    "FoldResult",
    "FoldWindow",
    "PolicyFoldResult",
    "PolicyWalkForwardReport",
    "PolicyWalkForwardValidator",
    "TuningCandidate",
    "WalkForwardConfig",
    "WalkForwardReport",
    "WalkForwardValidator",
    "build_folds",
    "run_backtest",
    "run_policy_backtest",
]
