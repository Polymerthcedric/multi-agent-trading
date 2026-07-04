from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    agent: str = "context_agent"
    regime: str = "neutral"
    signal_alignment: str = "neutral"
    support_level: float = 0.0
    resistance_level: float = 0.0
    reasoning: Dict[str, object] = field(default_factory=dict)


class ContextAgent:
    name: str = "context_agent"

    def __init__(self, lookback: int = 14) -> None:
        self._price_history: List[float] = []
        self._lookback = lookback

    async def analyze(self, market_data: Dict[str, float]) -> ContextResult:
        price = market_data.get("price", 0.0)
        support = market_data.get("historical_support", price * 0.95)
        resistance = market_data.get("historical_resistance", price * 1.05)

        self._price_history.append(price)
        if len(self._price_history) > self._lookback:
            self._price_history.pop(0)

        regime = self._evaluate_regime(price)

        distance_to_support = abs(price - support) / price if price > 0 else 0.0
        distance_to_resistance = abs(price - resistance) / price if price > 0 else 0.0

        proximity_threshold = 0.02
        near_support = distance_to_support < proximity_threshold
        near_resistance = distance_to_resistance < proximity_threshold

        if near_support and regime in ("neutral", "bullish"):
            signal_alignment = "bullish"
        elif near_resistance and regime in ("neutral", "bearish"):
            signal_alignment = "bearish"
        else:
            signal_alignment = "neutral"

        reasoning = {
            "price": price,
            "support": support,
            "resistance": resistance,
            "regime": regime,
            "signal_alignment": signal_alignment,
            "near_support": near_support,
            "near_resistance": near_resistance,
            "distance_to_support_pct": round(distance_to_support * 100, 2),
            "distance_to_resistance_pct": round(distance_to_resistance * 100, 2),
        }

        logger.info(
            "ContextAgent | regime=%s alignment=%s support=%.2f resistance=%.2f reasoning=%s",
            regime, signal_alignment, support, resistance, reasoning,
        )

        return ContextResult(
            agent=self.name,
            regime=regime,
            signal_alignment=signal_alignment,
            support_level=support,
            resistance_level=resistance,
            reasoning=reasoning,
        )

    def _evaluate_regime(self, price: float) -> str:
        if len(self._price_history) < 3:
            return "neutral"
        recent = self._price_history[-3:]
        avg = sum(recent) / len(recent)
        if price > avg * 1.01:
            return "bullish"
        elif price < avg * 0.99:
            return "bearish"
        return "neutral"
