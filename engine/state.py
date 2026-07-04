from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

STATE_DIM = 24


@dataclass
class OrderBookImbalance:
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    ratio: float = 0.0
    mid_price: float = 0.0

    def update(self, bids: List[tuple], asks: List[tuple]) -> None:
        self.bid_volume = sum(v for _, v in bids) if bids else 0.0
        self.ask_volume = sum(v for _, v in asks) if asks else 0.0
        total = self.bid_volume + self.ask_volume
        self.ratio = (self.bid_volume - self.ask_volume) / total if total > 0 else 0.0
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        self.mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0


@dataclass
class PairsZScore:
    symbol_a: str = ""
    symbol_b: str = ""
    beta: float = 1.0
    spread_history: List[float] = field(default_factory=list)
    z_score: float = 0.0
    lookback: int = 30

    def update(self, price_a: float, price_b: float) -> float:
        spread = math.log(price_a) - self.beta * math.log(price_b) if price_a > 0 and price_b > 0 else 0.0
        self.spread_history.append(spread)
        if len(self.spread_history) > self.lookback:
            self.spread_history.pop(0)
        if len(self.spread_history) < 10:
            self.z_score = 0.0
            return self.z_score
        mu = sum(self.spread_history) / len(self.spread_history)
        var = sum((s - mu) ** 2 for s in self.spread_history) / len(self.spread_history)
        std = math.sqrt(var) if var > 0 else 1e-10
        self.z_score = (spread - mu) / std
        return self.z_score


