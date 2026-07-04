from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_holding_period: float = 0.0


class SelfLearningAgent:
    """Scaffolding placeholder — PPO/RL training is not yet implemented.
    The class provides stub methods that log but perform no learning.
    """

    def __init__(
        self,
        state_dim: int = 5,
        action_dim: int = 3,
        sliding_window: int = 100,
        learning_rate: float = 0.001,
    ) -> None:
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.sliding_window = sliding_window
        self.learning_rate = learning_rate
        self.performance_history: List[PerformanceMetrics] = []
        self._policy_weights: np.ndarray = np.zeros((state_dim, action_dim), dtype=np.float32)

    async def predict(self, state: np.ndarray) -> int:
        if state.shape[0] != self.state_dim:
            logger.warning("SelfLearner | state dim mismatch: got %d, expected %d", state.shape[0], self.state_dim)
            return 0
        scores = state @ self._policy_weights
        action = int(np.argmax(scores))
        return action

    def train(self, episodes: int = 100) -> None:
        logger.info("SelfLearner | PPO training placeholder — %d episodes (no-op)", episodes)

    def update_policy(self, states: np.ndarray, actions: np.ndarray, advantages: np.ndarray) -> None:
        logger.debug("SelfLearner | policy update stub — shape=%s", states.shape)

    def compute_performance(self, trades: List[Dict]) -> PerformanceMetrics:
        if not trades:
            return PerformanceMetrics()

        returns = [t.get("return", 0.0) for t in trades if isinstance(t.get("return"), (int, float))]
        if len(returns) < 2:
            return PerformanceMetrics(total_trades=len(trades))

        avg_return = sum(returns) / len(returns)
        variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
        std_return = math.sqrt(variance) if variance > 0 else 0.0

        sharpe = (avg_return / std_return * math.sqrt(252)) if std_return > 0 else 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = (peak - cumulative) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        total_return = sum(returns)
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if returns else 0.0

        metrics = PerformanceMetrics(
            sharpe_ratio=round(sharpe, 4),
            max_drawdown=round(max_dd, 4),
            total_return=round(total_return, 4),
            win_rate=round(win_rate, 4),
            total_trades=len(trades),
        )

        self.performance_history.append(metrics)
        logger.info(
            "SelfLearner | sharpe=%.4f max_dd=%.4f ret=%.4f win_rate=%.4f trades=%d",
            sharpe, max_dd, total_return, win_rate, len(trades),
        )

        return metrics
