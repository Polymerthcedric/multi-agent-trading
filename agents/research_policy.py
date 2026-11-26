from __future__ import annotations

from typing import Dict

from agents.context import ContextAgent
from agents.debate import BullBearDebate
from agents.predictive import PredictiveAgent
from agents.risk_manager import MIN_CONFIDENCE_THRESHOLD, consensus_action
from agents.volatility import VolatilityAgent


class MultiAgentResearchPolicy:
    """Market-data-only replay of the paper pipeline; historical news is excluded."""

    name = "market-only multi-agent policy; sentiment excluded without timestamped history"

    def __init__(self, symbol: str = "", confidence_threshold: float = MIN_CONFIDENCE_THRESHOLD):
        self.symbol = symbol
        self.confidence_threshold = confidence_threshold
        self.predictive = PredictiveAgent()
        self.context = ContextAgent()
        self.volatility = VolatilityAgent()
        self.debate = BullBearDebate()

    def decide(self, market_data: Dict[str, float]) -> str:
        prediction = self.predictive.analyze_sync(market_data)
        context = self.context.analyze_sync(market_data)
        volatility = self.volatility.analyze_sync(market_data)
        context_inputs = {
            "regime": context.regime,
            "signal_alignment": context.signal_alignment,
        }
        volatility_inputs = {
            "volatility_regime": volatility.volatility_regime,
            "risk_multiplier": volatility.risk_multiplier,
        }
        debate = self.debate.debate(
            symbol=self.symbol,
            prediction={
                "direction": prediction.direction,
                "confidence": prediction.confidence,
            },
            context=context_inputs,
            volatility=volatility_inputs,
            sentiment=None,
            market_data=market_data,
            original_confidence=prediction.confidence,
        )
        return consensus_action(
            prediction.direction,
            context.signal_alignment,
            debate.adjusted_confidence,
            self.confidence_threshold,
        )
