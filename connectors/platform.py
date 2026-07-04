from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_TRADE_HISTORY = 500
MAX_EQUITY_POINTS = 10000


@dataclass
class OrderResult:
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    status: str = ""
    timestamp: float = 0.0
    error: Optional[str] = None


@dataclass
class Balance:
    total_equity: float = 0.0
    cash: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)


class BaseExchangeConnector(ABC):
    def __init__(self, name: str = "base") -> None:
        self.name = name
        self._is_live: bool = False

    @property
    def is_live(self) -> bool:
        return self._is_live

    @abstractmethod
    async def get_balance(self) -> Balance:
        ...

    @abstractmethod
    async def get_market_data(self, symbol: str) -> Dict[str, float]:
        ...

    @abstractmethod
    async def execute_order(
        self, symbol: str, side: str, quantity: float, order_type: str = "market",
    ) -> OrderResult:
        ...

    @abstractmethod
    async def get_positions(self) -> Dict[str, float]:
        ...


class PaperTradingConnector(BaseExchangeConnector):
    _BASE_PRICES: Dict[str, float] = {
        "BTC/USD": 52000.0,
        "ETH/USD": 2800.0,
        "SOL/USD": 120.0,
    }

    def __init__(self, initial_balance: float = 100000.0, tv_feed: Optional[object] = None) -> None:
        super().__init__(name="paper")
        self._cash: float = initial_balance
        self._positions: Dict[str, float] = {}
        self._order_id_counter: int = 0
        self._trade_history: deque = deque(maxlen=MAX_TRADE_HISTORY)
        self._equity_curve: deque = deque([initial_balance], maxlen=MAX_EQUITY_POINTS)
        self._is_live = False
        self._tv_feed = tv_feed

    @property
    def trade_history(self) -> List[OrderResult]:
        return list(self._trade_history)

    async def get_balance(self) -> Balance:
        return Balance(
            total_equity=self._cash + await self._position_value(),
            cash=self._cash,
            positions=dict(self._positions),
        )

    async def get_market_data(self, symbol: str) -> Dict[str, float]:
        if self._tv_feed is not None:
            try:
                snap = await self._tv_feed.get_snapshot(symbol)
                return self._tv_feed.to_market_data(symbol, snap)
            except Exception as e:
                logger.warning("PaperTrading | TV feed failed, falling back: %s", e)
        base = self._BASE_PRICES.get(symbol, 100.0)
        noise = random.uniform(-0.02, 0.02)
        price = base * (1.0 + noise)
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "sma": round(base * 0.99, 2),
            "ema": round(base * 1.005, 2),
            "rsi": round(random.uniform(25, 75), 2),
            "high": round(price * 1.015, 2),
            "low": round(price * 0.985, 2),
            "historical_support": round(base * 0.93, 2),
            "historical_resistance": round(base * 1.07, 2),
        }

    async def execute_order(
        self, symbol: str, side: str, quantity: float, order_type: str = "market",
    ) -> OrderResult:
        self._order_id_counter += 1
        price_data = await self.get_market_data(symbol)
        fill_price = price_data["price"]
        side_lower = side.lower()

        if side_lower == "buy":
            cost = quantity * fill_price
            self._cash -= cost
            self._positions[symbol] = self._positions.get(symbol, 0.0) + quantity
        elif side_lower == "sell":
            current = self._positions.get(symbol, 0.0)
            actual_qty = min(quantity, current)
            if actual_qty <= 0:
                logger.warning("PaperTrading | cannot sell %s: position=%.6f, requested=%.6f", symbol, current, quantity)
                return OrderResult(
                    order_id=f"paper_{self._order_id_counter}", symbol=symbol, side=side_lower,
                    quantity=quantity, price=fill_price, filled_quantity=0.0,
                    avg_fill_price=0.0, status="rejected", timestamp=time.time(),
                    error=f"position too small: have {current:.6f}, want {quantity:.6f}",
                )
            proceeds = actual_qty * fill_price
            self._cash += proceeds
            remaining = current - actual_qty
            if remaining <= 0:
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = remaining

        result = OrderResult(
            order_id=f"paper_{self._order_id_counter}",
            symbol=symbol,
            side=side_lower,
            quantity=quantity,
            price=fill_price,
            filled_quantity=quantity if side_lower == "buy" else min(quantity, current if side_lower == "sell" else quantity),
            avg_fill_price=fill_price,
            status="filled",
            timestamp=time.time(),
        )
        self._trade_history.append(result)
        self._equity_curve.append(self._cash + await self._position_value())
        logger.info("PaperTrading | %s %s %.4f @ %.2f", side_lower, symbol, quantity, fill_price)
        return result

    async def get_positions(self) -> Dict[str, float]:
        return dict(self._positions)

    async def _position_value(self) -> float:
        if not self._positions:
            return 0.0
        total = 0.0
        if self._tv_feed is not None:
            for sym, qty in self._positions.items():
                try:
                    snap = await self._tv_feed.get_snapshot(sym)
                    current_price = snap.price if snap and snap.price > 0 else self._BASE_PRICES.get(sym, 100.0)
                except Exception:
                    current_price = self._BASE_PRICES.get(sym, 100.0)
                total += qty * current_price
        else:
            for sym, qty in self._positions.items():
                total += qty * self._BASE_PRICES.get(sym, 100.0)
        return total


class LiveExchangeConnector(BaseExchangeConnector):
    def __init__(self, api_key: str = "", secret: str = "", testnet: bool = True) -> None:
        super().__init__(name="live" if not testnet else "testnet")
        self._api_key = api_key
        self._secret = secret
        self._testnet = testnet
        self._is_live = not testnet
        self._initialized = False

    async def initialize(self) -> None:
        if not self._api_key or not self._secret:
            logger.warning("LiveExchange | missing API credentials — stub mode")
            return
        self._initialized = True
        logger.info("LiveExchange | initialized (testnet=%s)", self._testnet)

    async def get_balance(self) -> Balance:
        logger.warning("LiveExchange | get_balance — stub returning zero")
        return Balance()

    async def get_market_data(self, symbol: str) -> Dict[str, float]:
        logger.warning("LiveExchange | get_market_data(%s) — stub", symbol)
        return {"symbol": symbol, "price": 0.0, "sma": 0.0, "ema": 0.0, "rsi": 50.0, "high": 0.0, "low": 0.0}

    async def execute_order(
        self, symbol: str, side: str, quantity: float, order_type: str = "market",
    ) -> OrderResult:
        logger.warning("LiveExchange | execute_order — stub, not configured")
        return OrderResult(
            order_id="stub",
            symbol=symbol,
            side=side,
            quantity=quantity,
            status="rejected",
            error="live connector not configured",
        )

    async def get_positions(self) -> Dict[str, float]:
        return {}
