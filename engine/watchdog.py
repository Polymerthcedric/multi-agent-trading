from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataQualityWatchdog:
    def __init__(self, max_stale_seconds: float = 3600.0, max_consecutive_failures: int = 3) -> None:
        self.max_stale_seconds = max_stale_seconds
        self.max_consecutive_failures = max_consecutive_failures
        self._last_success: Dict[str, float] = {}
        self._failure_count: Dict[str, int] = {}
        self._alerts: List[Dict] = []
        self._mode: str = "PAPER"

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def record_success(self, source: str, symbol: str) -> None:
        key = f"{source}:{symbol}"
        self._last_success[key] = time.time()
        self._failure_count[key] = 0

    def record_failure(self, source: str, symbol: str, error: str) -> None:
        key = f"{source}:{symbol}"
        self._failure_count[key] = self._failure_count.get(key, 0) + 1
        count = self._failure_count[key]
        if count >= self.max_consecutive_failures:
            alert = {
                "timestamp": time.time(),
                "source": source,
                "symbol": symbol,
                "type": "consecutive_failure",
                "count": count,
                "error": error,
                "mode": self._mode,
            }
            self._alerts.append(alert)
            logger.warning("WATCHDOG ALERT | %s:%s %d consecutive failures — %s", source, symbol, count, error)

    def check_staleness(self, source: str, symbol: str) -> Optional[Dict]:
        key = f"{source}:{symbol}"
        last = self._last_success.get(key)
        if last is None:
            return None
        elapsed = time.time() - last
        if elapsed > self.max_stale_seconds:
            alert = {
                "timestamp": time.time(),
                "source": source,
                "symbol": symbol,
                "type": "stale_data",
                "staleness_seconds": round(elapsed, 1),
                "mode": self._mode,
            }
            self._alerts.append(alert)
            return alert
        return None

    def get_active_alerts(self, max_age_seconds: float = 300.0) -> List[Dict]:
        now = time.time()
        if len(self._alerts) > 1000:
            cutoff = now - max_age_seconds * 2
            self._alerts = [a for a in self._alerts if a["timestamp"] > cutoff]
        return [a for a in self._alerts if now - a["timestamp"] < max_age_seconds]

    def has_critical_alerts(self) -> bool:
        active = self.get_active_alerts()
        critical_types = {"consecutive_failure", "stale_data"}
        return any(a["type"] in critical_types and a.get("mode") in ("LIVE", "PAPER") for a in active)

    def summary(self) -> Dict:
        active = self.get_active_alerts()
        return {
            "total_alerts": len(self._alerts),
            "active_alerts": len(active),
            "critical": self.has_critical_alerts(),
            "mode": self._mode,
            "sources_monitored": len(self._last_success),
            "sources_failing": sum(1 for v in self._failure_count.values() if v >= self.max_consecutive_failures),
        }
