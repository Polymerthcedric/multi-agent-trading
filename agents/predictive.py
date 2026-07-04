from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    agent: str = "predictive_agent"
    direction: str = "Neutral"
    confidence: float = 0.0
    reasoning: Dict[str, object] = field(default_factory=dict)


class PredictiveAgent:
    name: str = "predictive_agent"

    async def analyze(self, market_data: Dict[str, float]) -> PredictionResult:
        sma = market_data.get("sma", 0.0)
        rsi = market_data.get("rsi", 50.0)
        ema = market_data.get("ema", 0.0)
        price = market_data.get("price", 0.0)

        bullish_score = 0.0
        bearish_score = 0.0

        if rsi < 30:
            bullish_score += 0.4
        elif rsi > 70:
            bearish_score += 0.4
        else:
            bullish_score += 0.2
            bearish_score += 0.2

        if ema > sma:
            bullish_score += 0.3
        else:
            bearish_score += 0.3

        if price > sma:
            bullish_score += 0.3
        else:
            bearish_score += 0.3

        total = bullish_score + bearish_score
        net = 0.0
        if total == 0:
            direction = "Neutral"
            confidence = 0.0
        else:
            net = bullish_score - bearish_score
            if net > 0.2:
                direction = "Bullish"
                confidence = bullish_score / total
            elif net < -0.2:
                direction = "Bearish"
                confidence = bearish_score / total
            else:
                direction = "Neutral"
                confidence = max(bullish_score, bearish_score) / total

        reasoning = {
            "indicators": {"sma": sma, "rsi": rsi, "ema": ema, "price": price},
            "scores": {"bullish": round(bullish_score, 4), "bearish": round(bearish_score, 4)},
            "net_score": round(net, 4),
        }

        logger.info(
            "PredictiveAgent | direction=%s confidence=%.4f reasoning=%s",
            direction, confidence, reasoning,
        )

        return PredictionResult(
            agent=self.name,
            direction=direction,
            confidence=round(confidence, 4),
            reasoning=reasoning,
        )
