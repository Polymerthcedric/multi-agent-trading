from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "logs", "learning_ledger.json",
)


@dataclass
class LedgerEntry:
    timestamp: float = 0.0
    symbol: str = ""
    action: int = 0
    action_label: str = ""
    price: float = 0.0
    quantity: float = 0.0
    state_vector: List[float] = field(default_factory=list)
    reward: float = 0.0
    portfolio_value_before: float = 0.0
    portfolio_value_after: float = 0.0
    transaction_cost: float = 0.0
    slippage: float = 0.0
    agent_reasoning: Dict[str, Any] = field(default_factory=dict)


class RuntimeLedger:
    def __init__(self, path: str = LEDGER_PATH) -> None:
        self.path = path
        self.entries: deque = deque(maxlen=10000)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.load()

    def record(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)
        logger.debug("Ledger | %s action=%d reward=%.6f", entry.symbol, entry.action, entry.reward)

    def save(self) -> None:
        data = [asdict(e) for e in self.entries]
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(self.path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except:
            os.unlink(tmp_path)
            raise
        logger.info("Ledger | saved %d entries to %s", len(self.entries), self.path)

    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entries = deque((LedgerEntry(**e) for e in data), maxlen=10000)
                logger.info("Ledger | loaded %d entries from %s", len(self.entries), self.path)
            except Exception as e:
                logger.warning("Ledger | load error: %s", e)

    def get_recent(self, n: int = 100) -> List[LedgerEntry]:
        entries_list = list(self.entries)
        return entries_list[-n:]

    def clear(self) -> None:
        self.entries.clear()
        self.save()