@dataclass
class MarketState:
    symbol: str = ""
    price: float = 0.0
    position: float = 0.0
    avg_entry: float = 0.0
    cash: float = 0.0
    portfolio_value: float = 0.0

    rsi: float = 50.0
    sma: float = 0.0
    ema: float = 0.0
    atr: float = 0.0
    momentum: float = 0.0
    adx: float = 0.0
    volume: float = 0.0

    ob_imbalance: OrderBookImbalance = field(default_factory=OrderBookImbalance)
    pairs_z: PairsZScore = field(default_factory=PairsZScore)
    price_history: List[float] = field(default_factory=list)
    volatility_index: float = 0.0
    z_score_self: float = 0.0

    drawdown_pct: float = 0.0
    peak_value: float = 0.0
    unrealized_pnl: float = 0.0

    # Normalization constants below assume equity/forex assets trading below ~200k.
    # For high-price assets (e.g. BTC > 200k), review and adjust divisors accordingly.
    def to_vector(self) -> np.ndarray:
        vec = np.zeros(STATE_DIM, dtype=np.float64)
        vec[0] = self.price / 100000.0
        vec[1] = self.position / 10.0
        vec[2] = (self.avg_entry / 100000.0) if self.avg_entry > 0 else 0.0
        vec[3] = self.cash / 100000.0
        vec[4] = self.portfolio_value / 100000.0
        vec[5] = self.rsi / 100.0
        vec[6] = (self.sma / 100000.0) if self.sma > 0 else 0.0
        vec[7] = (self.ema / 100000.0) if self.ema > 0 else 0.0
        vec[8] = self.atr / 1000.0
        vec[9] = max(-1.0, min(1.0, self.momentum / 10.0))
        vec[10] = self.adx / 100.0
        vec[11] = math.log1p(self.volume) if self.volume > 0 else 0.0
        vec[12] = self.ob_imbalance.ratio
        vec[13] = max(-5.0, min(5.0, self.pairs_z.z_score / 3.0))
        vec[14] = min(1.0, self.volatility_index / 2.0)
        vec[15] = max(-3.0, min(3.0, self.z_score_self))
        vec[16] = max(-0.5, min(0.0, self.drawdown_pct))
        vec[17] = self.unrealized_pnl / 100000.0
        n = len(self.price_history)
        if n >= 2:
            returns = [0.0] * (n - 1)
            for i in range(1, n):
                prev = self.price_history[i - 1]
                returns[i - 1] = (self.price_history[i] - prev) / prev if prev > 0 else 0.0
            vec[18] = sum(returns) / len(returns) if returns else 0.0
            vec[19] = math.sqrt(sum(r * r for r in returns) / len(returns)) if returns else 0.0
        vec[20] = 1.0 if self.position > 0 else 0.0
        vec[21] = 1.0 if self.position < 0 else 0.0
        prev = self.price_history[-2] if n >= 2 else self.price
        vec[22] = (self.price - prev) / prev if prev > 0 else 0.0
        vec[23] = self.peak_value / 100000.0 if self.peak_value > 0 else 0.0
        return np.clip(vec, -10.0, 10.0)

    @classmethod
    def from_market_data(cls, symbol: str, md: Dict[str, float], state: Optional[MarketState] = None) -> MarketState:
        price = md.get("price") or 0.0
        s = cls(
            symbol=symbol,
            price=price,
            rsi=md.get("rsi", 50.0),
            sma=md.get("sma", 0.0),
            ema=md.get("ema", 0.0),
            atr=md.get("atr", price * 0.01),
            momentum=md.get("momentum", 0.0),
            adx=md.get("adx", 0.0),
            volume=md.get("volume", 0.0),
        )
        if state is not None:
            s.position = state.position
            s.avg_entry = state.avg_entry
            s.cash = state.cash
            s.portfolio_value = state.portfolio_value
            s.peak_value = state.peak_value
            s.ob_imbalance = state.ob_imbalance
            s.pairs_z = state.pairs_z
            s.price_history = list(state.price_history)
            s.drawdown_pct = (state.portfolio_value - s.peak_value) / s.peak_value if s.peak_value > 0 else 0.0
            s.unrealized_pnl = (price - s.avg_entry) * s.position if s.position != 0 else 0.0
        s.price_history.append(price)
        if len(s.price_history) > 50:
            s.price_history.pop(0)
        if len(s.price_history) >= 5:
            returns = [(s.price_history[i] - s.price_history[i - 1]) / s.price_history[i - 1] for i in range(1, len(s.price_history))]
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(var_r) if var_r > 0 else 0.001
            s.volatility_index = std_r * math.sqrt(252)
            if std_r > 0 and len(returns) > 1:
                s.z_score_self = (returns[-1] - mean_r) / std_r
        return s

    def simulate_step(self, action: str, fill_price: float, size: float, taker_fee: float = 0.0005) -> MarketState:
        s = MarketState.from_market_data(self.symbol, {"price": fill_price, "rsi": self.rsi, "sma": self.sma, "ema": self.ema, "atr": self.atr, "momentum": self.momentum, "adx": self.adx, "volume": self.volume}, state=self)
        s.price_history.append(fill_price)
        if len(s.price_history) > 50:
            s.price_history.pop(0)
        cost = 0.0
        if action == "BUY_LIMIT" and size > 0 and self.cash >= size * fill_price * (1 + taker_fee):
            cost = size * fill_price * (1 + taker_fee)
            s.cash -= cost
            s.position += size
            s.avg_entry = (self.avg_entry * abs(self.position) + fill_price * size) / abs(s.position) if s.avg_entry > 0 and self.position != 0 else fill_price
        elif action == "SELL_LIMIT" and size > 0 and self.position >= size:
            proceeds = size * fill_price * (1 - taker_fee)
            s.cash += proceeds
            s.position -= size
        elif action == "RISK_CLOSE" and self.position != 0:
            if self.position > 0:
                proceeds = abs(self.position) * fill_price * (1 - taker_fee)
                s.cash += proceeds
            else:
                cost = abs(self.position) * fill_price * (1 + taker_fee)
                s.cash -= cost
            s.position = 0.0
            s.avg_entry = 0.0
        s.portfolio_value = s.cash + s.position * fill_price
        s.unrealized_pnl = (fill_price - s.avg_entry) * s.position if s.position != 0 else 0.0
        s.peak_value = max(self.peak_value, s.portfolio_value)
        s.drawdown_pct = (s.portfolio_value - s.peak_value) / s.peak_value if s.peak_value > 0 else 0.0
        return s
