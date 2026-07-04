from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

ACTIONS = ["HOLD", "BUY_LIMIT", "SELL_LIMIT", "RISK_CLOSE"]

# Named vector indices
PRICE_IDX = 0
CASH_IDX = 3
PORTFOLIO_IDX = 4
RSI_IDX = 5
MOMENTUM_IDX = 9
PNL_IDX = 17
POSITION_LONG_IDX = 20
POSITION_SHORT_IDX = 21


@dataclass
class MCTSNode:
    state_vector: np.ndarray
    action: str = "HOLD"
    parent: Optional[MCTSNode] = None
    children: List[MCTSNode] = field(default_factory=list)
    visits: int = 0
    value_sum: float = 0.0
    prior: float = 0.0
    depth: int = 0

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits > 0 else 0.0

    def ucb1_score(self, total_visits: int, exploration_c: float = 1.4) -> float:
        if self.visits == 0:
            return float("inf")
        exploitation = self.mean_value
        exploration = exploration_c * math.sqrt(math.log(total_visits + 1) / self.visits)
        return exploitation + exploration

    def best_child(self) -> Optional[MCTSNode]:
        if not self.children:
            return None
        total = sum(c.visits for c in self.children)
        return max(self.children, key=lambda c: c.ucb1_score(total))

    def best_action_child(self) -> Optional[MCTSNode]:
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.visits)


class DirectionMatchTracker:
    def __init__(self) -> None:
        self.total_rollouts: int = 0
        self.direction_matches: int = 0
        self.log: List[Dict] = []

    def record_rollout(self, sim_start_price: float, actual_next_price: float, action: str, score: float) -> None:
        self.total_rollouts += 1
        sim_dir = 0
        if sim_start_price > 0 and actual_next_price > 0:
            sim_dir = 1 if actual_next_price >= sim_start_price else -1
        action_dir = 0
        if action == "BUY_LIMIT":
            action_dir = 1
        elif action == "SELL_LIMIT":
            action_dir = -1
        matched = (sim_dir == action_dir and action_dir != 0)
        if matched:
            self.direction_matches += 1
        if self.total_rollouts <= 500:
            self.log.append({
                "rollout": self.total_rollouts, "action": action, "score": round(score, 4),
                "sim_start": round(sim_start_price, 2), "sim_end": round(actual_next_price, 2),
                "sim_dir": sim_dir, "action_dir": action_dir, "matched": matched,
            })

    @property
    def accuracy(self) -> float:
        if self.total_rollouts == 0:
            return 0.0
        return self.direction_matches / self.total_rollouts

    def report(self) -> Dict:
        return {
            "total_rollouts": self.total_rollouts,
            "direction_matches": self.direction_matches,
            "accuracy": round(self.accuracy, 4),
            "samples_logged": len(self.log),
        }


