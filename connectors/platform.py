from __future__ import annotations

import logging
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from connectors.tv_datafeed import DataUnavailableError

logger = logging.getLogger(__name__)

MAX_TRADE_HISTORY = 500
MAX_EQUITY_POINTS = 10000
MIN_QUANTITY = 0.0001


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
    commission: float = 0.0
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
    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        *,
        reference_price: Optional[float] = None,
        fill_price: Optional[float] = None,
        commission_pct: float = 0.0,
    ) -> OrderResult:
        ...

    @abstractmethod
    async def get_positions(self) -> Dict[str, float]:
        ...


class PaperTradingConnector(BaseExchangeConnector):
    def __init__(self, initial_balance: float = 100000.0, tv_feed: Optional[object] = None) -> None:
        super().__init__(name="paper")
        self._cash: float = initial_balance
        self._positions: Dict[str, float] = {}
        self._order_id_counter: int = 0
        self._trade_history: deque = deque(maxlen=MAX_TRADE_HISTORY)
        self._equity_curve: deque = deque([initial_balance], maxlen=MAX_EQUITY_POINTS)
        self._is_live = False
        self._tv_feed = tv_feed
        self._last_prices: Dict[str, float] = {}

    @property
    def trade_history(self) -> List[OrderResult]:
        return list(self._trade_history)

    async def get_balance(self) -> Balance:
        return Balance(
            total_equity=self._cash + await self._position_value(),
            cash=self._cash,
            positions=dict(self._positions),
        )

    async def get_market_data(self, symbol: str) -> Dict[str, Any]:
        if self._tv_feed is None:
            raise DataUnavailableError(
                f"No market-data feed configured for paper trading {symbol}"
            )
        try:
            snap = await self._tv_feed.get_snapshot(symbol)
            if snap is None or getattr(snap, "is_stale", False):
                raise DataUnavailableError(f"Fresh market data unavailable for {symbol}")
            market_data = self._tv_feed.to_market_data(symbol, snap)
        except Exception as error:
            if isinstance(error, DataUnavailableError):
                raise
            raise DataUnavailableError(
                f"Market-data request failed for {symbol}: {error}"
            ) from error

        price = market_data.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise DataUnavailableError(f"Market-data price is invalid for {symbol}")
        if not math.isfinite(price) or price <= 0:
            raise DataUnavailableError(f"Market-data price is invalid for {symbol}")
        self._last_prices[symbol] = float(price)
        market_data["is_stale"] = False
        return market_data

    async def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        *,
        reference_price: Optional[float] = None,
        fill_price: Optional[float] = None,
        commission_pct: float = 0.0,
    ) -> OrderResult:
        self._order_id_counter += 1
        order_id = f"paper_{self._order_id_counter}"
        requested_qty = quantity
        side_lower = side.lower() if isinstance(side, str) else ""

        def reject(reason: str, price: float = 0.0) -> OrderResult:
            logger.warning("PaperTrading | rejected %s %s %s", side_lower, symbol, reason)
            return OrderResult(
                order_id=order_id, symbol=symbol, side=side_lower,
                quantity=requested_qty, price=price, filled_quantity=0.0,
                avg_fill_price=0.0, status="rejected", timestamp=time.time(),
                error=reason,
            )

        if side_lower not in ("buy", "sell"):
            return reject(f"unsupported side: {side!r}")
        if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or not math.isfinite(quantity):
            return reject(f"invalid quantity: {quantity!r}")
        if quantity < MIN_QUANTITY:
            return reject(f"quantity {quantity:.8f} below minimum {MIN_QUANTITY}")

        if isinstance(commission_pct, bool) or not isinstance(commission_pct, (int, float)):
            return reject(f"invalid commission rate: {commission_pct!r}")
        if not math.isfinite(commission_pct) or commission_pct < 0 or commission_pct >= 1:
            return reject(f"invalid commission rate: {commission_pct!r}")
        if fill_price is None:
            try:
                price_data = await self.get_market_data(symbol)
            except DataUnavailableError as error:
                return reject(str(error))
            fill_price = float(price_data["price"])
        if isinstance(fill_price, bool) or not isinstance(fill_price, (int, float)):
            return reject(f"invalid fill price: {fill_price!r}")
        if not math.isfinite(fill_price) or fill_price <= 0:
            return reject(f"invalid fill price: {fill_price}", float(fill_price))
        fill_price = float(fill_price)

        if reference_price is None:
            reference_price = fill_price
        if isinstance(reference_price, bool) or not isinstance(reference_price, (int, float)):
            return reject(f"invalid reference price: {reference_price!r}", fill_price)
        if not math.isfinite(reference_price) or reference_price <= 0:
            return reject(f"invalid reference price: {reference_price}", fill_price)
        reference_price = float(reference_price)

        filled_qty = 0.0
        commission = 0.0
        if side_lower == "buy":
            cost = quantity * (fill_price + reference_price * commission_pct)
            if cost > self._cash:
                affordable_qty = self._cash / (fill_price + reference_price * commission_pct)
                if affordable_qty < MIN_QUANTITY:
                    return reject(
                        f"insufficient cash: need {cost:.2f}, have {self._cash:.2f}", fill_price,
                    )
                quantity = affordable_qty
                cost = quantity * (fill_price + reference_price * commission_pct)
                logger.info("PaperTrading | reduced buy qty to %.6f (cash limited)", quantity)
            commission = quantity * reference_price * commission_pct
            self._cash -= cost
            self._positions[symbol] = self._positions.get(symbol, 0.0) + quantity
            filled_qty = quantity
        else:
            current = self._positions.get(symbol, 0.0)
            filled_qty = min(quantity, current)
            if filled_qty < MIN_QUANTITY:
                return reject(
                    f"position too small: have {current:.6f}, want {quantity:.6f}", fill_price,
                )
            commission = filled_qty * reference_price * commission_pct
            self._cash += filled_qty * fill_price - commission
            remaining = current - filled_qty
            if remaining <= 1e-12:
                self._positions.pop(symbol, None)
            else:
                self._positions[symbol] = remaining

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side_lower,
            quantity=requested_qty,
            price=fill_price,
            filled_quantity=filled_qty,
            avg_fill_price=fill_price,
            status="filled",
            timestamp=time.time(),
            commission=commission,
        )
        self._last_prices[symbol] = fill_price
        self._trade_history.append(result)
        self._equity_curve.append(self._cash + await self._position_value())
        logger.info(
            "PaperTrading | %s %s requested=%.6f filled=%.6f @ %.2f",
            side_lower, symbol, requested_qty, filled_qty, fill_price,
        )
        return result

    async def get_positions(self) -> Dict[str, float]:
        return dict(self._positions)

    async def _position_value(self) -> float:
        if not self._positions:
            return 0.0
        total = 0.0
        for symbol, quantity in self._positions.items():
            try:
                market_data = await self.get_market_data(symbol)
                current_price = float(market_data["price"])
            except DataUnavailableError:
                current_price = self._last_prices.get(symbol, 0.0)
            if current_price <= 0:
                raise DataUnavailableError(
                    f"No valid valuation price available for open position {symbol}"
                )
            total += quantity * current_price
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
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        *,
        reference_price: Optional[float] = None,
        fill_price: Optional[float] = None,
        commission_pct: float = 0.0,
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
