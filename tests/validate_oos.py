from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("validate_oos")

sys.path.insert(0, ".")

from connectors.historical import HistoricalDataFeed
from engine.evaluator import StateEvaluator
from engine.state import MarketState

SYMBOLS_TO_TEST = ["GOLD/USD", "SILVER/USD", "EUR/USD", "AAPL"]
TRAIN_DAYS = 90
TEST_DAYS = 30
SLIPPAGE_BPS = 2.0
COMMISSION_PCT = 0.001


def load_bars(symbol: str, days: int) -> List[Dict]:
    feed = HistoricalDataFeed(mode="DEMO")
    logger.info("Loading %dd of %s...", days, symbol)
    bars = feed.fetch(symbol, days=days, interval="1h")
    logger.info("  got %d bars", len(bars))
    return bars


def compute_sharpe(returns: List[float], annual_factor: float = 252 * 6.5) -> float:
    if len(returns) < 2:
        return 0.0
    mean_r = np.mean(returns)
    std_r = np.std(returns)
    if std_r == 0:
        return 0.0
    return (mean_r / std_r) * np.sqrt(annual_factor)


def compute_max_drawdown(equity: List[float]) -> float:
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
    return mdd


def run_backtest(
    symbol: str,
    bars: List[Dict],
    evaluator: StateEvaluator,
) -> Dict:
    closes = np.array([b["close"] for b in bars], dtype=np.float64)
    highs = np.array([b["high"] for b in bars], dtype=np.float64)
    lows = np.array([b["low"] for b in bars], dtype=np.float64)

    cash = 100000.0
    position = 0.0
    entry_price = 0.0
    equity = [cash]
    trades = 0
    gross_pnl = 0.0
    total_costs = 0.0
    returns = []
    signals: List[str] = []

    for i in range(50, len(closes)):
        price = closes[i]
        high = highs[i]
        low = lows[i]

        md = {
            "symbol": symbol, "price": price, "high": high, "low": low,
            "sma": float(np.mean(closes[max(0, i - 20):i])),
            "ema": float(np.mean(closes[max(0, i - 10):i])),
            "rsi": 50.0, "atr": high - low, "momentum": 0.0,
            "volume": 1000.0, "adx": 20.0,
            "historical_support": float(np.min(closes[max(0, i - 50):i])),
            "historical_resistance": float(np.max(closes[max(0, i - 50):i])),
        }

        state = MarketState.from_market_data(symbol, md)
        state.cash = cash
        state.position = position
        state.avg_entry = entry_price if position != 0 else 0.0
        state.portfolio_value = cash + position * price
        state.peak_value = max(100000.0, max(equity))
        vec = state.to_vector()
        score = evaluator.evaluate(vec)

        action = "HOLD"
        if score > 1.5 and cash > price * 0.01:
            action = "BUY_LIMIT"
        elif score < -1.0 and position > 0:
            action = "SELL_LIMIT"

        fill_price = price
        cost = 0.0

        if action == "BUY_LIMIT":
            fill_price = price * (1.0 + SLIPPAGE_BPS / 10000.0)
            qty = cash * 0.25 / fill_price
            cost = qty * fill_price * COMMISSION_PCT
            total_costs += cost
            cash -= (qty * fill_price + cost)
            position += qty
            entry_price = (entry_price * (position - qty) + fill_price * qty) / position if position > qty else fill_price
            trades += 1
            signals.append("BUY")

        elif action == "SELL_LIMIT" and position > 0:
            fill_price = price * (1.0 - SLIPPAGE_BPS / 10000.0)
            cost = position * fill_price * COMMISSION_PCT
            total_costs += cost
            proceeds = position * fill_price - cost
            gross_pnl += proceeds - (position * entry_price)
            cash += proceeds
            position = 0.0
            entry_price = 0.0
            trades += 1
            signals.append("SELL")

        new_equity = cash + position * price
        if new_equity > 0 and equity[-1] > 0:
            returns.append((new_equity - equity[-1]) / equity[-1])
        equity.append(new_equity)

    final_equity = cash + position * price
    if position > 0:
        gross_pnl += (price - entry_price) * position

    sharpe = compute_sharpe(returns)
    mdd = compute_max_drawdown(equity)
    net_pnl = final_equity - 100000.0

    return {
        "symbol": symbol,
        "bars": len(closes),
        "trades": trades,
        "final_equity": round(final_equity, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "total_costs": round(total_costs, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "return_pct": round((final_equity - 100000.0) / 100000.0 * 100, 2),
        "signals": signals[:10],
    }


def main():
    logger.info("=" * 70)
    logger.info("OUT-OF-SAMPLE VALIDATION — StateEvaluator weight sensitivity")
    logger.info("=" * 70)

    evaluator = StateEvaluator()
    results = []

    for symbol in SYMBOLS_TO_TEST:
        logger.info("\n--- %s ---", symbol)

        train_bars = load_bars(symbol, TRAIN_DAYS)
        test_bars = load_bars(symbol, TEST_DAYS)

        if len(train_bars) < 50:
            logger.warning("  Not enough training bars, skipping")
            continue

        train_result = run_backtest(symbol, train_bars, evaluator)
        test_result = run_backtest(symbol, test_bars, evaluator)

        degradation = test_result["sharpe"] - train_result["sharpe"]

        logger.info("  In-sample  (%dd): Sharpe=%.4f  Return=%.2f%%  MDD=%.2f%%  Trades=%d  Costs=$%.2f",
                     TRAIN_DAYS, train_result["sharpe"], train_result["return_pct"],
                     train_result["max_drawdown"] * 100, train_result["trades"], train_result["total_costs"])
        logger.info("  Out-of-sample (%dd): Sharpe=%.4f  Return=%.2f%%  MDD=%.2f%%  Trades=%d  Costs=$%.2f",
                     TEST_DAYS, test_result["sharpe"], test_result["return_pct"],
                     test_result["max_drawdown"] * 100, test_result["trades"], test_result["total_costs"])
        logger.info("  Degradation: Sharpe %.4f -> %.4f (delta=%.4f)",
                     train_result["sharpe"], test_result["sharpe"], degradation)

        results.append({
            "symbol": symbol,
            "train": train_result,
            "test": test_result,
            "sharpe_degradation": round(degradation, 4),
        })

    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    total_degradation = 0.0
    for r in results:
        deg = r["sharpe_degradation"]
        total_degradation += deg
        logger.info("  %12s  Sharpe: train=%.4f  test=%.4f  delta=%+.4f  (costs: train=$%.0f test=$%.0f)",
                     r["symbol"], r["train"]["sharpe"], r["test"]["sharpe"], deg,
                     r["train"]["total_costs"], r["test"]["total_costs"])
    if results:
        logger.info("\n  Mean Sharpe degradation: %.4f", total_degradation / len(results))

    report = {
        "timestamp": time.time(),
        "config": {"train_days": TRAIN_DAYS, "test_days": TEST_DAYS, "slippage_bps": SLIPPAGE_BPS, "commission_pct": COMMISSION_PCT},
        "results": results,
        "mean_sharpe_degradation": round(total_degradation / len(results), 4) if results else 0.0,
    }

    import os
    os.makedirs("logs", exist_ok=True)
    with open("logs/oos_validation.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info("\nReport saved to logs/oos_validation.json")

    if any(r["sharpe_degradation"] < -0.5 for r in results):
        logger.warning("\n*** WARNING: Severe Sharpe degradation detected — evaluator weights likely overfit ***")
    else:
        logger.info("\nNo severe degradation detected.")


if __name__ == "__main__":
    main()
