"""
Bull/Bear Debate Engine — Inspired by TradingAgents (AAAI 2025).

Two virtual researchers argue FOR and AGAINST a trade.
The debate outcome adjusts the final confidence score.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class DebateArgument:
    side: str = "bull"
    strength: float = 0.0
    points: list = field(default_factory=list)
    confidence_modifier: float = 0.0


@dataclass
class DebateResult:
    symbol: str = ""
    bull_argument: Optional[DebateArgument] = None
    bear_argument: Optional[DebateArgument] = None
    winner: str = "neutral"
    adjusted_confidence: float = 0.0
    original_confidence: float = 0.0
    reasoning: Dict = field(default_factory=dict)


class BullBearDebate:
    """
    Structured debate between Bull and Bear researchers.
    Each examines the same data and argues their case.
    The stronger argument wins and adjusts the confidence.
    """

    def __init__(self) -> None:
        pass

    def _build_bull_case(
        self, prediction: Dict, context: Dict, volatility: Dict,
        sentiment: Optional[Dict], market_data: Dict,
    ) -> DebateArgument:
        points = []
        strength = 0.0

        pred_dir = prediction.get("direction", "Neutral")
        pred_conf = prediction.get("confidence", 0.0)
        if pred_dir.lower() == "bullish":
            points.append(f"Technical analysis predicts BULLISH (conf={pred_conf:.2%})")
            strength += pred_conf * 0.3

        ctx_align = context.get("signal_alignment", "neutral")
        if ctx_align == "bullish":
            regime = context.get("regime", "unknown")
            points.append(f"Market regime is {regime}, signals aligned bullish")
            strength += 0.25

        vol_regime = volatility.get("volatility_regime", "mean_reverting")
        risk_mult = volatility.get("risk_multiplier", 1.0)
        if vol_regime == "low_vol_trend":
            points.append(f"Low volatility trending environment (risk_mult={risk_mult:.2f})")
            strength += 0.2
        elif vol_regime == "mean_reverting":
            points.append("Mean-reverting environment — dips are buying opportunities")
            strength += 0.15

        if sentiment:
            sent_label = sentiment.get("label", "neutral")
            sent_score = sentiment.get("score", 0.0)
            if sent_label == "bullish":
                points.append(f"News sentiment is bullish (score={sent_score:.3f})")
                strength += 0.15
            elif sent_label == "neutral":
                points.append("News sentiment neutral — no headwinds")
                strength += 0.05

        price = market_data.get("price", 0)
        rsi = market_data.get("rsi", 50)
        if rsi < 40:
            points.append(f"RSI oversold at {rsi:.1f} — bounce likely")
            strength += 0.1
        elif 40 <= rsi <= 60:
            points.append(f"RSI neutral at {rsi:.1f} — room to run")
            strength += 0.05

        sma = market_data.get("sma", 0)
        if price > sma > 0:
            points.append(f"Price ${price:,.2f} above SMA ${sma:,.2f}")
            strength += 0.1

        strength = min(1.0, strength)
        conf_mod = strength * 0.15

        return DebateArgument(
            side="bull", strength=round(strength, 4),
            points=points, confidence_modifier=round(conf_mod, 4),
        )

    def _build_bear_case(
        self, prediction: Dict, context: Dict, volatility: Dict,
        sentiment: Optional[Dict], market_data: Dict,
    ) -> DebateArgument:
        points = []
        strength = 0.0

        pred_dir = prediction.get("direction", "Neutral")
        pred_conf = prediction.get("confidence", 0.0)
        if pred_dir.lower() == "bearish":
            points.append(f"Technical analysis predicts BEARISH (conf={pred_conf:.2%})")
            strength += pred_conf * 0.3

        ctx_align = context.get("signal_alignment", "neutral")
        if ctx_align == "bearish":
            regime = context.get("regime", "unknown")
            points.append(f"Market regime is {regime}, signals aligned bearish")
            strength += 0.25

        vol_regime = volatility.get("volatility_regime", "mean_reverting")
        risk_mult = volatility.get("risk_multiplier", 1.0)
        if vol_regime == "high_vol_chaos":
            points.append(f"HIGH VOLATILITY CHAOS (risk_mult={risk_mult:.2f}) — stay out")
            strength += 0.3
        elif vol_regime == "mean_reverting":
            points.append("Mean-reverting — rallies are selling opportunities")
            strength += 0.15

        if sentiment:
            sent_label = sentiment.get("label", "neutral")
            sent_score = sentiment.get("score", 0.0)
            if sent_label == "bearish":
                points.append(f"News sentiment is bearish (score={sent_score:.3f})")
                strength += 0.2
            elif sent_label == "neutral":
                points.append("News sentiment neutral — no catalysts")
                strength += 0.05

        price = market_data.get("price", 0)
        rsi = market_data.get("rsi", 50)
        if rsi > 70:
            points.append(f"RSI overbought at {rsi:.1f} — pullback likely")
            strength += 0.15
        elif rsi > 60:
            points.append(f"RSI elevated at {rsi:.1f} — limited upside")
            strength += 0.05

        sma = market_data.get("sma", 0)
        if price < sma < 0:
            points.append(f"Price ${price:,.2f} below SMA ${sma:,.2f}")
            strength += 0.1

        atr = market_data.get("atr", 0)
        if atr > 0 and price > 0:
            atr_pct = atr / price
            if atr_pct > 0.02:
                points.append(f"ATR {atr_pct:.2%} of price — elevated risk")
                strength += 0.1

        strength = min(1.0, strength)
        conf_mod = strength * 0.15

        return DebateArgument(
            side="bear", strength=round(strength, 4),
            points=points, confidence_modifier=round(conf_mod, 4),
        )

    def debate(
        self, symbol: str, prediction: Dict, context: Dict,
        volatility: Dict, sentiment: Optional[Dict], market_data: Dict,
        original_confidence: float,
    ) -> DebateResult:
        bull = self._build_bull_case(prediction, context, volatility, sentiment, market_data)
        bear = self._build_bear_case(prediction, context, volatility, sentiment, market_data)

        if bull.strength > bear.strength:
            winner = "bull"
            adjusted = original_confidence + bull.confidence_modifier
        elif bear.strength > bull.strength:
            winner = "bear"
            adjusted = original_confidence - bear.confidence_modifier
        else:
            winner = "neutral"
            adjusted = original_confidence

        adjusted = max(0.0, min(1.0, adjusted))

        result = DebateResult(
            symbol=symbol,
            bull_argument=bull,
            bear_argument=bear,
            winner=winner,
            adjusted_confidence=round(adjusted, 4),
            original_confidence=original_confidence,
            reasoning={
                "bull_strength": bull.strength,
                "bear_strength": bear.strength,
                "bull_points": bull.points,
                "bear_points": bear.points,
                "winner": winner,
                "confidence_change": round(adjusted - original_confidence, 4),
            },
        )

        logger.info(
            "Debate | %s bull=%.3f bear=%.3f winner=%s conf %.3f -> %.3f",
            symbol, bull.strength, bear.strength, winner,
            original_confidence, adjusted,
        )

        return result
