from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MAX_STATE_HISTORY = 5000


@dataclass
class EnvironmentState:
    portfolio_value: float = 0.0
    cash: float = 0.0
    position: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    pnl_unrealized: float = 0.0
    step: int = 0
    total_trades: int = 0


class TradingEnvironment:
    def __init__(
        self,
        initial_balance: float = 100000.0,
        transaction_cost_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        state_window: int = 10,
    ) -> None:
        self.initial_balance = initial_balance
        self.tc_pct = transaction_cost_pct
        self.slippage_pct = slippage_pct
        self.state_window = state_window

        self.cash: float = initial_balance
        self.position: float = 0.0
        self.entry_price: float = 0.0
        self.portfolio_value: float = initial_balance
        self.total_trades: int = 0

        self.price_history: deque = deque(maxlen=state_window)
        self.state_history: deque = deque(maxlen=MAX_STATE_HISTORY)
        self.step_count: int = 0
        self._prev_portfolio_value: float = initial_balance

    def step(
        self,
        action: int,
        price: float,
        rsi: float,
        macd: float,
        atr: float,
        volatility_index: float,
    ) -> Tuple[np.ndarray, float, bool, dict]:
        self.price_history.append(price)

        momentum = self._compute_momentum(price)
        reward = self._execute_action(action, price)

        done = self.portfolio_value <= 0.0

        state = self._build_state(rsi, macd, atr, momentum, volatility_index)
        self.state_history.append(state)
        self.step_count += 1

        info = {
            "step": self.step_count,
            "portfolio_value": round(self.portfolio_value, 2),
            "cash": round(self.cash, 2),
            "position": round(self.position, 6),
            "price": price,
        }

        logger.debug(
            "Environment | step=%d action=%d price=%.2f reward=%.6f pv=%.2f",
            self.step_count, action, price, reward, self.portfolio_value,
        )

        return state, reward, done, info

    def apply_trade(self, action: int, fill_price: float, shares: float) -> float:
        prev = self._prev_portfolio_value
        if action == 1 and shares > 0:
            cost = shares * fill_price * (1.0 + self.tc_pct + self.slippage_pct)
            if cost <= self.cash:
                self.cash -= cost
                self.position += shares
                self.entry_price = fill_price
                self.total_trades += 1
        elif action == 2 and self.position > 0:
            proceeds = self.position * fill_price * (1.0 - self.tc_pct - self.slippage_pct)
            self.cash += proceeds
            self.position = 0.0
            self.entry_price = 0.0
            self.total_trades += 1

        self.portfolio_value = self.cash + self.position * fill_price
        log_return = math.log(self.portfolio_value / prev) if prev > 0 else 0.0
        self._prev_portfolio_value = self.portfolio_value
        return log_return

    def reset(self, initial_balance: Optional[float] = None) -> np.ndarray:
        if initial_balance is not None:
            self.initial_balance = initial_balance
        self.cash = self.initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.portfolio_value = self.initial_balance
        self.total_trades = 0
        self.price_history.clear()
        self.state_history.clear()
        self.step_count = 0
        self._prev_portfolio_value = self.initial_balance
        logger.info("Environment | reset to balance=%.2f", self.initial_balance)
        return np.zeros(5, dtype=np.float32)

    def _execute_action(self, action: int, price: float) -> float:
        prev_value = self._prev_portfolio_value

        if action == 1:
            alloc = self.cash * 0.95
            shares = alloc / price if price > 0 else 0.0
            cost = shares * price * (1.0 + self.tc_pct + self.slippage_pct)
            if cost <= self.cash:
                self.cash -= cost
                self.position += shares
                self.entry_price = price
                self.total_trades += 1
        elif action == 2:
            if self.position > 0.0:
                proceeds = self.position * price * (1.0 - self.tc_pct - self.slippage_pct)
                self.cash += proceeds
                self.position = 0.0
                self.entry_price = 0.0
                self.total_trades += 1

        self.portfolio_value = self.cash + self.position * price
        self._prev_portfolio_value = self.portfolio_value

        log_return = math.log(self.portfolio_value / prev_value) if prev_value > 0 else 0.0
        return log_return

    def _compute_momentum(self, price: float) -> float:
        if len(self.price_history) < 2:
            return 0.0
        return (price - self.price_history[0]) / self.price_history[0] if self.price_history[0] != 0 else 0.0

    def _build_state(
        self, rsi: float, macd: float, atr: float, momentum: float, vol_index: float
    ) -> np.ndarray:
        return np.array([rsi, macd, atr, momentum, vol_index], dtype=np.float32)

    def get_portfolio_state(self) -> EnvironmentState:
        return EnvironmentState(
            portfolio_value=self.portfolio_value,
            cash=self.cash,
            position=self.position,
            entry_price=self.entry_price,
            current_price=self.price_history[-1] if self.price_history else 0.0,
            pnl_unrealized=self.portfolio_value - self.initial_balance,
            step=self.step_count,
            total_trades=self.total_trades,
        )
