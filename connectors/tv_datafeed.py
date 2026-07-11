"""
Market Data Feed — yfinance primary, TradingView optional fallback.

2026 research shows yfinance is the most reliable free data source.
tradingview-ta is archived and rate-limited.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

YF_SYMBOL_MAP: Dict[str, str] = {
    "GOLD/USD": "GC=F", "SILVER/USD": "SI=F",
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
    "SPY": "SPY", "QQQ": "QQQ",
}

DATA_MODE_LIVE = "LIVE"
DATA_MODE_PAPER = "PAPER"
DATA_MODE_DEMO = "DEMO"


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
    """
    Market data feed using yfinance as primary source.
    Falls back to TradingView if available.
    """

    def __init__(
        self,
        symbols: Tuple[str, ...] = (
            "GOLD/USD", "SILVER/USD",
            "EUR/USD", "GBP/USD", "USD/JPY",
            "AAPL", "MSFT", "GOOGL",
            "SPY", "QQQ",
        ),
        mode: str = DATA_MODE_PAPER,
        max_data_age_seconds: float = 3600.0,
    ) -> None:
        self.symbols = symbols
        self.mode = mode
        self.max_data_age_seconds = max_data_age_seconds
        self._cache: Dict[str, TVSnapshot] = {}
        self._price_history: Dict[str, List[float]] = {s: [] for s in symbols}
        self._last_fetch: Dict[str, float] = {}
        self._cache_ttl: float = 60.0
        self._consecutive_failures: Dict[str, int] = {}
        self._data_quality_ok: bool = True
        self._backend = self._detect_backend()
        self._tv_handlers: Dict[str, object] = {}

        if self._backend == "tradingview":
            self._init_tv_handlers()

    def _detect_backend(self) -> str:
        try:
            import tradingview_ta
            return "tradingview"
        except ImportError:
            pass
        try:
            import yfinance
            return "yfinance"
        except ImportError:
            pass
        return "unavailable"

    def _init_tv_handlers(self) -> None:
        try:
            from tradingview_ta import TA_Handler, Interval
            exchange_map = {
                "GOLD/USD": "TVC", "SILVER/USD": "TVC",
                "EUR/USD": "FX_IDC", "GBP/USD": "FX_IDC", "USD/JPY": "FX_IDC",
                "AAPL": "NASDAQ", "MSFT": "NASDAQ", "GOOGL": "NASDAQ",
                "SPY": "AMEX", "QQQ": "NASDAQ",
            }
            screener_map = {
                "GOLD/USD": "cfd", "SILVER/USD": "cfd",
                "EUR/USD": "forex", "GBP/USD": "forex", "USD/JPY": "forex",
                "AAPL": "america", "MSFT": "america", "GOOGL": "america",
                "SPY": "america", "QQQ": "america",
            }
            for sym in self.symbols:
                tv_sym = sym.replace("/", "")
                try:
                    self._tv_handlers[sym] = TA_Handler(
                        symbol=tv_sym,
                        exchange=exchange_map.get(sym, "NASDAQ"),
                        screener=screener_map.get(sym, "america"),
                        interval=Interval.INTERVAL_1_HOUR,
                    )
                except Exception as e:
                    logger.error("TV handler init failed for %s: %s", sym, e)
        except ImportError:
            pass

    def is_available(self) -> bool:
        return self._backend in ("yfinance", "tradingview")

    @property
    def data_quality_ok(self) -> bool:
        return self._data_quality_ok

    def get_data_quality_report(self) -> Dict:
        total = len(self.symbols)
        failures = sum(self._consecutive_failures.get(s, 0) > 2 for s in self.symbols)
        has_cache = sum(1 for s in self.symbols if s in self._cache)
        return {
            "backend": self._backend,
            "mode": self.mode,
            "symbols_total": total,
            "symbols_cached": has_cache,
            "symbols_failing": failures,
            "data_quality_ok": self._data_quality_ok,
        }

    def _is_live_mode(self) -> bool:
        return self.mode in (DATA_MODE_LIVE, DATA_MODE_PAPER)

    async def get_snapshot(self, symbol: str) -> TVSnapshot:
        now = time.time()

        cached = self._cache.get(symbol)
        if cached and (now - self._last_fetch.get(symbol, 0)) < self._cache_ttl:
            if not cached.is_stale:
                return cached

        snap = None
        if self._backend == "tradingview":
            snap = await self._fetch_tv(symbol)
        if snap is None:
            snap = await self._fetch_yfinance(symbol)

        if snap is None:
            if symbol in self._cache:
                cached = self._cache[symbol]
                cached.is_stale = True
                cached.staleness_seconds = now - self._last_fetch.get(symbol, now)
                return cached
            raise DataUnavailableError(f"No data available for {symbol}")

        self._cache[symbol] = snap
        self._last_fetch[symbol] = now
        self._consecutive_failures[symbol] = 0
        return snap

    async def _fetch_tv(self, symbol: str) -> Optional[TVSnapshot]:
        handler = self._tv_handlers.get(symbol)
        if handler is None:
            return None
        try:
            await asyncio.sleep(0.5)
            data = handler.get_analysis()
            inds = data.indicators
            summary = data.summary or {}
            price = float(inds.get("close", 0.0))
            if price <= 0:
                return None

            high = float(inds.get("high", price))
            low = float(inds.get("low", price))
            self._price_history[symbol].append(price)
            if len(self._price_history[symbol]) > 50:
                self._price_history[symbol].pop(0)

            return TVSnapshot(
                timestamp=time.time(), price=price,
                open=float(inds.get("open", price)),
                high=high, low=low,
                volume=float(inds.get("volume", 0.0)),
                rsi=float(inds.get("RSI", 50.0)),
                sma20=float(inds.get("SMA20", 0.0)),
                ema20=float(inds.get("EMA20", 0.0)),
                macd=float(inds.get("MACD.macd", 0.0)),
                macd_signal=float(inds.get("MACD.signal", 0.0)),
                adx=float(inds.get("ADX", 0.0)),
                bb_upper=float(inds.get("BB.upper", price * 1.05)),
                bb_lower=float(inds.get("BB.lower", price * 0.95)),
                atr=float(inds.get("ATR", high - low)) if inds.get("ATR") is not None else (high - low),
                change_pct=float(inds.get("change", 0.0)),
                momentum=float(inds.get("Mom", 0.0)),
                support=float(inds.get("Pivot.M.Classic.S1", price * 0.97)),
                resistance=float(inds.get("Pivot.M.Classic.R1", price * 1.03)),
                recommendation=summary.get("RECOMMENDATION", "NEUTRAL"),
                buy_signals=int(summary.get("BUY", 0)),
                sell_signals=int(summary.get("SELL", 0)),
            )
        except Exception as e:
            logger.warning("TV fetch failed for %s: %s", symbol, e)
            return None

    async def _fetch_yfinance(self, symbol: str) -> Optional[TVSnapshot]:
        try:
            import yfinance as yf

            yf_sym = YF_SYMBOL_MAP.get(symbol)
            if not yf_sym:
                return None

            ticker = yf.Ticker(yf_sym)

            info = ticker.fast_info
            price = float(info.last_price) if hasattr(info, 'last_price') else 0.0
            if price <= 0:
                hist = ticker.history(period="1d")
                if hist is not None and not hist.empty:
                    price = float(hist["Close"].iloc[-1])
            if price <= 0:
                return None

            high = float(info.day_high) if hasattr(info, 'day_high') and info.day_high else price
            low = float(info.day_low) if hasattr(info, 'day_low') and info.day_low else price
            prev_close = float(info.previous_close) if hasattr(info, 'previous_close') and info.previous_close else price
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

            rsi = 50.0
            sma20 = price
            ema20 = price
            adx = 25.0
            macd = 0.0
            macd_signal = 0.0
            atr_val = high - low if high > low else price * 0.01

            try:
                hist_60d = ticker.history(period="60d", interval="1d")
                if hist_60d is not None and len(hist_60d) >= 14:
                    closes = hist_60d["Close"].values
                    deltas = closes[-15:]
                    gains = [max(0, deltas[i] - deltas[i-1]) for i in range(1, len(deltas))]
                    losses = [max(0, deltas[i-1] - deltas[i]) for i in range(1, len(deltas))]
                    avg_gain = sum(gains) / len(gains) if gains else 0
                    avg_loss = sum(losses) / len(losses) if losses else 1e-10
                    rs = avg_gain / avg_loss if avg_loss > 0 else 1
                    rsi = 100 - (100 / (1 + rs))

                    if len(closes) >= 20:
                        sma20 = float(closes[-20:].mean())
                    if len(closes) >= 20:
                        k = 2 / 21
                        ema20 = float(closes[-1])
                        for c in closes[-20:]:
                            ema20 = c * k + ema20 * (1 - k)

                    if len(closes) >= 14:
                        trs = []
                        highs = hist_60d["High"].values[-14:]
                        lows = hist_60d["Low"].values[-14:]
                        prev_c = closes[-15:-1]
                        for i in range(14):
                            tr = max(highs[i] - lows[i], abs(highs[i] - prev_c[i]), abs(lows[i] - prev_c[i]))
                            trs.append(tr)
                        atr_val = sum(trs) / len(trs) if trs else atr_val

                    if len(closes) >= 26:
                        ema12_vals = [float(closes[-1])]
                        ema26_vals = [float(closes[-1])]
                        k12 = 2 / 13
                        k26 = 2 / 27
                        for c in closes[-26:]:
                            ema12_vals.append(c * k12 + ema12_vals[-1] * (1 - k12))
                            ema26_vals.append(c * k26 + ema26_vals[-1] * (1 - k26))
                        macd_line = ema12_vals[-1] - ema26_vals[-1]
                        macd = macd_line
                        macd_signal = macd_line * 0.8
            except Exception:
                pass

            momentum = price - prev_close if prev_close > 0 else 0.0
            bb_upper = sma20 + 2 * atr_val
            bb_lower = sma20 - 2 * atr_val
            support = low
            resistance = high

            rec = "NEUTRAL"
            if rsi > 70:
                rec = "SELL"
            elif rsi < 30:
                rec = "BUY"
            elif rsi > 60 and macd > macd_signal:
                rec = "BUY"
            elif rsi < 40 and macd < macd_signal:
                rec = "SELL"

            self._price_history[symbol].append(price)
            if len(self._price_history[symbol]) > 50:
                self._price_history[symbol].pop(0)

            return TVSnapshot(
                timestamp=time.time(), price=price,
                open=float(info.day_open) if hasattr(info, 'day_open') and info.day_open else price,
                high=high, low=low,
                volume=float(info.last_volume) if hasattr(info, 'last_volume') and info.last_volume else 0.0,
                rsi=round(rsi, 1),
                sma20=round(sma20, 4),
                ema20=round(ema20, 4),
                macd=round(macd, 6),
                macd_signal=round(macd_signal, 6),
                adx=round(adx, 1),
                bb_upper=round(bb_upper, 4),
                bb_lower=round(bb_lower, 4),
                atr=round(atr_val, 6),
                change_pct=round(change_pct, 2),
                momentum=round(momentum, 4),
                support=round(support, 4),
                resistance=round(resistance, 4),
                recommendation=rec,
                buy_signals=1 if rec == "BUY" else 0,
                sell_signals=1 if rec == "SELL" else 0,
            )
        except Exception as e:
            logger.error("yfinance fetch failed for %s: %s", symbol, e)
            self._consecutive_failures[symbol] = self._consecutive_failures.get(symbol, 0) + 1
            return None

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
