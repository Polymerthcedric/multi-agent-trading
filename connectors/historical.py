from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

YF_MAP: Dict[str, str] = {
    "GOLD/USD": "GC=F", "SILVER/USD": "SI=F",
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
    "SPY": "SPY", "QQQ": "QQQ",
}

_MODE_LIVE = "LIVE"
_MODE_PAPER = "PAPER"
_MODE_DEMO = "DEMO"


class HistoricalDataError(RuntimeError):
    pass


class HistoricalDataFeed:
    def __init__(self, mode: str = _MODE_PAPER) -> None:
        self.mode = mode
        self._cache: Dict[str, List[Dict]] = {}
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        try:
            import xfinance
            return "xfinance"
        except ImportError:
            pass
        try:
            import yfinance
            return "yfinance"
        except ImportError:
            pass
        return "synthetic"

    def is_available(self) -> bool:
        return self._backend in ("xfinance", "yfinance")

    def _is_live_or_paper(self) -> bool:
        return self.mode in (_MODE_LIVE, _MODE_PAPER)

    def fetch(self, symbol: str, days: int = 90, interval: str = "1h") -> List[Dict[str, float]]:
        cached = self._cache.get(symbol)
        if cached is not None:
            return cached

        yf_symbol = YF_MAP.get(symbol)
        if not yf_symbol:
            if self._is_live_or_paper():
                raise HistoricalDataError(f"No yfinance mapping for {symbol}")
            return self._synthetic_data(symbol, days)

        bars = None

        if self._backend == "xfinance":
            bars = self._fetch_xfinance(yf_symbol, symbol, days, interval)
        elif self._backend == "yfinance":
            bars = self._fetch_yfinance(yf_symbol, symbol, days, interval)

        if bars:
            self._cache[symbol] = bars
            return bars

        if self._is_live_or_paper():
            raise HistoricalDataError(f"Failed to fetch data for {symbol}")
        return self._synthetic_data(symbol, days)

    def _fetch_xfinance(self, yf_symbol: str, symbol: str, days: int, interval: str) -> Optional[List[Dict]]:
        try:
            import xfinance as xf
            t = xf.Ticker(yf_symbol)
            df = t.history(period=f"{days}d", interval=interval)
            if df is None or df.empty:
                return None
            records = []
            for idx, row in df.iterrows():
                records.append({
                    "timestamp": idx.timestamp() if hasattr(idx, "timestamp") else datetime.now().timestamp(),
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
            logger.info("xfinance | fetched %d bars for %s (%s)", len(records), symbol, yf_symbol)
            return records
        except Exception as e:
            logger.warning("xfinance fetch failed for %s: %s", symbol, e)
            return None

    def _fetch_yfinance(self, yf_symbol: str, symbol: str, days: int, interval: str) -> Optional[List[Dict]]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=f"{days}d", interval=interval)
            if df is None or df.empty:
                return None
            records = []
            for idx, row in df.iterrows():
                records.append({
                    "timestamp": idx.timestamp() if hasattr(idx, "timestamp") else datetime.now().timestamp(),
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
            logger.info("yfinance | fetched %d bars for %s (%s)", len(records), symbol, yf_symbol)
            return records
        except Exception as e:
            logger.warning("yfinance fetch failed for %s: %s", symbol, e)
            return None

    def compute_features(self, bars: List[Dict]) -> Dict[str, np.ndarray]:
        closes = np.array([b["close"] for b in bars], dtype=np.float64)
        highs = np.array([b["high"] for b in bars], dtype=np.float64)
        lows = np.array([b["low"] for b in bars], dtype=np.float64)
        volumes = np.array([b["volume"] for b in bars], dtype=np.float64)
        n = len(closes)
        features: Dict[str, np.ndarray] = {}

        if n >= 2:
            returns = np.diff(closes) / closes[:-1]
            features["returns"] = returns

        if n >= 14:
            gains = np.maximum(0, np.diff(closes))
            losses = np.maximum(0, -np.diff(closes))
            avg_gain = np.convolve(gains, np.ones(14) / 14, mode="valid")[:len(closes) - 14 + 1]
            avg_loss = np.convolve(losses, np.ones(14) / 14, mode="valid")[:len(closes) - 14 + 1]
            avg_loss = np.where(avg_loss == 0, 1e-10, avg_loss)
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            padded = np.full(n, 50.0)
            padded[-len(rsi):] = rsi
            features["rsi"] = padded

        if n >= 20:
            sma20 = np.convolve(closes, np.ones(20) / 20, mode="valid")
            padded = np.full(n, closes[0])
            padded[-len(sma20):] = sma20
            features["sma20"] = padded

        if n >= 2:
            returns = features.get("returns", np.diff(closes) / closes[:-1])
            if len(returns) > 1:
                vol = np.std(returns) * np.sqrt(252)
                features["volatility_index"] = np.full(n, vol)

        features["close"] = closes
        features["high"] = highs
        features["low"] = lows
        features["volume"] = volumes
        return features

    def _synthetic_data(self, symbol: str, days: int) -> List[Dict]:
        import random
        base_prices = {
            "GOLD/USD": 2350, "SILVER/USD": 28.5,
            "EUR/USD": 1.14, "GBP/USD": 1.33, "USD/JPY": 161,
            "AAPL": 195, "MSFT": 420, "GOOGL": 175,
            "SPY": 520, "QQQ": 450,
        }
        base = base_prices.get(symbol, 100.0)
        bars = []
        price = base
        n_bars = days * 8 if days <= 30 else days
        for i in range(n_bars):
            ret = random.gauss(0.0001, 0.005)
            price *= (1.0 + ret)
            bars.append({
                "timestamp": (datetime.now() - timedelta(hours=n_bars - i)).timestamp(),
                "open": round(price / (1 + ret * 0.5), 2),
                "high": round(price * (1 + abs(ret) * 0.5), 2),
                "low": round(price * (1 - abs(ret) * 0.5), 2),
                "close": round(price, 2),
                "volume": random.randint(1000, 100000),
            })
        logger.info("HistoricalDataFeed | DEMO synthetic: %d bars for %s", len(bars), symbol)
        return bars
