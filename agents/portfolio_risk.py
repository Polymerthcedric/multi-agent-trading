"""Portfolio-level correlation and risk tracking.

Provides cross-asset correlation monitoring, portfolio VaR computation, and
sector-level exposure tracking so the system can detect hidden concentration
risk when multiple correlated positions are open simultaneously.

The computations are deliberately dependency-free (pure Python): this module is
queried on the trading hot path and must import even when scientific optional
extras are unavailable.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASSET_GROUPS: Dict[str, List[str]] = {
    "commodities": ["GOLD/USD", "SILVER/USD"],
    "forex_major": ["EUR/USD", "GBP/USD", "USD/JPY"],
    "tech_stocks": ["AAPL", "MSFT", "GOOGL"],
    "us_indices": ["SPY", "QQQ"],
}

# Build reverse lookup: symbol -> sector
_SYMBOL_TO_SECTOR: Dict[str, str] = {}
for _sector, _symbols in ASSET_GROUPS.items():
    for _sym in _symbols:
        _SYMBOL_TO_SECTOR[_sym] = _sector

DEFAULT_ROLLING_WINDOW: int = 60  # bars of returns to keep
CORRELATION_THRESHOLD: float = 0.70  # flag pairs above this
MAX_TOTAL_EXPOSURE_PCT: float = 0.85
MAX_CONCENTRATED_EXPOSURE_PCT: float = 0.40  # max combined exposure for correlated group
VAR_CONFIDENCE_95: float = 0.05
VAR_CONFIDENCE_99: float = 0.01


def _finite_float(value: object) -> Optional[float]:
    """Return *value* as a finite float, or ``None`` for invalid input."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation percentile (matches numpy's default method)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation of the two most recent aligned samples.

    Returns 0.0 when either series is constant, too short, or numerically
    degenerate (no NaNs/infinities can escape this function).
    """
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    left = a[-n:]
    right = b[-n:]
    mean_a = sum(left) / n
    mean_b = sum(right) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(left, right))
    var_a = sum((x - mean_a) ** 2 for x in left)
    var_b = sum((y - mean_b) ** 2 for y in right)
    if var_a <= 0.0 or var_b <= 0.0:
        return 0.0
    corr = cov / math.sqrt(var_a * var_b)
    if not math.isfinite(corr):
        return 0.0
    return max(-1.0, min(1.0, corr))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PortfolioRiskAssessment:
    """Snapshot of portfolio-level risk metrics."""

    total_exposure_pct: float  # total position value / portfolio value
    concentrated_exposure: bool  # True if correlated assets exceed limit
    portfolio_var_95: float  # 1-day 95% VaR as % of portfolio
    portfolio_var_99: float  # 1-day 99% VaR as % of portfolio
    sector_exposures: Dict[str, float]  # sector -> exposure %
    correlation_warnings: List[str]  # e.g. "GOLD/USD and SILVER/USD correlation 0.85"
    allow_new_position: bool  # True if portfolio can take on more risk
    reasoning: Dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class PortfolioRiskMonitor:
    """Cross-asset correlation tracker and portfolio risk aggregator.

    Designed to be held as a singleton alongside the ``RiskManager`` and
    queried before every new position is opened.
    """

    def __init__(
        self,
        portfolio_value: float = 100_000.0,
        rolling_window: int = DEFAULT_ROLLING_WINDOW,
        correlation_threshold: float = CORRELATION_THRESHOLD,
        max_total_exposure_pct: float = MAX_TOTAL_EXPOSURE_PCT,
        max_concentrated_exposure_pct: float = MAX_CONCENTRATED_EXPOSURE_PCT,
    ) -> None:
        # A non-finite or non-positive starting value is unusable as a
        # denominator; fall back to 1.0 instead of poisoning every metric.
        initial = _finite_float(portfolio_value)
        self._portfolio_value = initial if initial is not None and initial > 0 else 1.0
        if initial is None or initial <= 0:
            logger.warning("PortfolioRisk | invalid initial portfolio value %r; using 1.0", portfolio_value)

        self._rolling_window = max(2, int(rolling_window))
        threshold = _finite_float(correlation_threshold)
        self._correlation_threshold = threshold if threshold is not None else CORRELATION_THRESHOLD
        total_limit = _finite_float(max_total_exposure_pct)
        self._max_total_exposure_pct = total_limit if total_limit is not None else MAX_TOTAL_EXPOSURE_PCT
        concentrated_limit = _finite_float(max_concentrated_exposure_pct)
        self._max_concentrated_exposure_pct = (
            concentrated_limit if concentrated_limit is not None else MAX_CONCENTRATED_EXPOSURE_PCT
        )

        # symbol -> list of recent returns (newest last); invalid values are
        # rejected at ingestion so correlations/VaR never see NaN or infinity.
        self._returns: Dict[str, List[float]] = defaultdict(list)

        # symbol -> current notional position value (signed: +long / -short)
        self._positions: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API — data ingestion
    # ------------------------------------------------------------------

    def update_portfolio_value(self, value: float) -> None:
        """Update the current total portfolio value (invalid updates ignored)."""
        number = _finite_float(value)
        if number is None or number <= 0:
            logger.warning("PortfolioRisk | ignoring invalid portfolio value %r", value)
            return
        self._portfolio_value = number

    def record_return(self, symbol: str, ret: float) -> None:
        """Append a single-bar return for *symbol* to the rolling window."""
        number = _finite_float(ret)
        if number is None:
            logger.debug("PortfolioRisk | ignoring non-finite return for %s: %r", symbol, ret)
            return
        if not symbol:
            return
        buf = self._returns[symbol]
        buf.append(number)
        if len(buf) > self._rolling_window:
            buf[:] = buf[-self._rolling_window:]

    def record_returns_batch(self, symbol: str, returns: List[float]) -> None:
        """Bulk-load returns for *symbol* (e.g. from a historical backfill)."""
        if not symbol:
            return
        buf = self._returns[symbol]
        for ret in (returns if returns is not None else []):
            number = _finite_float(ret)
            if number is not None:
                buf.append(number)
        if len(buf) > self._rolling_window:
            buf[:] = buf[-self._rolling_window:]

    def set_position(self, symbol: str, notional_value: float) -> None:
        """Set the current notional exposure for *symbol*.

        Use a positive value for long, negative for short, zero to clear.
        Invalid notionals are ignored rather than silently clearing a position.
        """
        number = _finite_float(notional_value)
        if number is None:
            logger.warning("PortfolioRisk | ignoring invalid notional for %s: %r", symbol, notional_value)
            return
        if not symbol:
            return
        if number == 0.0:
            self._positions.pop(symbol, None)
        else:
            # Preserve the sign: shorts are negative and their VaR contribution
            # must offset longs, while exposure metrics use the absolute value.
            self._positions[symbol] = number

    # ------------------------------------------------------------------
    # Public API — risk assessment
    # ------------------------------------------------------------------

    def check_portfolio_risk(self) -> PortfolioRiskAssessment:
        """Compute and return a full portfolio risk snapshot."""
        # Ingestion already validates this; the guard keeps the method total
        # even if internal state is tampered with.
        pv = self._portfolio_value if self._portfolio_value > 0 else 1.0

        # --- total exposure ------------------------------------------------
        # abs() so long and short positions both consume risk budget.
        total_exposure = sum(abs(v) for v in self._positions.values())
        total_exposure_pct = total_exposure / pv

        # --- sector exposures ----------------------------------------------
        sector_exposure: Dict[str, float] = defaultdict(float)
        for sym, notional in self._positions.items():
            sector = _SYMBOL_TO_SECTOR.get(sym, "other")
            sector_exposure[sector] += abs(notional)
        sector_exposures_pct = {s: v / pv for s, v in sector_exposure.items()}

        # --- correlation matrix & warnings ---------------------------------
        correlation_warnings: List[str] = []
        concentrated_exposure = False
        corr_matrix = self._compute_correlation_matrix()

        positioned_symbols = [
            s for s in self._positions
            if s in self._returns and len(self._returns[s]) >= 2
        ]

        for i, sym_a in enumerate(positioned_symbols):
            for sym_b in positioned_symbols[i + 1:]:
                corr = corr_matrix.get((sym_a, sym_b))
                if corr is None:
                    continue
                # Strong inverse correlation is reported too: it can signal a
                # pair that is really one macro bet expressed two ways. Only
                # positive correlation drives the concentration *denial*,
                # because opposing signs hedge rather than compound risk.
                if abs(corr) >= self._correlation_threshold:
                    correlation_warnings.append(
                        f"{sym_a} and {sym_b} correlation {corr:.2f}"
                    )
                    if corr > 0:
                        combined = (
                            abs(self._positions.get(sym_a, 0.0))
                            + abs(self._positions.get(sym_b, 0.0))
                        )
                        if combined / pv > self._max_concentrated_exposure_pct:
                            concentrated_exposure = True

        # --- VaR (historical simulation) -----------------------------------
        var_95, var_99 = self._compute_portfolio_var(pv)

        # --- allow new position? -------------------------------------------
        deny_reasons: List[str] = []
        if total_exposure_pct >= self._max_total_exposure_pct:
            deny_reasons.append("total_exposure_exceeded")
        if concentrated_exposure:
            deny_reasons.append("concentrated_correlated_exposure")
        # Block if 99% VaR exceeds 5% of portfolio (very conservative)
        if var_99 > 0.05:
            deny_reasons.append("var99_too_high")

        allow_new = len(deny_reasons) == 0

        reasoning: Dict[str, object] = {
            "portfolio_value": round(pv, 2),
            "num_positions": len(self._positions),
            "positioned_symbols": list(self._positions.keys()),
            "deny_reasons": deny_reasons,
        }

        assessment = PortfolioRiskAssessment(
            total_exposure_pct=round(total_exposure_pct, 4),
            concentrated_exposure=concentrated_exposure,
            portfolio_var_95=round(var_95, 6),
            portfolio_var_99=round(var_99, 6),
            sector_exposures={s: round(v, 4) for s, v in sector_exposures_pct.items()},
            correlation_warnings=correlation_warnings,
            allow_new_position=allow_new,
            reasoning=reasoning,
        )

        logger.info(
            "PortfolioRisk | exposure=%.2f%% var95=%.4f%% var99=%.4f%% "
            "concentrated=%s allow_new=%s warnings=%d",
            total_exposure_pct * 100, var_95 * 100, var_99 * 100,
            concentrated_exposure, allow_new, len(correlation_warnings),
        )

        return assessment

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_correlation_matrix(self) -> Dict[tuple, float]:
        """Return pairwise Pearson correlations for symbols with sufficient data.

        Returns a dict mapping ``(sym_a, sym_b)`` -> correlation (both orderings).
        """
        symbols = [s for s, r in self._returns.items() if len(r) >= 2]
        result: Dict[tuple, float] = {}
        if len(symbols) < 2:
            return result

        # Align lengths: use the most recent N bars common to each pair
        for i, sym_a in enumerate(symbols):
            for sym_b in symbols[i + 1:]:
                result[(sym_a, sym_b)] = _pearson(self._returns[sym_a], self._returns[sym_b])
                result[(sym_b, sym_a)] = result[(sym_a, sym_b)]

        return result

    def _compute_portfolio_var(self, pv: float) -> tuple[float, float]:
        """Historical-simulation VaR for the current portfolio.

        Returns ``(var_95, var_99)`` as fractions of portfolio value.
        If insufficient data, returns ``(0.0, 0.0)``.
        """
        if not self._positions:
            return 0.0, 0.0

        # Build aligned return matrix for positioned symbols
        positioned = {
            s: self._returns[s] for s in self._positions
            if s in self._returns and len(self._returns[s]) >= 2
        }
        if not positioned:
            return 0.0, 0.0

        # Use the shortest common history length
        min_len = min(len(r) for r in positioned.values())
        if min_len < 2:
            return 0.0, 0.0

        symbols = list(positioned.keys())
        # Signed weights: shorts offset longs in the simulated P&L.
        weights = [self._positions[s] / pv for s in symbols]

        # Simulated portfolio returns for each historical bar.
        port_returns = [
            sum(positioned[s][-min_len:][i] * w for s, w in zip(symbols, weights))
            for i in range(min_len)
        ]

        # VaR as the negative percentile of the loss distribution, floored at
        # zero (a profitable tail is not a loss).
        var_95 = max(-_percentile(port_returns, VAR_CONFIDENCE_95), 0.0)
        var_99 = max(-_percentile(port_returns, VAR_CONFIDENCE_99), 0.0)
        return var_95, var_99
