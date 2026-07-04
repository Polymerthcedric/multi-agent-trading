from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

YF_MAP: Dict[str, str] = {
    "BTC/USD": "BTC-USD", "ETH/USD": "ETH-USD", "SOL/USD": "SOL-USD",
    "GOLD/USD": "GC=F", "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X", "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X",
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
        self._yf_available = self._check_yf()

    def _check_yf(self) -> bool:
        try:
            import yfinance
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        return self._yf_available

    def _is_live_or_paper(self) -> bool:
        return self.mode in (_MODE_LIVE, _MODE_PAPER)

    def fetch(self, symbol: str, days: int = 90, interval: str = "1h") -> List[Dict[str, float]]:
        cached = self._cache.get(symbol)
        if cached is not None:
            logger.debug("HistoricalDataFeed | returning %d cached bars for %s", len(cached), symbol)
            return cached

        if not self._yf_available:
            msg = f"yfinance not installed. Cannot fetch historical data for {symbol} [mode={self.mode}]"
            if self._is_live_or_paper():
                raise HistoricalDataError(msg)
            logger.warning(msg + " — falling back to synthetic (DEMO only)")
            return self._synthetic_data(symbol, days)

        yf_symbol = YF_MAP.get(symbol)
        if not yf_symbol:
            msg = f"No yfinance mapping for {symbol}"
            if self._is_live_or_paper():
                raise HistoricalDataError(msg)
            logger.warning(msg + " — falling back to synthetic (DEMO only)")
            return self._synthetic_data(symbol, days)

        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_symbol)
            period = f"{days}d"
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                msg = f"yfinance returned empty DataFrame for {symbol} ({yf_symbol})"
                if self._is_live_or_paper():
                    raise HistoricalDataError(msg)
                logger.warning(msg + " — synthetic fallback (DEMO only)")
                return self._synthetic_data(symbol, days)

            records = []
            for idx, row in df.iterrows():
                records.append({
                    "timestamp": idx.timestamp() if hasattr(idx, "timestamp") else datetime.now().timestamp(),
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": float(row["Volume"]),
                })
            self._cache[symbol] = records
            logger.info("yfinance | fetched %d bars for %s (%s)", len(records), symbol, yf_symbol)
            return records
        except HistoricalDataError:
            raise
        except Exception as e:
            msg = f"yfinance fetch error for {symbol}: {e}"
            if self._is_live_or_paper():
                raise HistoricalDataError(msg) from e
            logger.warning(msg + " — synthetic fallback (DEMO only)")
            return self._synthetic_data(symbol, days)

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

        if n >= 2 and n <= 50:
            vol = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.0
            features["volatility_index"] = np.full(n, vol)
        elif n > 50:
            vol_series = np.array([
                np.std(returns[max(0, i - 20):i + 1]) * np.sqrt(252)
                for i in range(len(returns))
            ])
            padded = np.full(n, 0.2)
            padded[-len(vol_series):] = vol_series
            features["volatility_index"] = padded

        features["close"] = closes
        features["high"] = highs
        features["low"] = lows
        features["volume"] = volumes
        return features

    def _synthetic_data(self, symbol: str, days: int) -> List[Dict]:
        import random
        base_prices = {
            "BTC/USD": 62000, "ETH/USD": 1750, "SOL/USD": 82,
            "GOLD/USD": 2350, "EUR/USD": 1.14, "GBP/USD": 1.33,
            "USD/JPY": 161, "USD/CHF": 0.80, "AUD/USD": 0.69,
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
