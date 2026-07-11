from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class VolatilityResult:
    agent: str = "volatility_agent"
    atr: float = 0.0
    implied_volatility: float = 0.0
    risk_multiplier: float = 1.0
    volatility_regime: str = "normal"
    z_score: float = 0.0
    reasoning: Dict[str, object] = field(default_factory=dict)


class VolatilityAgent:
    name: str = "volatility_agent"

    def __init__(self, lookback: int = 20) -> None:
        self._lookback = lookback
        self._price_history: List[float] = []
        self._low_vol_threshold = 0.15
        self._high_vol_threshold = 0.35

    async def analyze(self, market_data: Dict[str, float]) -> VolatilityResult:
        price = market_data.get("price", 0.0)
        high = market_data.get("high", price * 1.01)
        low = market_data.get("low", price * 0.99)
        atr_from_data = market_data.get("atr", 0.0)

        self._price_history.append(price)
        if len(self._price_history) > self._lookback:
            self._price_history.pop(0)

        atr = atr_from_data if atr_from_data > 0 else (high - low)
        if len(self._price_history) >= 2:
            prev = self._price_history[-2]
            atr = max(atr, abs(high - prev), abs(low - prev))

        z_score = 0.0
        iv = 0.0
        if len(self._price_history) >= 5:
            returns = [
                (self._price_history[i] - self._price_history[i - 1]) / self._price_history[i - 1]
                for i in range(1, len(self._price_history))
                if self._price_history[i - 1] > 0
            ]
            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_ret = variance ** 0.5
                iv = std_ret * (252 ** 0.5)
                if std_ret > 0 and len(returns) > 1:
                    z_score = (returns[-1] - mean_ret) / std_ret
        else:
            iv = 0.20

        if iv > self._high_vol_threshold or z_score > 1.5:
            volatility_regime = "high_vol_chaos"
            risk_multiplier = max(0.3, 1.0 - abs(z_score) * 0.12)
        elif iv < self._low_vol_threshold and z_score < -0.5:
            volatility_regime = "low_vol_trend"
            risk_multiplier = min(1.5, 1.0 + abs(z_score) * 0.08)
        else:
            volatility_regime = "mean_reverting"
            risk_multiplier = 1.0

        reasoning = {
            "atr": round(atr, 4),
            "implied_volatility": round(iv, 4),
            "volatility_regime": volatility_regime,
            "z_score": round(z_score, 4),
            "risk_multiplier": round(risk_multiplier, 4),
            "price_history_count": len(self._price_history),
            "low_vol_threshold": self._low_vol_threshold,
            "high_vol_threshold": self._high_vol_threshold,
        }

        logger.info(
            "VolatilityAgent | atr=%.4f iv=%.4f regime=%s z=%.2f multiplier=%.4f",
            atr, iv, volatility_regime, z_score, risk_multiplier,
        )

        return VolatilityResult(
            agent=self.name,
            atr=round(atr, 4),
            implied_volatility=round(iv, 4),
            risk_multiplier=round(risk_multiplier, 4),
            volatility_regime=volatility_regime,
            z_score=round(z_score, 4),
            reasoning=reasoning,
        )
