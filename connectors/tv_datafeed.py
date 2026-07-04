from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SYMBOL_MAP: Dict[str, str] = {
    "BTC/USD": "BTCUSD", "ETH/USD": "ETHUSD", "SOL/USD": "SOLUSD",
    "BTC/USDT": "BTCUSDT", "GOLD/USD": "GOLD",
    "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD", "USD/JPY": "USDJPY",
    "USD/CHF": "USDCHF", "AUD/USD": "AUDUSD",
}

_EXCHANGE_MAP: Dict[str, str] = {
    "BTC/USD": "BINANCE", "ETH/USD": "BINANCE", "SOL/USD": "BINANCE",
    "BTC/USDT": "BINANCE", "GOLD/USD": "TVC",
    "EUR/USD": "FX_IDC", "GBP/USD": "FX_IDC", "USD/JPY": "FX_IDC",
    "USD/CHF": "FX_IDC", "AUD/USD": "FX_IDC",
}

_SCREENER_MAP: Dict[str, str] = {
    "BTC/USD": "crypto", "ETH/USD": "crypto", "SOL/USD": "crypto",
    "BTC/USDT": "crypto", "GOLD/USD": "cfd",
    "EUR/USD": "forex", "GBP/USD": "forex", "USD/JPY": "forex",
    "USD/CHF": "forex", "AUD/USD": "forex",
}

_DATA_MODE_LIVE = "LIVE"
_DATA_MODE_PAPER = "PAPER"
_DATA_MODE_DEMO = "DEMO"


@dataclass
class TVSnapshot:
    timestamp: float = 0.0
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    rsi: float = 50.0
    sma10: float = 0.0
    sma20: float = 0.0
    sma50: float = 0.0
    ema10: float = 0.0
    ema20: float = 0.0
    ema50: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    adx: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    atr: float = 0.0
    change_pct: float = 0.0
    momentum: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    recommendation: str = "NEUTRAL"
    buy_signals: int = 0
    sell_signals: int = 0
    is_stale: bool = False
    staleness_seconds: float = 0.0


class DataUnavailableError(RuntimeError):
    pass


