"""Offline walk-forward out-of-sample check (DEMO data is SYNTHETIC).

DEMO BAR DATA IS GENERATED LOCALLY AND IS SYNTHETIC.  IT IS NOT MARKET DATA
AND NOT EVIDENCE OF REAL-MARKET PERFORMANCE.  Use ``--bars series.csv`` (or
``.json``) to validate against a real, locally supplied chronological series.

This script deliberately does NOT call ``HistoricalDataFeed``: in DEMO mode
that feed may fall back to yfinance/xfinance, and calling it twice with
different ``days`` produces two unrelated synthetic series, which makes an
in-sample/out-of-sample comparison meaningless.  ``engine.walk_forward``
instead reuses ONE series and slices it into train/test folds.

Programmatic API::

    from engine.walk_forward import WalkForwardConfig, WalkForwardValidator
    report = WalkForwardValidator(WalkForwardConfig(...)).validate(
        bars, symbol="GOLD/USD", data_source="LOCAL_FILE"
    )
    print(report.as_dict())

Run from the repo root, e.g.::

    python tests/validate_oos.py --demo-bars 240 --no-write
    python tests/validate_oos.py --bars data/bars.csv --output logs/oos.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("validate_oos")

SYMBOLS_TO_TEST = ["GOLD/USD", "SILVER/USD", "EUR/USD", "AAPL"]
DEFAULT_OUTPUT = "logs/oos_validation.json"
DISCLAIMER = (
    "DEMO data in this report is SYNTHETIC, generated locally and deterministic. "
    "It is NOT market data and NOT evidence of real-market performance. "
    "Only results from --bars with a genuine chronological series are meaningful."
)
LOCAL_FILE_DISCLAIMER = (
    "This report uses the local file {path}. Results depend on that file's bars, "
    "costs, and assumptions. They are NOT evidence of real-market performance."
)


def disclaimer_for(bars_path: Optional[str]) -> str:
    """Return the disclaimer that matches the data source."""
    if bars_path is None:
        return DISCLAIMER
    return LOCAL_FILE_DISCLAIMER.format(path=str(bars_path))

DEMO_BASE_PRICES = {
    "GOLD/USD": 2350.0, "SILVER/USD": 28.5, "EUR/USD": 1.14,
    "GBP/USD": 1.33, "USD/JPY": 161.0, "AAPL": 195.0,
    "MSFT": 420.0, "GOOGL": 175.0, "SPY": 520.0, "QQQ": 450.0,
}

_NUMERIC_FIELDS = ("open", "high", "low", "close", "volume")


def generate_demo_bars(symbol: str, n_bars: int) -> List[Dict[str, Any]]:
    """Deterministic synthetic OHLCV bars. No RNG, no network, no wall clock."""
    if n_bars < 1:
        return []
    base = DEMO_BASE_PRICES.get(symbol, 100.0)
    phase = (sum(ord(c) for c in symbol) % 97) / 97.0
    price = base
    bars: List[Dict[str, Any]] = []
    for i in range(n_bars):
        open_price = price
        ret = 0.0002 + 0.004 * math.sin(i * 0.23 + phase) + 0.002 * math.sin(i * 0.061 + 1.7)
        price = max(price * (1.0 + ret), 1e-6)
        high = max(open_price, price) * (1.001 + abs(ret) * 0.25)
        low = min(open_price, price) * (1.0 - 0.001 - min(abs(ret) * 0.25, 0.5))
        bars.append({
            "timestamp": float(1_700_000_000 + i * 3600),
            "open": round(open_price, 6),
            "high": round(high, 6),
            "low": round(max(low, 1e-6), 6),
            "close": round(price, 6),
            "volume": float(1000 + (i * 37) % 5000),
        })
    return bars


def _coerce_bar(raw: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(raw)
    if "timestamp" not in out or out["timestamp"] is None:
        out["timestamp"] = 1_700_000_000.0
    else:
        try:
            out["timestamp"] = float(out["timestamp"])
        except (TypeError, ValueError):
            from datetime import datetime

            out["timestamp"] = datetime.fromisoformat(str(out["timestamp"]).replace("Z", "+00:00")).timestamp()
    for field in _NUMERIC_FIELDS:
        if field in out and out[field] is not None:
            out[field] = float(out[field])
    return out


def load_bars(path: str) -> List[Dict[str, Any]]:
    """Load a local CSV (header row) or JSON list/dict-of-bars series."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("bars", data.get("data"))
        if not isinstance(data, list):
            raise ValueError("JSON bar file must contain a list of bar objects")
        raw_bars = data
    else:
        reader = csv.DictReader(text.splitlines())
        raw_bars = [{k.lower(): v for k, v in row.items() if k is not None} for row in reader]

    if not raw_bars:
        raise ValueError(f"no bars found in {path}")
    return [_coerce_bar(row) for row in raw_bars]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS_TO_TEST)
    parser.add_argument(
        "--strategy",
        choices=("multi_agent", "state_evaluator"),
        default="multi_agent",
        help="fixed paper-agent policy (default) or the legacy StateEvaluator research model",
    )
    parser.add_argument("--bars", metavar="PATH", help="local CSV/JSON bar series (no network calls)")
    parser.add_argument("--demo-bars", type=int, default=240, help="synthetic bars per DEMO symbol")
    parser.add_argument("--train-window", type=int, default=60)
    parser.add_argument("--test-window", type=int, default=20)
    parser.add_argument("--step", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--commission-pct", type=float, default=0.001)
    parser.add_argument(
        "--annual-factor", type=float, default=252.0 * 6.5,
        help="Sharpe annualization factor (default 1638 for hourly bars; use 252 for daily bars)",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="JSON report path")
    parser.add_argument("--no-write", action="store_true", help="do not write the JSON report")
    return parser.parse_args(argv)


def run_validation(args: argparse.Namespace) -> Dict[str, Any]:
    """Validate each symbol against one series; return a JSON-ready report."""
    from engine.walk_forward import (
        PolicyWalkForwardValidator,
        WalkForwardConfig,
        WalkForwardValidator,
    )

    config = WalkForwardConfig(
        train_window=args.train_window,
        test_window=args.test_window,
        step=args.step,
        warmup=args.warmup,
        slippage_bps=args.slippage_bps,
        commission_pct=args.commission_pct,
        annual_factor=args.annual_factor,
    )
    legacy_validator = WalkForwardValidator(config)
    local_bars = load_bars(args.bars) if args.bars else None
    data_source = f"LOCAL_FILE:{args.bars}" if args.bars else "SYNTHETIC_DEMO"

    per_symbol: Dict[str, Dict[str, Any]] = {}
    for symbol in args.symbols:
        bars = local_bars if local_bars is not None else generate_demo_bars(symbol, args.demo_bars)
        if args.strategy == "multi_agent":
            from agents.research_policy import MultiAgentResearchPolicy

            validator = PolicyWalkForwardValidator(
                lambda symbol=symbol: MultiAgentResearchPolicy(symbol),
                config,
                strategy=MultiAgentResearchPolicy.name,
            )
        else:
            validator = legacy_validator
        report = validator.validate(bars, symbol=symbol, data_source=data_source)
        per_symbol[symbol] = report.as_dict()

        if not report.folds:
            logger.warning("%s: %s", symbol, report.reason)
            continue
        if args.strategy == "multi_agent":
            for fold in report.folds:
                logger.info(
                    "%s fold %d [%d:%d] -> [%d:%d] | in-sample Sharpe=%.3f "
                    "OOS Sharpe=%.3f OOS net=$%.2f trades=%d",
                    symbol, fold.window.fold,
                    fold.window.train_start, fold.window.train_end,
                    fold.window.test_start, fold.window.test_end,
                    fold.in_sample.sharpe, fold.out_of_sample.sharpe,
                    fold.out_of_sample.net_pnl, fold.out_of_sample.trade_count,
                )
            payload = report.as_dict()
            logger.info("%s aggregate: %s", symbol, payload["aggregate"])
            logger.info("%s OOS baselines: %s", symbol, payload["benchmarks"])
        else:
            for fold in report.folds:
                logger.info(
                    "%s fold %d [%d:%d] -> [%d:%d] params=%s | train Sharpe=%.3f test Sharpe=%.3f "
                    "test net=$%.2f trades=%d",
                    symbol, fold.window.fold,
                    fold.window.train_start, fold.window.train_end,
                    fold.window.test_start, fold.window.test_end,
                    fold.chosen_params.as_dict(),
                    fold.train.sharpe, fold.test.sharpe,
                    fold.test.net_pnl, fold.test.trade_count,
                )
            logger.info("%s aggregate: %s", symbol, report.aggregate.as_dict())

    degradations = [
        r["aggregate"]["mean_sharpe_degradation"] for r in per_symbol.values() if r["folds"]
    ]
    return {
        "timestamp": time.time(),
        "disclaimer": disclaimer_for(args.bars),
        "strategy": args.strategy,
        "data_source": data_source,
        "config": config.as_dict(),
        "symbols": per_symbol,
        "mean_sharpe_degradation_across_symbols": (
            sum(degradations) / len(degradations) if degradations else 0.0
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.getLogger("agents").setLevel(logging.WARNING)
    logger.info("=" * 70)
    logger.info("WALK-FORWARD OUT-OF-SAMPLE VALIDATION")
    logger.info("%s", disclaimer_for(args.bars))
    logger.info("=" * 70)

    report = run_validation(args)
    if not args.no_write:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Report saved to %s", output)

    warnings = [
        (symbol, r["aggregate"]["mean_sharpe_degradation"])
        for symbol, r in report["symbols"].items()
        if r["folds"] and r["aggregate"]["mean_sharpe_degradation"] < -0.5
    ]
    scored = [symbol for symbol, result in report["symbols"].items() if result["folds"]]
    if not scored:
        logger.warning("No folds were scored; Sharpe degradation was not evaluated.")
    elif warnings:
        logger.warning("Severe Sharpe degradation: %s", warnings)
    else:
        logger.info("No severe aggregate Sharpe degradation detected for scored symbols.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
