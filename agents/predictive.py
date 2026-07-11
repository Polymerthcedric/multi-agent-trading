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
        macd = market_data.get("macd", 0.0)
        macd_signal = market_data.get("macd_signal", 0.0)
        adx = market_data.get("adx", 0.0)
        bb_upper = market_data.get("bb_upper", price * 1.05)
        bb_lower = market_data.get("bb_lower", price * 0.95)
        volume = market_data.get("volume", 0.0)
        atr = market_data.get("atr", 0.0)
        momentum = market_data.get("momentum", 0.0)

        bullish_score = 0.0
        bearish_score = 0.0

        if rsi < 30:
            bullish_score += 0.25
        elif rsi > 70:
            bearish_score += 0.25
        elif rsi < 40:
            bullish_score += 0.10
        elif rsi > 60:
            bearish_score += 0.10
        else:
            bullish_score += 0.10
            bearish_score += 0.10

        if ema > sma and price > sma:
            bullish_score += 0.20
        elif ema < sma and price < sma:
            bearish_score += 0.20
        elif price > sma:
            bullish_score += 0.10
        elif price < sma:
            bearish_score += 0.10
        else:
            bullish_score += 0.05
            bearish_score += 0.05

        if macd > macd_signal:
            bullish_score += 0.20
        elif macd < macd_signal:
            bearish_score += 0.20

        if adx > 25:
            trend_strength = min(adx / 50.0, 1.0)
            if price > sma:
                bullish_score += 0.15 * trend_strength
            elif price < sma:
                bearish_score += 0.15 * trend_strength

        bb_range = bb_upper - bb_lower if bb_upper > bb_lower else 1.0
        bb_position = (price - bb_lower) / bb_range if bb_range > 0 else 0.5
        if bb_position < 0.2:
            bullish_score += 0.10
        elif bb_position > 0.8:
            bearish_score += 0.10

        if momentum > 0:
            bullish_score += 0.05
        elif momentum < 0:
            bearish_score += 0.05

        total = bullish_score + bearish_score
        net = 0.0
        if total == 0:
            direction = "Neutral"
            confidence = 0.0
        else:
            net = bullish_score - bearish_score
            if net > 0.15:
                direction = "Bullish"
                confidence = bullish_score / total
            elif net < -0.15:
                direction = "Bearish"
                confidence = bearish_score / total
            else:
                direction = "Neutral"
                confidence = max(bullish_score, bearish_score) / total

        reasoning = {
            "indicators": {
                "sma": sma, "rsi": rsi, "ema": ema, "price": price,
                "macd": macd, "macd_signal": macd_signal, "adx": adx,
                "bb_position": round(bb_position, 4), "momentum": momentum, "atr": atr,
            },
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
