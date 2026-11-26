from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, Tuple


@dataclass(frozen=True)
class PolicyRiskConfig:
    min_confidence: float = 0.55
    max_asset_allocation: float = 0.20
    max_portfolio_exposure: float = 0.85
    max_risk_per_trade: float = 0.015
    daily_loss_limit: float = 0.03
    weekly_loss_limit: float = 0.05
    kill_switch_drawdown: float = 0.07
    max_trades_per_day: int = 15
    stop_atr_multiple: float = 2.0

    def __post_init__(self) -> None:
        fractions = (
            self.min_confidence,
            self.max_asset_allocation,
            self.max_portfolio_exposure,
            self.max_risk_per_trade,
            self.daily_loss_limit,
            self.weekly_loss_limit,
            self.kill_switch_drawdown,
        )
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in fractions):
            raise ValueError("policy risk fractions must be in [0, 1]")
        if isinstance(self.max_trades_per_day, bool) or self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if not math.isfinite(self.stop_atr_multiple) or self.stop_atr_multiple <= 0:
            raise ValueError("stop_atr_multiple must be > 0")


@dataclass(frozen=True)
class PortfolioSnapshot:
    equity: float = 100_000.0
    cash: float = 100_000.0
    position_quantity: float = 0.0
    total_exposure_pct: float = 0.0
    peak_equity: float = 100_000.0
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0
    daily_trades: int = 0
    active_stop_loss: float = 0.0
    allow_new_positions: bool = True


@dataclass(frozen=True)
class PolicyDecision:
    action: str = "HOLD"
    allocation_pct: float = 0.0
    stop_loss: float = 0.0
    stop_distance: float = 0.0
    signal: str = "HOLD"
    confidence: float = 0.0
    reasons: Tuple[str, ...] = ()
    agent_outputs: Dict[str, Any] = field(default_factory=dict)


class TradingPolicy(Protocol):
    def decide(
        self,
        market_data: Dict[str, Any],
        portfolio: PortfolioSnapshot,
    ) -> PolicyDecision: ...
