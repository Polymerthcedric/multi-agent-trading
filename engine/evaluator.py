from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05
MAX_DRAWDOWN_PENALTY = -0.15
ANNUAL_FACTOR = 252.0


class StateEvaluator:
    def __init__(
        self,
        risk_aversion: float = 3.0,
        drawdown_penalty: float = 2.0,
        position_conviction_bonus: float = 0.3,
    ) -> None:
        self.risk_aversion = risk_aversion
        self.drawdown_penalty = drawdown_penalty
        self.position_conviction_bonus = position_conviction_bonus

    def evaluate(self, state_vector: np.ndarray) -> float:
        score = 0.0
        components = {}

        price = max(state_vector[0] * 100000.0, 1.0)
        position_size = state_vector[1]
        cash = state_vector[3] * 100000.0
        portfolio_value = state_vector[4] * 100000.0
        rsi = state_vector[5] * 100.0
        momentum = state_vector[9] * 10.0
        adx = state_vector[10] * 100.0
        volatility = state_vector[14] * 2.0
        drawdown = state_vector[16]
        unrealized_pnl = state_vector[17] * 100000.0
        ret = state_vector[18]
        std_ret = state_vector[19]
        has_position = state_vector[20] > 0.5
        has_short = state_vector[21] > 0.5
        change_pct = state_vector[22]

        if std_ret > 0:
            sharpe = (ret - RISK_FREE_RATE / ANNUAL_FACTOR) / std_ret
        else:
            sharpe = 0.0
        score += sharpe * 1.5
        components["sharpe"] = sharpe * 1.5

        if volatility > 0:
            sortino = (ret - RISK_FREE_RATE / ANNUAL_FACTOR) / max(volatility * 0.01, 1e-6)
            score += sortino * 0.5
            components["sortino"] = sortino * 0.5

        if drawdown < 0:
            dd_penalty = drawdown * self.drawdown_penalty * 5.0
            if drawdown < MAX_DRAWDOWN_PENALTY:
                dd_penalty *= 3.0
            score += dd_penalty
            components["drawdown_penalty"] = dd_penalty

        if 40 <= rsi <= 60:
            score += 0.1
            components["rsi_safety"] = 0.1
        elif rsi > 80 or rsi < 20:
            score -= 0.3
            components["rsi_extreme_penalty"] = -0.3

        if adx > 25:
            score += 0.2
            components["trend_strength"] = 0.2

        if has_position or has_short:
            exposure = abs(position_size) * price / max(portfolio_value, 1.0)
            if exposure <= 0.25:
                score += 0.2
                components["position_sizing"] = 0.2
            elif exposure > 0.5:
                score -= 0.4
                components["overexposure_penalty"] = -0.4

        if momentum > 2.0 and has_position:
            score += self.position_conviction_bonus
            components["momentum_conviction"] = self.position_conviction_bonus
        if momentum < -2.0 and has_short:
            score += self.position_conviction_bonus * 0.5
            components["short_momentum"] = self.position_conviction_bonus * 0.5

        score += cash / max(portfolio_value, 1.0) * 0.1
        components["cash_reserve"] = cash / max(portfolio_value, 1.0) * 0.1

        if abs(change_pct) > 0.05:
            score -= abs(change_pct) * 2.0
            components["volatility_penalty"] = -abs(change_pct) * 2.0

        score = max(-10.0, min(10.0, score))
        return score

    def evaluate_path(self, path_vectors: List[np.ndarray]) -> float:
        if not path_vectors:
            return -5.0
        scores = [self.evaluate(v) for v in path_vectors]
        weights = [1.0 + 0.1 * i for i in range(len(scores))]
        total_w = sum(weights)
        weighted = sum(s * w for s, w in zip(scores, weights)) / total_w if total_w > 0 else scores[-1]

        terminal = path_vectors[-1]
        drawdown = terminal[16]
        if drawdown < MAX_DRAWDOWN_PENALTY:
            weighted -= 5.0
        pnl = terminal[17] * 100000.0
        pnl_penalty = 0.0
        if pnl < -1000.0:
            pnl_penalty = max(-5.0, min(0.0, pnl / 50000.0))
        weighted += pnl_penalty
        return max(-10.0, min(10.0, weighted))


# UNUSED — kept for reference; was an earlier NNUE-style wrapper
def nnue_forward(state_vector: np.ndarray) -> float:
    evaluator = StateEvaluator()
    return evaluator.evaluate(state_vector)


# UNUSED — kept for reference; factory function superseded by direct instantiation
def create_evaluator() -> StateEvaluator:
    return StateEvaluator()
