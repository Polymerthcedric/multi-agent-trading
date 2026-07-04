from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class Settings:
    exchange_api_key: str = os.getenv("EXCHANGE_API_KEY", "placeholder_key")
    exchange_secret: str = os.getenv("EXCHANGE_SECRET", "placeholder_secret")
    exchange_passphrase: str = os.getenv("EXCHANGE_PASSPHRASE", "")

    def __repr__(self) -> str:
        cls = type(self).__name__
        return (
            f"{cls}(exchange_api_key='***', exchange_secret='***', "
            f"exchange_passphrase='***', paper_trading={self.paper_trading}, "
            f"log_level='{self.log_level}', log_file='{self.log_file}', "
            f"simulation_tick_interval_sec={self.simulation_tick_interval_sec}, "
            f"max_daily_trades={self.max_daily_trades}, "
            f"symbols={self.symbols}, "
            f"max_daily_drawdown_pct={self.max_daily_drawdown_pct}, "
            f"max_position_size_pct={self.max_position_size_pct}, "
            f"max_risk_per_trade_pct={self.max_risk_per_trade_pct}, "
            f"learning_cadence_trades={self.learning_cadence_trades})"
        )

    paper_trading: bool = True
    log_level: str = "INFO"
    log_file: str = "trading_bot.log"

    simulation_tick_interval_sec: float = 1.0
    max_daily_trades: int = 10

    symbols: Tuple[str, ...] = field(default_factory=lambda: (
        "BTC/USD", "ETH/USD", "SOL/USD",
        "GOLD/USD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
    ))

    max_daily_drawdown_pct: float = 0.02
    max_position_size_pct: float = 0.25
    max_risk_per_trade_pct: float = 0.02
    learning_cadence_trades: int = 50