class PathSearchTree:
    def __init__(
        self,
        evaluator_fn: Callable,
        simulator_fn: Callable,
        max_depth: int = 5,
        n_simulations: int = 100,
        time_limit_ms: float = 5000.0,
        noise_scale: float = 0.01,
    ) -> None:
        self.evaluator_fn = evaluator_fn
        self.simulator_fn = simulator_fn
        self.max_depth = max_depth
        self.n_simulations = n_simulations
        self.time_limit_ms = time_limit_ms
        self.noise_scale = noise_scale
        self._root: Optional[MCTSNode] = None
        self.direction_tracker = DirectionMatchTracker()

    def search(self, root_state_vector: np.ndarray) -> Tuple[str, float, MCTSNode]:
        self._root = MCTSNode(state_vector=root_state_vector, action="ROOT", depth=0)
        deadline = time.time() + self.time_limit_ms / 1000.0
        sim_count = 0
        max_sim = min(self.n_simulations, 500)

        while sim_count < max_sim and time.time() < deadline:
            node = self._select(self._root)
            if node is None:
                break
            if node.depth < self.max_depth and node.visits > 0:
                node = self._expand(node)
            value = self._simulate(node)
            self._backpropagate(node, value)
            sim_count += 1

        if self._root and self._root.children:
            best_node = self._root.best_action_child()
            if best_node:
                return best_node.action, best_node.mean_value, best_node
        return "HOLD", 0.0, self._root

    def _select(self, node: MCTSNode) -> MCTSNode:
        while node.children:
            if any(c.visits == 0 for c in node.children):
                return next(c for c in node.children if c.visits == 0)
            node = node.best_child()
            if node is None:
                break
        return node

    def _expand(self, node: MCTSNode) -> MCTSNode:
        valid_actions = self._valid_actions(node)
        for action in valid_actions:
            sim_state = self.simulator_fn(node.state_vector, action, noise_scale=self.noise_scale)
            prior = 1.0 / len(valid_actions)
            child = MCTSNode(
                state_vector=sim_state,
                action=action,
                parent=node,
                prior=prior,
                depth=node.depth + 1,
            )
            node.children.append(child)
        if node.children:
            return random.choice(node.children)
        return node

    def _simulate(self, node: MCTSNode) -> float:
        vec = node.state_vector.copy()
        depth = node.depth
        while depth < self.max_depth:
            action = random.choice(self._valid_actions_from_vec(vec))
            vec = self.simulator_fn(vec, action, noise_scale=self.noise_scale * 2)
            depth += 1
        return float(self.evaluator_fn(vec))

    def _backpropagate(self, node: MCTSNode, value: float) -> None:
        while node is not None:
            node.visits += 1
            node.value_sum += value
            node = node.parent

    def _valid_actions(self, node: MCTSNode) -> List[str]:
        return self._valid_actions_from_vec(node.state_vector)

    def _valid_actions_from_vec(self, vec: np.ndarray) -> List[str]:
        actions = ["HOLD"]
        has_position = abs(vec[20] - 1.0) < 0.1 or abs(vec[21] - 1.0) < 0.1
        has_cash = vec[3] > 0.01
        if has_cash:
            actions.append("BUY_LIMIT")
        if has_position:
            actions.append("SELL_LIMIT")
            actions.append("RISK_CLOSE")
        return actions


def default_simulator(vec: np.ndarray, action: str, noise_scale: float = 0.01) -> np.ndarray:
    new_vec = vec.copy()

    price = new_vec[PRICE_IDX] * 100000.0
    cash = new_vec[CASH_IDX] * 100000.0
    size = 0.1
    noise = random.gauss(0, noise_scale)
    new_price = price * (1.0 + noise)
    new_vec[PRICE_IDX] = new_price / 100000.0

    if action == "BUY_LIMIT" and cash >= size * new_price:
        cost = size * new_price
        new_vec[CASH_IDX] = (cash - cost) / 100000.0
        new_vec[POSITION_LONG_IDX] = 1.0
        new_vec[POSITION_SHORT_IDX] = 0.0
        new_vec[PNL_IDX] = 0.0
    elif action == "SELL_LIMIT":
        new_vec[POSITION_LONG_IDX] = 0.0
        new_vec[CASH_IDX] = (cash + size * new_price * 0.999) / 100000.0
    elif action == "RISK_CLOSE":
        new_vec[POSITION_LONG_IDX] = 0.0
        new_vec[POSITION_SHORT_IDX] = 0.0
        new_vec[PNL_IDX] = 0.0

    new_vec[PORTFOLIO_IDX] = (new_vec[CASH_IDX] * 100000.0) / 100000.0
    new_vec[PORTFOLIO_IDX] = new_vec[CASH_IDX]
    return np.clip(new_vec, -10.0, 10.0)


def heuristic_simulator(vec: np.ndarray, action: str, noise_scale: float = 0.01) -> np.ndarray:
    new_vec = default_simulator(vec, action, noise_scale)
    rsi = new_vec[RSI_IDX] * 100.0
    rsi_noise = random.gauss(0, 3.0)
    if rsi > 70:
        rsi_noise -= 2.0
    elif rsi < 30:
        rsi_noise += 2.0
    new_vec[RSI_IDX] = max(0, min(100, rsi + rsi_noise)) / 100.0
    mom = new_vec[MOMENTUM_IDX] * 10.0
    mom_noise = random.gauss(0, 0.5)
    if action == "BUY_LIMIT":
        mom_noise += 0.3
    elif action == "SELL_LIMIT":
        mom_noise -= 0.3
    new_vec[MOMENTUM_IDX] = max(-1.0, min(1.0, (mom + mom_noise) / 10.0))
    return new_vec

