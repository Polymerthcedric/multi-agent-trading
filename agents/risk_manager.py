from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

MAX_ASSET_ALLOCATION: float = 0.25
MAX_PORTFOLIO_EXPOSURE: float = 0.90
TRAILING_STOP_LOSS: float = 0.02
DAILY_DRAWDOWN_HALT: float = 0.05
MIN_CONFIDENCE_THRESHOLD: float = 0.55
POSITION_SIZING_K: float = 0.25
MAX_RISK_PER_TRADE: float = 0.02
DRAWDOWN_LOCKDOWN_HOURS: int = 24
ESTIMATED_SLIPPAGE_BPS: float = 2.0
ESTIMATED_SPREAD_BPS: float = 1.0


@dataclass(frozen=True)
class RiskLimits:
    max_asset_allocation: float = MAX_ASSET_ALLOCATION
    max_portfolio_exposure: float = MAX_PORTFOLIO_EXPOSURE
    trailing_stop_loss: float = TRAILING_STOP_LOSS
    daily_drawdown_halt: float = DAILY_DRAWDOWN_HALT
    min_confidence_threshold: float = MIN_CONFIDENCE_THRESHOLD
    position_sizing_k: float = POSITION_SIZING_K
    max_risk_per_trade: float = MAX_RISK_PER_TRADE
    drawdown_lockdown_hours: int = DRAWDOWN_LOCKDOWN_HOURS
    estimated_slippage_bps: float = ESTIMATED_SLIPPAGE_BPS
    estimated_spread_bps: float = ESTIMATED_SPREAD_BPS


@dataclass
class AllocationDecision:
    action: str = "HOLD"
    symbol: str = "UNKNOWN"
    allocation_pct: float = 0.0
    stop_loss: float = 0.0
    reasoning: Dict[str, object] = field(default_factory=dict)


