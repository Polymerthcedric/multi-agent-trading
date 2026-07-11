from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    agent: str = "context_agent"
    regime: str = "neutral"
    signal_alignment: str = "neutral"
    support_level: float = 0.0
    resistance_level: float = 0.0
    trend_strength: float = 0.0
    reasoning: Dict[str, object] = field(default_factory=dict)


class ContextAgent:
    name: str = "context_agent"

    def __init__(self, lookback: int = 20) -> None:
        self._price_history: List[float] = []
        self._lookback = lookback

    async def analyze(self, market_data: Dict[str, float]) -> ContextResult:
        price = market_data.get("price", 0.0)
        support = market_data.get("historical_support", price * 0.97)
        resistance = market_data.get("historical_resistance", price * 1.03)
        adx = market_data.get("adx", 0.0)
        rsi = market_data.get("rsi", 50.0)

        self._price_history.append(price)
        if len(self._price_history) > self._lookback:
            self._price_history.pop(0)

        regime = self._evaluate_regime(price)
        trend_strength = self._compute_trend_strength()

        distance_to_support = abs(price - support) / price if price > 0 else 0.0
        distance_to_resistance = abs(price - resistance) / price if price > 0 else 0.0

        proximity_threshold = 0.02
        near_support = distance_to_support < proximity_threshold
        near_resistance = distance_to_resistance < proximity_threshold

        if near_support and regime in ("neutral", "bullish"):
            signal_alignment = "bullish"
        elif near_resistance and regime in ("neutral", "bearish"):
            signal_alignment = "bearish"
        elif regime == "bullish" and rsi < 65:
            signal_alignment = "bullish"
        elif regime == "bearish" and rsi > 35:
            signal_alignment = "bearish"
        else:
            signal_alignment = "neutral"

        reasoning = {
            "price": price,
            "support": support,
            "resistance": resistance,
            "regime": regime,
            "signal_alignment": signal_alignment,
            "trend_strength": round(trend_strength, 4),
            "near_support": near_support,
            "near_resistance": near_resistance,
            "distance_to_support_pct": round(distance_to_support * 100, 2),
            "distance_to_resistance_pct": round(distance_to_resistance * 100, 2),
            "adx": adx,
            "rsi": rsi,
        }

        logger.info(
            "ContextAgent | regime=%s alignment=%s trend=%.2f support=%.2f resistance=%.2f",
            regime, signal_alignment, trend_strength, support, resistance,
        )

        return ContextResult(
            agent=self.name,
            regime=regime,
            signal_alignment=signal_alignment,
            support_level=support,
            resistance_level=resistance,
            trend_strength=round(trend_strength, 4),
            reasoning=reasoning,
        )

    def _evaluate_regime(self, price: float) -> str:
        if len(self._price_history) < 5:
            return "neutral"
        recent = self._price_history[-5:]
        avg = sum(recent) / len(recent)
        older = self._price_history[:max(1, len(self._price_history) - 5)]
        older_avg = sum(older) / len(older) if older else avg

        if price > avg * 1.005 and avg > older_avg:
            return "bullish"
        elif price < avg * 0.995 and avg < older_avg:
            return "bearish"
        elif price > avg * 1.01:
            return "bullish"
        elif price < avg * 0.99:
            return "bearish"
        return "neutral"

    def _compute_trend_strength(self) -> float:
        if len(self._price_history) < 5:
            return 0.0
        returns = [
            (self._price_history[i] - self._price_history[i - 1]) / self._price_history[i - 1]
            for i in range(1, len(self._price_history))
            if self._price_history[i - 1] > 0
        ]
        if not returns:
            return 0.0
        mean_r = sum(returns) / len(returns)
        positive = sum(1 for r in returns if r > 0)
        consistency = positive / len(returns) if returns else 0.5
        trend = abs(mean_r) * 100
        return min(1.0, trend * consistency)
