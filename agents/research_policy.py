from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Dict, Optional

from agents.context import ContextAgent
from agents.debate import BullBearDebate
from agents.predictive import PredictiveAgent
from agents.risk_manager import consensus_action
from agents.volatility import VolatilityAgent
from engine.policy import PolicyDecision, PolicyRiskConfig, PortfolioSnapshot


class MultiAgentResearchPolicy:
    """Deterministic, market-only policy shared by research and paper mode."""

    name = "market-only multi-agent policy; sentiment excluded without timestamped history"

    def __init__(
        self,
        symbol: str = "",
        risk_config: Optional[PolicyRiskConfig] = None,
    ) -> None:
        self.symbol = symbol
        self.risk_config = risk_config or PolicyRiskConfig()
        self.predictive = PredictiveAgent()
        self.context = ContextAgent()
        self.volatility = VolatilityAgent()
        self.debate = BullBearDebate()
        self._last_processed_timestamp: Optional[float] = None

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def _hold(
        self,
        reason: str,
        *,
        signal: str = "HOLD",
        confidence: float = 0.0,
        stop_loss: float = 0.0,
        agent_outputs: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            signal=signal,
            confidence=confidence,
            stop_loss=stop_loss,
            reasons=(reason,),
            agent_outputs=agent_outputs or {},
        )

    def decide(
        self,
        market_data: Dict[str, Any],
        portfolio: Optional[PortfolioSnapshot] = None,
    ) -> PolicyDecision:
        portfolio = portfolio or PortfolioSnapshot()
        price = self._number(market_data.get("price"))
        if price is None or price <= 0:
            return self._hold("invalid_or_missing_price")
        if market_data.get("is_stale") is True:
            return self._hold("stale_market_data")
        if market_data.get("data_quality_ok") is False:
            return self._hold("market_data_quality_failure")
        timestamp = self._number(market_data.get("timestamp"))
        if timestamp is not None:
            if self._last_processed_timestamp is not None and timestamp <= self._last_processed_timestamp:
                return self._hold("duplicate_or_out_of_order_market_snapshot")
            self._last_processed_timestamp = timestamp

        prediction = self.predictive.analyze_sync(market_data)
        context = self.context.analyze_sync(market_data)
        volatility = self.volatility.analyze_sync(market_data)
        debate = self.debate.debate(
            symbol=self.symbol,
            prediction={
                "direction": prediction.direction,
                "confidence": prediction.confidence,
            },
            context={
                "regime": context.regime,
                "signal_alignment": context.signal_alignment,
            },
            volatility={
                "volatility_regime": volatility.volatility_regime,
                "risk_multiplier": volatility.risk_multiplier,
            },
            sentiment=None,
            market_data=market_data,
            original_confidence=prediction.confidence,
        )
        agent_outputs = {
            "prediction": asdict(prediction),
            "context": asdict(context),
            "volatility": asdict(volatility),
            "debate": debate.reasoning,
        }
        signal = consensus_action(
            prediction.direction,
            context.signal_alignment,
            prediction.confidence,
            self.risk_config.min_confidence,
        )
        confidence = self._number(prediction.confidence) or 0.0
        position = self._number(portfolio.position_quantity)
        equity = self._number(portfolio.equity)
        cash = self._number(portfolio.cash)
        exposure = self._number(portfolio.total_exposure_pct)
        daily_pnl = self._number(portfolio.daily_pnl_pct)
        weekly_pnl = self._number(portfolio.weekly_pnl_pct)
        drawdown = self._number(portfolio.drawdown_pct)
        if None in (position, equity, cash, exposure, daily_pnl, weekly_pnl, drawdown):
            return self._hold(
                "invalid_portfolio_state",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        assert position is not None and equity is not None and cash is not None
        assert exposure is not None and daily_pnl is not None
        assert weekly_pnl is not None and drawdown is not None
        if equity <= 0 or cash < 0 or position < 0:
            return self._hold(
                "invalid_portfolio_state",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )

        risk = self.risk_config
        active_stop = self._number(portfolio.active_stop_loss) or 0.0
        atr = self._number(market_data.get("atr"))
        stop_distance = (
            atr * risk.stop_atr_multiple if atr is not None and atr > 0 else 0.0
        )
        trailing_stop = (
            max(active_stop, price - stop_distance)
            if position > 0 and stop_distance > 0 else active_stop
        )
        if position > 0 and drawdown <= -risk.kill_switch_drawdown:
            return PolicyDecision(
                action="SELL",
                allocation_pct=1.0,
                stop_loss=active_stop,
                signal=signal,
                confidence=confidence,
                reasons=("kill_switch_liquidation",),
                agent_outputs=agent_outputs,
            )
        low = self._number(market_data.get("low"))
        if position > 0 and active_stop > 0 and (
            price <= active_stop or (low is not None and low <= active_stop)
        ):
            return PolicyDecision(
                action="SELL",
                allocation_pct=1.0,
                stop_loss=active_stop,
                signal=signal,
                confidence=confidence,
                reasons=("protective_stop_triggered",),
                agent_outputs=agent_outputs,
            )
        if signal == "SELL":
            if position > 0:
                return PolicyDecision(
                    action="SELL",
                    allocation_pct=1.0,
                    stop_loss=active_stop,
                    signal=signal,
                    confidence=confidence,
                    reasons=("bearish_consensus_exit",),
                    agent_outputs=agent_outputs,
                )
            return self._hold(
                "short_selling_disabled",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if signal != "BUY":
            return self._hold(
                "no_bullish_consensus",
                confidence=confidence,
                stop_loss=trailing_stop,
                agent_outputs=agent_outputs,
            )
        if position > 0:
            return PolicyDecision(
                stop_loss=trailing_stop,
                stop_distance=stop_distance,
                signal=signal,
                confidence=confidence,
                reasons=("existing_long_position",),
                agent_outputs=agent_outputs,
            )
        if not portfolio.allow_new_positions:
            return self._hold(
                "portfolio_risk_gate",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if portfolio.daily_trades >= risk.max_trades_per_day:
            return self._hold(
                "daily_trade_limit",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if daily_pnl <= -risk.daily_loss_limit:
            return self._hold(
                "daily_loss_limit",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if weekly_pnl <= -risk.weekly_loss_limit:
            return self._hold(
                "weekly_loss_limit",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if drawdown <= -risk.kill_switch_drawdown:
            return self._hold(
                "kill_switch_no_new_positions",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )

        risk_multiplier = self._number(volatility.risk_multiplier)
        if atr is None or atr <= 0:
            return self._hold(
                "invalid_or_missing_atr",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        if risk_multiplier is None or risk_multiplier <= 0:
            return self._hold(
                "invalid_volatility_multiplier",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )

        stop_distance = atr * risk.stop_atr_multiple
        stop_fraction = stop_distance / price
        if stop_fraction <= 0 or not math.isfinite(stop_fraction):
            return self._hold(
                "invalid_stop_distance",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        risk_budget_fraction = risk.max_risk_per_trade * min(1.0, risk_multiplier)
        risk_limited_allocation = risk_budget_fraction / stop_fraction
        cash_allocation = cash / equity
        exposure_allocation = risk.max_portfolio_exposure - exposure
        allocation = min(
            risk.max_asset_allocation,
            risk_limited_allocation,
            cash_allocation,
            exposure_allocation,
        )
        if allocation <= 0 or not math.isfinite(allocation):
            return self._hold(
                "no_risk_budget_available",
                signal=signal,
                confidence=confidence,
                agent_outputs=agent_outputs,
            )
        return PolicyDecision(
            action="BUY",
            allocation_pct=allocation,
            stop_loss=price - stop_distance,
            stop_distance=stop_distance,
            signal=signal,
            confidence=confidence,
            reasons=("bullish_consensus_risk_sized",),
            agent_outputs=agent_outputs,
        )
