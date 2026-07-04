import asyncio
from connectors.tv_datafeed import TradingViewFeed

async def test():
    feed = TradingViewFeed()
    for sym in feed.symbols:
        snap = await feed.get_snapshot(sym)
        if snap.price > 0:
            print(f"OK  {sym:12s} price={snap.price:>12.4f} RSI={snap.rsi:>8.2f} rec={snap.recommendation}")
        else:
            print(f"FAIL {sym:12s} no data")

asyncio.run(test())
