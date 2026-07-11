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
    max_daily_trades: int = 20

    symbols: Tuple[str, ...] = field(default_factory=lambda: (
        "GOLD/USD", "SILVER/USD",
        "EUR/USD", "GBP/USD", "USD/JPY",
        "AAPL", "MSFT", "GOOGL",
        "SPY", "QQQ",
    ))

    max_daily_drawdown_pct: float = 0.03
    max_position_size_pct: float = 0.20
    max_risk_per_trade_pct: float = 0.015
    learning_cadence_trades: int = 25

    max_daily_loss_pct: float = 0.03
    max_weekly_loss_pct: float = 0.05
    max_drawdown_halt_pct: float = 0.07
    max_trades_per_day: int = 15
    min_risk_reward_ratio: float = 1.5
