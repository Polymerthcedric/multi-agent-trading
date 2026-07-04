from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TRADE_LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "logs", "trade_ledger.json",
)
PARAMS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "learned_parameters.json",
)
TRADE_CADENCE = 50


@dataclass
class TradeRecord:
    timestamp: float = 0.0
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    volatility_at_entry: float = 0.0
    volatility_regime: str = ""
    agent_confidences: Dict[str, float] = field(default_factory=dict)
    risk_multiplier: float = 1.0


class TradeLedger:
    def __init__(self, path: str = TRADE_LEDGER_PATH) -> None:
        self.path = path
        self.trades: List[TradeRecord] = []
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.load()

    def record_trade(self, trade: TradeRecord) -> None:
        self.trades.append(trade)
        logger.info(
            "TradeLedger | %s %s qty=%.4f entry=%.2f exit=%.2f pnl=%.2f",
            trade.symbol, trade.direction, trade.quantity,
            trade.entry_price, trade.exit_price, trade.pnl,
        )

    def close_trade(self, symbol: str, exit_price: float, exit_time: Optional[float] = None) -> Optional[TradeRecord]:
        for trade in self.trades:
            if trade.symbol == symbol and trade.exit_price == 0.0:
                trade.exit_price = exit_price
                trade.pnl = (exit_price - trade.entry_price) * trade.quantity
                trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price if trade.entry_price > 0 else 0.0
                if exit_time:
                    trade.timestamp = exit_time
                logger.info(
                    "TradeLedger | CLOSE %s pnl=%.2f pnl_pct=%.4f",
                    symbol, trade.pnl, trade.pnl_pct,
                )
                return trade
        return None

    def save(self) -> None:
        data = [asdict(t) for t in self.trades]
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(self.path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except:
            os.unlink(tmp_path)
            raise

    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.trades = [TradeRecord(**t) for t in data]
                logger.info("TradeLedger | loaded %d trades", len(self.trades))
            except Exception as e:
                logger.warning("TradeLedger | load failed: %s", e)

    def get_recent(self, n: int = 100) -> List[TradeRecord]:
        return self.trades[-n:]

    def get_open_trades(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.exit_price == 0.0]

    def total_trades(self) -> int:
        return len(self.trades)


@dataclass
class LearnedParameters:
    confidence_threshold: float = 0.55
    position_sizing_k: float = 0.25
    volatility_lookback: int = 14
    low_vol_threshold: float = 0.15
    high_vol_threshold: float = 0.35
    risk_per_trade_pct: float = 0.02
    trailing_stop_pct: float = 0.02
    max_allocation_pct: float = 0.25
    performance_score: float = 0.0


class SelfLearningCritic:
    def __init__(self, cadence: int = TRADE_CADENCE) -> None:
        self.cadence = cadence
        self._params: LearnedParameters = self._load_params()

    def evaluate(self, trade_ledger: TradeLedger) -> Optional[LearnedParameters]:
        total = trade_ledger.total_trades()
        if total == 0 or total % self.cadence != 0:
            return None

        recent = trade_ledger.get_recent(self.cadence)
        if not recent:
            return None

        logger.info("Critic | evaluating %d trades at cadence=%d", len(recent), self.cadence)

        wins = [t for t in recent if t.pnl > 0]
        losses = [t for t in recent if t.pnl <= 0]
        win_rate = len(wins) / len(recent) if recent else 0.0

        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 1.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 1.0

        returns = [t.pnl_pct for t in recent if isinstance(t.pnl_pct, (int, float))]
        sharpe = 0.0
        if len(returns) > 1:
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

        self._params.performance_score = sharpe
        self._params.confidence_threshold = self._tune_confidence(win_rate, profit_factor)
        self._params.position_sizing_k = self._tune_kelly(win_rate, profit_factor)

        self._save_params(self._params)
        logger.info(
            "Critic | params updated: conf_thresh=%.4f kelly_k=%.4f sharpe=%.4f",
            self._params.confidence_threshold, self._params.position_sizing_k, sharpe,
        )
        return self._params

    def get_parameters(self) -> LearnedParameters:
        return LearnedParameters(**asdict(self._params))

    def _tune_confidence(self, win_rate: float, profit_factor: float) -> float:
        base = 0.55
        if profit_factor > 1.5 and win_rate > 0.5:
            return max(0.45, base - 0.05)
        elif profit_factor < 1.0 or win_rate < 0.4:
            return min(0.70, base + 0.10)
        return base

    def _tune_kelly(self, win_rate: float, profit_factor: float) -> float:
        p = win_rate
        b = profit_factor
        kelly = ((b * p) - (1.0 - p)) / b if b > 0 else 0.0
        return max(0.05, min(0.50, kelly * 0.5))

    def _load_params(self) -> LearnedParameters:
        if os.path.exists(PARAMS_PATH):
            try:
                with open(PARAMS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("Critic | loaded params from %s", PARAMS_PATH)
                return LearnedParameters(**data)
            except Exception as e:
                logger.warning("Critic | load params failed: %s", e)
        return LearnedParameters()

    def _save_params(self, params: LearnedParameters) -> None:
        os.makedirs(os.path.dirname(PARAMS_PATH), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(PARAMS_PATH))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(params), f, indent=2)
            os.replace(tmp_path, PARAMS_PATH)
        except:
            os.unlink(tmp_path)
            raise
        logger.info("Critic | saved params to %s", PARAMS_PATH)
