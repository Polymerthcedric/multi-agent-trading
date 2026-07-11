"""
Decision Logger — Inspired by TradingAgents' persistent decision logs.

Every decision is logged with full reasoning, agent outputs, and market state.
This enables the self-learning feedback loop and post-trade analysis.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DECISION_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "logs", "decision_log.json",
)


@dataclass
class DecisionRecord:
    timestamp: float = 0.0
    symbol: str = ""
    action: str = "HOLD"
    confidence: float = 0.0
    adjusted_confidence: float = 0.0
    allocation_pct: float = 0.0
    stop_loss: float = 0.0
    price: float = 0.0
    agent_outputs: Dict[str, Any] = field(default_factory=dict)
    debate_result: Dict[str, Any] = field(default_factory=dict)
    sentiment_result: Dict[str, Any] = field(default_factory=dict)
    risk_check: Dict[str, Any] = field(default_factory=dict)
    search_result: Dict[str, Any] = field(default_factory=dict)
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    reasoning_chain: List[str] = field(default_factory=list)
    execution_status: str = "pending"
    fill_price: float = 0.0
    quantity: float = 0.0


class DecisionLogger:
    def __init__(self, path: str = DECISION_LOG_PATH) -> None:
        self.path = path
        self.records: List[DecisionRecord] = []
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._load()

    def log(self, record: DecisionRecord) -> None:
        self.records.append(record)
        logger.info(
            "DecisionLog | %s %s conf=%.3f adj=%.3f alloc=%.2f%%",
            record.symbol, record.action, record.confidence,
            record.adjusted_confidence, record.allocation_pct * 100,
        )
        self._save()

    def update_execution(self, symbol: str, status: str, fill_price: float = 0.0, quantity: float = 0.0) -> None:
        for record in reversed(self.records):
            if record.symbol == symbol and record.execution_status == "pending":
                record.execution_status = status
                record.fill_price = fill_price
                record.quantity = quantity
                self._save()
                break

    def get_recent(self, n: int = 50) -> List[DecisionRecord]:
        return self.records[-n:]

    def get_by_symbol(self, symbol: str, n: int = 20) -> List[DecisionRecord]:
        return [r for r in self.records if r.symbol == symbol][-n:]

    def get_win_rate(self) -> float:
        executed = [r for r in self.records if r.execution_status == "executed"]
        if not executed:
            return 0.0
        wins = sum(1 for r in executed if r.action == "BUY" and r.fill_price > 0)
        return wins / len(executed) if executed else 0.0

    def _save(self) -> None:
        data = [asdict(r) for r in self.records[-1000:]]
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(self.path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.records = [DecisionRecord(**r) for r in data]
                logger.info("DecisionLog | loaded %d records", len(self.records))
            except Exception as e:
                logger.warning("DecisionLog | load failed: %s", e)
