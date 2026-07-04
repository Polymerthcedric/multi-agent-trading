from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from engine.state import MarketState, STATE_DIM
from engine.search_tree import PathSearchTree, heuristic_simulator
from engine.evaluator import StateEvaluator

logger = logging.getLogger(__name__)

SEARCH_METRICS_FILE = os.path.join("logs", "search_metrics.json")


@dataclass
class SearchMetrics:
    timestamp: float = 0.0
    symbol: str = ""
    best_action: str = "HOLD"
    score: float = 0.0
    search_depth: int = 0
    simulations_run: int = 0
    search_time_ms: float = 0.0
    price: float = 0.0
    position: float = 0.0
    portfolio_value: float = 0.0
    drawdown: float = 0.0
    volatility_index: float = 0.0


class SearchEngine:
    def __init__(
        self,
        max_depth: int = 5,
        n_simulations: int = 100,
        time_limit_ms: float = 3000.0,
        noise_scale: float = 0.015,
    ) -> None:
        self.evaluator = StateEvaluator()
        self.tree = PathSearchTree(
            evaluator_fn=self.evaluator.evaluate,
            simulator_fn=heuristic_simulator,
            max_depth=max_depth,
            n_simulations=n_simulations,
            time_limit_ms=time_limit_ms,
            noise_scale=noise_scale,
        )
        self._metrics_history: deque = deque(maxlen=1000)
        self._states: Dict[str, MarketState] = {}

    async def update_state(self, symbol: str, market_data: Dict[str, float]) -> MarketState:
        prev = self._states.get(symbol)
        state = MarketState.from_market_data(symbol, market_data, state=prev)
        self._states[symbol] = state
        return state

    async def search_best_action(self, symbol: str) -> Tuple[str, float, Dict]:
        state = self._states.get(symbol)
        if state is None:
            return "HOLD", 0.0, {"error": "no_state"}

        vec = state.to_vector()
        start = time.time()
        best_action, best_score, best_node = self.tree.search(vec)
        elapsed = (time.time() - start) * 1000.0

        root = getattr(self.tree, '_root', None)
        sim_count = sum(c.visits for c in root.children) if root and root.children else 0

        metrics = SearchMetrics(
            timestamp=time.time(),
            symbol=symbol,
            best_action=best_action,
            score=round(best_score, 4),
            search_depth=self.tree.max_depth,
            simulations_run=sim_count,
            search_time_ms=round(elapsed, 1),
            price=state.price,
            position=state.position,
            portfolio_value=state.portfolio_value,
            drawdown=round(state.drawdown_pct, 4),
            volatility_index=round(state.volatility_index, 4),
        )
        self._metrics_history.append(metrics)

        logger.info(
            "SearchEngine | %s action=%s score=%.4f sims=%d depth=%d time=%.1fms price=%.2f",
            symbol, best_action, best_score, sim_count, self.tree.max_depth, elapsed, state.price,
        )

        metrics_dict = asdict(metrics)
        metrics_dict["direction_tracker"] = self.tree.direction_tracker.report()
        return best_action, best_score, metrics_dict

    async def execute_action(
        self,
        symbol: str,
        action: str,
        broker: object,
        price: float,
        portfolio_value: float,
        allocation_pct: float = 0.0,
    ) -> object:
        if action == "HOLD" or action == "ROOT":
            return None
        action_map = {"BUY_LIMIT": "buy", "SELL_LIMIT": "sell", "RISK_CLOSE": "sell"}
        side = action_map.get(action, "hold")
        if side == "hold":
            return None
        if action == "RISK_CLOSE":
            state = self._states.get(symbol)
            allocation_pct = 1.0 if state and state.position != 0 else 0.0
        elif allocation_pct <= 0:
            allocation_pct = min(0.25, portfolio_value * 0.02 / (price if price > 0 else 1))
        result = await broker.execute_action(
            action={"buy": 1, "sell": 2}.get(side, 0),
            symbol=symbol,
            price=price,
            allocation_pct=allocation_pct,
            portfolio_value=portfolio_value,
        )
        if result and result.status == "filled":
            state = self._states.get(symbol)
            if state:
                if side == "buy":
                    size = (portfolio_value * allocation_pct) / price if price > 0 else 0.0
                    new_state = state.simulate_step(action, price, size)
                elif side == "sell":
                    size = state.position if action == "RISK_CLOSE" else (portfolio_value * allocation_pct) / price if price > 0 else 0.0
                    new_state = state.simulate_step(action, price, min(size, state.position))
                self._states[symbol] = new_state
                logger.info("SearchEngine | executed %s %s -> position=%.6f", action, symbol, new_state.position)
        return result

    def save_metrics(self) -> None:
        os.makedirs("logs", exist_ok=True)
        if self._metrics_history:
            data = [asdict(m) for m in list(self._metrics_history)[-500:]]
            fd, tmp = tempfile.mkstemp(suffix=".json", dir="logs")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, SEARCH_METRICS_FILE)
            except Exception:
                os.unlink(tmp)
                raise
            logger.info("SearchEngine | saved %d metrics to %s", len(data), SEARCH_METRICS_FILE)

    def get_latest_metrics(self, n: int = 10) -> List[Dict]:
        return [asdict(m) for m in self._metrics_history[-n:]]

    def get_state(self, symbol: str) -> Optional[MarketState]:
        return self._states.get(symbol)