class TradingViewFeed:
    def __init__(
        self,
        symbols: Tuple[str, ...] = (
            "BTC/USD", "ETH/USD", "SOL/USD",
            "GOLD/USD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
        ),
        mode: str = _DATA_MODE_PAPER,
        max_data_age_seconds: float = 3600.0,
    ) -> None:
        self.symbols = symbols
        self.mode = mode
        self.max_data_age_seconds = max_data_age_seconds
        self._handlers: Dict[str, object] = {}
        self._cache: Dict[str, TVSnapshot] = {}
        self._price_history: Dict[str, List[float]] = {s: [] for s in symbols}
        self._last_fetch: Dict[str, float] = {}
        self._cache_ttl: float = 30.0
        self._backoff: Dict[str, float] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._data_quality_ok: bool = True
        self._init_handlers()

    def _init_handlers(self) -> None:
        try:
            from tradingview_ta import TA_Handler, Interval
        except ImportError:
            logger.error("tradingview_ta not installed. Run: pip install tradingview-ta")
            raise
        for sym in self.symbols:
            tv_sym = _SYMBOL_MAP.get(sym, sym.replace("/", ""))
            exchange = _EXCHANGE_MAP.get(sym, "BINANCE")
            screener = _SCREENER_MAP.get(sym, "crypto")
            self._handlers[sym] = TA_Handler(
                symbol=tv_sym, exchange=exchange, screener=screener, interval=Interval.INTERVAL_1_HOUR,
            )

    def is_available(self) -> bool:
        try:
            import tradingview_ta
            return True
        except ImportError:
            return False

    @property
    def data_quality_ok(self) -> bool:
        return self._data_quality_ok

    def get_data_quality_report(self) -> Dict:
        stale = 0
        total = len(self.symbols)
        failures = sum(self._consecutive_failures.get(s, 0) > 2 for s in self.symbols)
        has_cache = sum(1 for s in self.symbols if s in self._cache)
        return {
            "mode": self.mode,
            "symbols_total": total,
            "symbols_cached": has_cache,
            "symbols_stale": stale,
            "symbols_failing": failures,
            "data_quality_ok": self._data_quality_ok,
            "backoff_active": sum(1 for v in self._backoff.values() if v > time.time()),
        }

    def _is_live_mode(self) -> bool:
        return self.mode in (_DATA_MODE_LIVE, _DATA_MODE_PAPER)

    async def _rate_limit(self, multiplier: float = 1.0) -> None:
        await asyncio.sleep(min(15.0, 0.8 * multiplier))

    async def get_snapshot(self, symbol: str) -> TVSnapshot:
        now = time.time()

        cached = self._cache.get(symbol)
        if cached and (now - self._last_fetch.get(symbol, 0)) < self._cache_ttl:
            if not cached.is_stale:
                return cached

        backoff_until = self._backoff.get(symbol, 0.0)
        if now < backoff_until:
            logger.debug("TradingViewFeed | backing off %s for %.1fs", symbol, backoff_until - now)
            await asyncio.sleep(min(backoff_until - now, 30.0))

        handler = self._handlers.get(symbol)
        if handler is None:
            raise DataUnavailableError(f"No TV handler for {symbol}")

        wait = self._backoff.get(symbol, 0.0)
        await self._rate_limit(1.0 + wait / 5.0)
        try:
            data = handler.get_analysis()
            inds = data.indicators
            self._backoff.pop(symbol, None)
            self._consecutive_failures[symbol] = 0
        except Exception as e:
            err_str = str(e)
            self._consecutive_failures[symbol] = self._consecutive_failures.get(symbol, 0) + 1
            failures = self._consecutive_failures[symbol]
            logger.error("TradingViewFeed | fetch failed for %s (x%d): %s", symbol, failures, err_str)
            if failures >= 5:
                self._backoff.pop(symbol, None)
            elif "429" in err_str:
                current = self._backoff.get(symbol, 1.0)
                self._backoff[symbol] = min(current * 2.0, 120.0)
                logger.warning("TradingViewFeed | rate limited %s, backoff=%.1fs", symbol, self._backoff[symbol])
            else:
                self._backoff.pop(symbol, None)

            if failures >= 3 and self._is_live_mode():
                self._data_quality_ok = False
                raise DataUnavailableError(
                    f"TradingView data unavailable for {symbol} after {failures} failures "
                    f"[mode={self.mode}]. Live/Paper mode cannot substitute data. "
                    f"Backoff: {self._backoff.get(symbol, 0):.0f}s"
                )

            if symbol in self._cache:
                cached = self._cache[symbol]
                cached.is_stale = True
                cached.staleness_seconds = time.time() - self._last_fetch.get(symbol, now)
                return cached
            raise DataUnavailableError(f"No cached data for {symbol} and fetch failed")

        price = float(inds.get("close", 0.0))
        if price <= 0 and self._is_live_mode():
            self._data_quality_ok = False
            raise DataUnavailableError(f"TradingView returned zero price for {symbol} [mode={self.mode}]")

        high = float(inds.get("high", price))
        low = float(inds.get("low", price))
        self._price_history[symbol].append(price)
        if len(self._price_history[symbol]) > 50:
            self._price_history[symbol].pop(0)
        self._data_quality_ok = True

        summary = data.summary or {}
        snap = TVSnapshot(
            timestamp=now, price=price, open=float(inds.get("open", price)),
            high=high, low=low, volume=float(inds.get("volume", 0.0)),
            rsi=float(inds.get("RSI", 50.0)),
            sma10=float(inds.get("SMA10", 0.0)), sma20=float(inds.get("SMA20", 0.0)),
            sma50=float(inds.get("SMA50", 0.0)),
            ema10=float(inds.get("EMA10", 0.0)), ema20=float(inds.get("EMA20", 0.0)),
            ema50=float(inds.get("EMA50", 0.0)),
            macd=float(inds.get("MACD.macd", 0.0)), macd_signal=float(inds.get("MACD.signal", 0.0)),
            adx=float(inds.get("ADX", 0.0)),
            bb_upper=float(inds.get("BB.upper", price * 1.05)),
            bb_lower=float(inds.get("BB.lower", price * 0.95)),
            atr=float(inds.get("ATR", high - low)) if inds.get("ATR") is not None else (high - low),
            change_pct=float(inds.get("change", 0.0)), momentum=float(inds.get("Mom", 0.0)),
            support=float(inds.get("Pivot.M.Classic.S1", price * 0.97)),
            resistance=float(inds.get("Pivot.M.Classic.R1", price * 1.03)),
            recommendation=summary.get("RECOMMENDATION", "NEUTRAL"),
            buy_signals=int(summary.get("BUY", 0)), sell_signals=int(summary.get("SELL", 0)),
            is_stale=False, staleness_seconds=0.0,
        )
        self._cache[symbol] = snap
        self._last_fetch[symbol] = now
        logger.debug("TradingViewFeed | %s price=%.2f rsi=%.1f rec=%s", symbol, price, snap.rsi, snap.recommendation)
        return snap

    def get_price_history(self, symbol: str) -> List[float]:
        return self._price_history.get(symbol, [])

    def to_market_data(self, symbol: str, snap: Optional[TVSnapshot] = None) -> Dict[str, float]:
        if snap is None:
            snap = self._cache.get(symbol)
            if snap is None:
                return {"symbol": symbol, "price": 0.0, "sma": 0.0, "ema": 0.0, "rsi": 50.0, "high": 0.0, "low": 0.0, "historical_support": 0.0, "historical_resistance": 0.0}
        return {
            "symbol": symbol, "price": snap.price, "sma": snap.sma20 or snap.sma10,
            "ema": snap.ema20 or snap.ema10, "rsi": snap.rsi, "high": snap.high, "low": snap.low,
            "historical_support": snap.support, "historical_resistance": snap.resistance,
            "volume": snap.volume, "adx": snap.adx, "macd": snap.macd, "macd_signal": snap.macd_signal,
            "bb_upper": snap.bb_upper, "bb_lower": snap.bb_lower,
            "change_pct": snap.change_pct, "momentum": snap.momentum, "atr": snap.atr,
            "recommendation": snap.recommendation, "buy_signals": snap.buy_signals,
            "sell_signals": snap.sell_signals,
        }
