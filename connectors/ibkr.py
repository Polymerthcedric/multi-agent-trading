from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MODE_LIVE = "LIVE"
_MODE_PAPER = "PAPER"
_MODE_DEMO = "DEMO"


class IBKRDataError(RuntimeError):
    pass


class IBConnector:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1, paper: bool = True, mode: str = _MODE_PAPER) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.paper = paper
        self.mode = mode
        self._ib = None
        self._connected = False
        self._contracts: Dict[str, object] = {}

    @property
    def name(self) -> str:
        return "ib_paper" if self.paper else "ib_live"

    @property
    def is_live(self) -> bool:
        return not self.paper

    def _is_live_or_paper(self) -> bool:
        return self.mode in (_MODE_LIVE, _MODE_PAPER)

    def is_available(self) -> bool:
        try:
            import ib_insync
            return True
        except ImportError:
            return False

    def connect(self) -> bool:
        if not self.is_available():
            logger.warning("IBKR | ib_insync not installed. Run: pip install ib_insync")
            return False
        try:
            from ib_insync import IB
            self._ib = IB()
            self._ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            logger.info("IBKR | connected to %s:%d (paper=%s)", self.host, self.port, self.paper)
            return True
        except Exception as e:
            logger.error("IBKR | connection failed: %s", e)
            return False

    def disconnect(self) -> None:
        if self._ib and self._connected:
            self._ib.disconnect()
            self._connected = False
            logger.info("IBKR | disconnected")

    def _get_contract(self, symbol: str):
        from ib_insync import Stock, Forex, CFD, Contract
        if symbol in self._contracts:
            return self._contracts[symbol]
        base = symbol.split("/")[0] if "/" in symbol else symbol
        quote = symbol.split("/")[1] if "/" in symbol else "USD"
        if symbol == "GOLD/USD" or base == "GOLD":
            from ib_insync import ComboLeg
            c = Contract(symbol="XAUUSD", secType="CMDTAG", exchange="SMART", currency="USD")
        elif base in ("EUR", "GBP", "JPY", "CHF", "AUD"):
            c = Forex(base + quote)
        elif symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
            from ib_insync import Crypto
            c = Crypto(base, "PAXOS", quote)
        else:
            c = Stock(base, "SMART", quote)
        self._contracts[symbol] = c
        return c

    async def get_market_data(self, symbol: str) -> Dict[str, float]:
        if not self._connected or not self._ib:
            msg = f"IBKR not connected for {symbol} [mode={self.mode}]"
            if self._is_live_or_paper():
                raise IBKRDataError(msg)
            logger.warning(msg + " — synthetic fallback (DEMO only)")
            return self._fallback_market_data(symbol)
        try:
            from ib_insync import util
            contract = self._get_contract(symbol)
            ticker = self._ib.reqMktData(contract, "", False, False)
            self._ib.sleep(1)
            if not ticker.last and not ticker.close:
                msg = f"IBKR returned zero/no price for {symbol} [mode={self.mode}]"
                if self._is_live_or_paper():
                    raise IBKRDataError(msg)
                logger.warning(msg + " — synthetic fallback (DEMO only)")
                return self._fallback_market_data(symbol)
            md = {
                "symbol": symbol,
                "price": ticker.last or ticker.close or 0.0,
                "high": ticker.high or 0.0,
                "low": ticker.low or 0.0,
                "volume": ticker.volume or 0.0,
                "bid": ticker.bid or 0.0,
                "ask": ticker.ask or 0.0,
                "change_pct": 0.0,
                "sma": 0.0, "ema": 0.0, "rsi": 50.0,
                "historical_support": 0.0, "historical_resistance": 0.0,
            }
            return md
        except IBKRDataError:
            raise
        except Exception as e:
            logger.error("IBKR | market data error for %s: %s", symbol, e)
            if self._is_live_or_paper():
                raise IBKRDataError(f"Market data error for {symbol}: {e}") from e
            return self._fallback_market_data(symbol)

    async def get_balance(self) -> Dict:
        if not self._connected or not self._ib:
            return {"total_equity": 100000.0, "cash": 100000.0, "positions": {}}
        try:
            account = self._ib.accountSummary()
            pos = self._ib.positions()
            total = float([s.value for s in account if s.tag == "NetLiquidation"][0]) if account else 100000.0
            cash = float([s.value for s in account if s.tag == "CashBalance"][0]) if account else 100000.0
            positions = {p.contract.symbol: float(p.position) for p in pos} if pos else {}
            return {"total_equity": total, "cash": cash, "positions": positions}
        except Exception as e:
            logger.error("IBKR | balance error: %s", e)
            return {"total_equity": 100000.0, "cash": 100000.0, "positions": {}}

    async def execute_order(self, symbol: str, side: str, quantity: float, order_type: str = "market") -> Dict:
        if not self._connected or not self._ib:
            logger.warning("IBKR | not connected, order rejected for %s", symbol)
            return {"status": "rejected", "error": "not connected"}
        try:
            from ib_insync import MarketOrder, LimitOrder
            contract = self._get_contract(symbol)
            order = MarketOrder(side.upper(), quantity)
            trade = self._ib.placeOrder(contract, order)
            self._ib.sleep(1)
            fill = trade.fills[0] if trade.fills else None
            return {
                "order_id": str(trade.order.orderId),
                "status": trade.orderStatus.status,
                "filled_quantity": float(fill.execution.shares) if fill else 0.0,
                "avg_fill_price": float(fill.execution.price) if fill else 0.0,
                "symbol": symbol,
                "side": side,
            }
        except Exception as e:
            logger.error("IBKR | order error: %s", e)
            return {"status": "rejected", "error": str(e)}

    async def get_historical_data(self, symbol: str, days: int = 30, bar_size: str = "1 hour") -> List[Dict]:
        if not self._connected or not self._ib:
            logger.warning("IBKR | not connected, cannot fetch historical data")
            return []
        try:
            from ib_insync import util
            contract = self._get_contract(symbol)
            duration = f"{days} D"
            bars = self._ib.reqHistoricalData(
                contract, endDateTime="", durationStr=duration,
                barSizeSetting=bar_size, whatToShow="TRADES", useRTH=True, formatDate=1,
            )
            return [
                {"timestamp": bar.date.timestamp(), "open": bar.open, "high": bar.high,
                 "low": bar.low, "close": bar.close, "volume": bar.volume}
                for bar in bars
            ] if bars else []
        except Exception as e:
            logger.error("IBKR | historical data error: %s", e)
            return []

    def _fallback_market_data(self, symbol: str) -> Dict[str, float]:
        import random
        base_prices = {
            "BTC/USD": 62000, "ETH/USD": 1750, "SOL/USD": 82,
            "GOLD/USD": 2350, "EUR/USD": 1.14, "GBP/USD": 1.33,
            "USD/JPY": 161, "USD/CHF": 0.80, "AUD/USD": 0.69,
        }
        base = base_prices.get(symbol, 100.0)
        noise = 1.0 + random.uniform(-0.005, 0.005)
        return {
            "symbol": symbol, "price": round(base * noise, 2),
            "high": round(base * noise * 1.005, 2), "low": round(base * noise * 0.995, 2),
            "volume": random.uniform(1000, 100000),
            "bid": round(base * noise * 0.9995, 2), "ask": round(base * noise * 1.0005, 2),
            "sma": round(base * 0.995, 2), "ema": round(base * 0.998, 2),
            "rsi": random.uniform(30, 70), "change_pct": round((noise - 1.0) * 100, 2),
            "historical_support": round(base * 0.95, 2),
            "historical_resistance": round(base * 1.05, 2),
        }