class RiskManager:
    name: str = "risk_manager"

    def __init__(self, initial_portfolio_value: float = 100000.0) -> None:
        self.limits = RiskLimits()
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._last_pnl_date: str = ""
        self._trading_halted: bool = False
        self._peak_value: float = initial_portfolio_value
        self._lockdown_until: float = 0.0

    def update_portfolio_value(self, portfolio_value: float) -> None:
        self._peak_value = max(self._peak_value, portfolio_value)

    def _estimate_fill_price(self, side: str, quoted_price: float) -> float:
        # NOTE: Similar fill-price logic exists in broker.py — keep in sync
        slip = quoted_price * self.limits.estimated_slippage_bps / 10000.0
        spread_half = quoted_price * self.limits.estimated_spread_bps / 20000.0
        if side == "BUY":
            return quoted_price + slip + spread_half
        return quoted_price - slip - spread_half

    def update_daily_pnl(self, pnl: float) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._last_pnl_date:
            self._daily_pnl = 0.0
            self._last_pnl_date = today
        self._daily_pnl += pnl
        drawdown_pct = self._daily_pnl / self._peak_value if self._peak_value > 0 else 0.0
        if drawdown_pct <= -self.limits.daily_drawdown_halt:
            self._trading_halted = True
            self._lockdown_until = time.time() + self.limits.drawdown_lockdown_hours * 3600
            logger.warning(
                "RISK_HALT | drawdown=%.4f threshold=%.4f lockdown_until=%s",
                drawdown_pct, self.limits.daily_drawdown_halt,
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._lockdown_until)),
            )

    async def evaluate(
        self,
        prediction: Optional[Dict[str, object]] = None,
        context: Optional[Dict[str, object]] = None,
        volatility: Optional[Dict[str, object]] = None,
        market_data: Optional[Dict[str, float]] = None,
    ) -> AllocationDecision:
        if self._trading_halted:
            if time.time() < self._lockdown_until:
                remaining_hours = (self._lockdown_until - time.time()) / 3600
                logger.warning("RiskManager | Lockdown active — %.1fh remaining", remaining_hours)
                return AllocationDecision(
                    action="HOLD",
                    symbol=market_data.get("symbol", "UNKNOWN") if market_data else "UNKNOWN",
                    allocation_pct=0.0, stop_loss=0.0,
                    reasoning={"halted": True, "reason": "drawdown_lockdown", "lockdown_remaining_hours": round(remaining_hours, 1)},
                )
            self._trading_halted = False
            self._lockdown_until = 0.0
            logger.info("RiskManager | Lockdown expired — resuming")

        if market_data is None:
            market_data = {}
        symbol = market_data.get("symbol", "UNKNOWN")
        price = market_data.get("price", 0.0)
        pred_dir = (prediction or {}).get("direction", "Neutral")
        pred_conf = (prediction or {}).get("confidence", 0.0)
        ctx_align = (context or {}).get("signal_alignment", "neutral")
        vol_mult = (volatility or {}).get("risk_multiplier", 1.0)
        vol_regime = (volatility or {}).get("volatility_regime", "mean_reverting")

        reasoning: Dict[str, object] = {
            "inputs": {
                "prediction": {"direction": pred_dir, "confidence": pred_conf},
                "context": {"alignment": ctx_align},
                "volatility": {"regime": vol_regime, "multiplier": vol_mult},
                "quoted_price": price,
            }
        }

        if not isinstance(pred_conf, (int, float)):
            pred_conf = 0.0
        if pred_conf < self.limits.min_confidence_threshold:
            logger.info("RiskManager | confidence=%.4f < min=%.4f -> HOLD", pred_conf, self.limits.min_confidence_threshold)
            return AllocationDecision(action="HOLD", symbol=symbol, allocation_pct=0.0, stop_loss=0.0,
                reasoning={**reasoning, "deny_reason": "low_confidence"})

        direction = "HOLD"
        if isinstance(pred_dir, str) and isinstance(ctx_align, str):
            if pred_dir.lower() == "bullish" and ctx_align == "bullish":
                direction = "BUY"
            elif pred_dir.lower() == "bearish" and ctx_align == "bearish":
                direction = "SELL"

        if direction == "HOLD":
            return AllocationDecision(action="HOLD", symbol=symbol, allocation_pct=0.0, stop_loss=0.0,
                reasoning={**reasoning, "deny_reason": "no_consensus"})

        if not isinstance(vol_mult, (int, float)):
            vol_mult = 1.0

        kelly_fraction = self._kelly_criterion(pred_conf, vol_regime if isinstance(vol_regime, str) else "mean_reverting")
        base_allocation = self.limits.max_asset_allocation * vol_mult
        final_allocation = base_allocation * kelly_fraction
        final_allocation = min(final_allocation, self.limits.max_asset_allocation)

        fill_price = self._estimate_fill_price(direction, price)
        slippage_bps_used = abs(fill_price - price) / price * 10000 if price > 0 else 0

        risk_amount_notional = self.limits.max_risk_per_trade * self._peak_value
        risk_limited_notional = risk_amount_notional / (1.0 + slippage_bps_used / 10000.0) if fill_price > 0 else 0.0
        risk_limited_alloc = risk_limited_notional / fill_price if fill_price > 0 else 0.0
        final_allocation = min(final_allocation, risk_limited_alloc)

        if not isinstance(price, (int, float)):
            price = 0.0
        stop_loss = fill_price * (1.0 - self.limits.trailing_stop_loss)

        reasoning["decision"] = {
            "action": direction,
            "allocation_pct": round(final_allocation, 4),
            "stop_loss": round(stop_loss, 2),
            "theoretical_price": round(price, 2),
            "estimated_fill_price": round(fill_price, 2),
            "slippage_bps": round(slippage_bps_used, 2),
            "base_allocation": round(base_allocation, 4),
            "volatility_multiplier": vol_mult,
            "kelly_fraction": round(kelly_fraction, 4),
        }

        logger.info(
            "RiskManager | action=%s alloc=%.4f fill=%.2f (quoted=%.2f) slip=%.1fbps stop=%.2f reasoning=%s",
            direction, final_allocation, fill_price, price, slippage_bps_used, stop_loss, reasoning,
        )

        return AllocationDecision(
            action=direction, symbol=symbol,
            allocation_pct=round(final_allocation, 4),
            stop_loss=round(stop_loss, 2),
            reasoning=reasoning,
        )

    @staticmethod
    def _kelly_criterion(confidence: float, regime: str) -> float:
        p = max(0.0, min(1.0, confidence))
        q = 1.0 - p
        b = 1.5
        kelly = ((b * p) - q) / b if b > 0 else 0.0
        kelly = max(0.0, kelly)
        if regime == "high_vol_chaos":
            kelly *= 0.3
        elif regime == "low_vol_trend":
            kelly *= 0.6
        else:
            kelly *= 0.5
        return max(0.05, min(0.50, kelly))
