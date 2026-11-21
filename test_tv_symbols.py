"""Manual check for the TradingView data feed.

Run with ``python test_tv_symbols.py``. This script calls a live data provider;
it is not a pytest test and is excluded from the automated suite.
"""
from __future__ import annotations

import asyncio

from connectors.tv_datafeed import TradingViewFeed


async def check_symbols() -> None:
    feed = TradingViewFeed()
    for sym in feed.symbols:
        snap = await feed.get_snapshot(sym)
        if snap.price > 0:
            print(f"OK  {sym:12s} price={snap.price:>12.4f} RSI={snap.rsi:>8.2f} rec={snap.recommendation}")
        else:
            print(f"FAIL {sym:12s} no data")


if __name__ == "__main__":
    asyncio.run(check_symbols())
