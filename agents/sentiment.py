"""
Sentiment Analysis Agent — Free, no API key required.

Uses yfinance news feeds + keyword-based scoring.
Inspired by TradingAgents and Freqtrade's sentiment pipelines.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BULLISH_WORDS = {
    "surge", "rally", "gain", "rise", "jump", "soar", "bull", "bullish",
    "upgrade", "beat", "exceed", "outperform", "strong", "growth", "profit",
    "record", "high", "breakout", "momentum", "buy", "accumulate", "moon",
    "green", "positive", "optimistic", "recovery", "rebound", "uptrend",
    "demand", "boom", "expansion", "upbeat", "confident",
}

BEARISH_WORDS = {
    "crash", "drop", "fall", "decline", "loss", "bear", "bearish",
    "downgrade", "miss", "weak", "fear", "sell", "dump", "plunge",
    "correction", "recession", "inflation", "risk", "warning", "cut",
    "red", "negative", "pessimistic", "slump", "downturn", "collapse",
    "bankruptcy", "debt", "crisis", "panic", "uncertainty", "volatile",
}

SENTIMENT_WINDOW_HOURS = 24


@dataclass
class SentimentResult:
    symbol: str = ""
    score: float = 0.0
    label: str = "neutral"
    confidence: float = 0.0
    news_count: int = 0
    bullish_signals: int = 0
    bearish_signals: int = 0
    headlines: List[str] = field(default_factory=list)
    reasoning: Dict[str, object] = field(default_factory=dict)


class SentimentAgent:
    name: str = "sentiment"

    def __init__(self) -> None:
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl: float = 300.0
        self._last_fetch: Dict[str, float] = {}

    def _get_news(self, symbol: str) -> List[Dict]:
        try:
            import yfinance as yf
            ticker_map = {
                "GOLD/USD": "GC=F", "SILVER/USD": "SI=F",
                "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
                "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
                "SPY": "SPY", "QQQ": "QQQ",
            }
            yf_sym = ticker_map.get(symbol, symbol)
            ticker = yf.Ticker(yf_sym)
            news = ticker.news or []
            return news[:20]
        except Exception as e:
            logger.warning("SentimentAgent | news fetch failed for %s: %s", symbol, e)
            return []

    def _score_headline(self, text: str) -> float:
        text_lower = text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))
        bullish = len(words & BULLISH_WORDS)
        bearish = len(words & BEARISH_WORDS)
        total = bullish + bearish
        if total == 0:
            return 0.0
        return (bullish - bearish) / total

    async def analyze(self, symbol: str, market_data: Optional[Dict] = None) -> SentimentResult:
        now = time.time()

        cached = self._cache.get(symbol)
        if cached and (now - self._last_fetch.get(symbol, 0)) < self._cache_ttl:
            return cached

        news = self._get_news(symbol)
        if not news:
            result = SentimentResult(
                symbol=symbol, score=0.0, label="neutral",
                confidence=0.0, news_count=0,
                reasoning={"status": "no_news_available"},
            )
            return result

        scores = []
        bullish_count = 0
        bearish_count = 0
        headlines = []

        for item in news:
            title = item.get("title", "")
            if not title:
                continue
            score = self._score_headline(title)
            scores.append(score)
            if score > 0:
                bullish_count += 1
            elif score < 0:
                bearish_count += 1
            headlines.append(title[:80])

        avg_score = sum(scores) / len(scores) if scores else 0.0
        total_signals = bullish_count + bearish_count
        confidence = min(1.0, total_signals / max(len(news), 1))

        if avg_score > 0.15:
            label = "bullish"
        elif avg_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        result = SentimentResult(
            symbol=symbol,
            score=round(avg_score, 4),
            label=label,
            confidence=round(confidence, 4),
            news_count=len(news),
            bullish_signals=bullish_count,
            bearish_signals=bearish_count,
            headlines=headlines[:5],
            reasoning={
                "avg_sentiment_score": round(avg_score, 4),
                "bullish_headlines": bullish_count,
                "bearish_headlines": bearish_count,
                "neutral_headlines": len(news) - total_signals,
                "total_news": len(news),
                "confidence": round(confidence, 4),
            },
        )

        self._cache[symbol] = result
        self._last_fetch[symbol] = now

        logger.info(
            "SentimentAgent | %s score=%.3f label=%s conf=%.2f news=%d (bull=%d bear=%d)",
            symbol, avg_score, label, confidence, len(news), bullish_count, bearish_count,
        )

        return result
