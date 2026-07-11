from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "your-secret-token-here")
HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")
PORT = int(os.getenv("WEBHOOK_PORT", "8000"))


class WebhookPayload(BaseModel):
    passphrase: str = ""
    action: str = ""
    symbol: str = ""
    price: float = 0.0
    volume: float = 0.0
    strategy_id: str = ""
    timeframe: str = ""
    confidence: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""


@dataclass
class SignalRecord:
    timestamp: float
    symbol: str
    action: str
    price: float
    volume: float
    strategy_id: str
    timeframe: str
    confidence: float
    stop_loss: float
    take_profit: float
    reason: str
    status: str = "received"
    error: str = ""


class SignalStore:
    def __init__(self, max_size: int = 1000) -> None:
        self.signals: List[SignalRecord] = []
        self.max_size = max_size
        self._seen_hashes: set = set()

    def add(self, signal: SignalRecord) -> bool:
        sig_hash = hashlib.sha256(
            f"{signal.symbol}:{signal.action}:{signal.price}:{signal.timeframe}:{signal.timestamp:.0f}".encode()
        ).hexdigest()

        if sig_hash in self._seen_hashes:
            logger.warning("Duplicate signal rejected: %s", sig_hash[:12])
            return False

        self._seen_hashes.add(sig_hash)
        self.signals.append(signal)

        if len(self.signals) > self.max_size:
            removed = self.signals[:self.max_size // 2]
            self.signals = self.signals[self.max_size // 2:]
            for s in removed:
                self._seen_hashes.discard(
                    hashlib.sha256(
                        f"{s.symbol}:{s.action}:{s.price}:{s.timeframe}:{s.timestamp:.0f}".encode()
                    ).hexdigest()
                )

        return True

    def get_recent(self, n: int = 50) -> List[SignalRecord]:
        return self.signals[-n:]

    def get_by_symbol(self, symbol: str, n: int = 20) -> List[SignalRecord]:
        return [s for s in self.signals if s.symbol == symbol][-n:]


signal_store = SignalStore()
app = FastAPI(title="TradingView Webhook Bridge", version="1.0.0")

trading_callbacks: List = []


def register_trading_callback(callback):
    trading_callbacks.append(callback)


@app.post("/webhook")
async def webhook(payload: WebhookPayload, request: Request):
    if payload.passphrase != WEBHOOK_SECRET:
        logger.warning("Invalid passphrase from %s", request.client.host)
        raise HTTPException(status_code=403, detail="Invalid passphrase")

    if not payload.action or not payload.symbol:
        raise HTTPException(status_code=400, detail="action and symbol are required")

    valid_actions = {"buy", "sell", "close", "BUY", "SELL", "CLOSE"}
    if payload.action.upper() not in {"BUY", "SELL", "CLOSE"}:
        raise HTTPException(status_code=400, detail=f"Invalid action: {payload.action}")

    signal = SignalRecord(
        timestamp=time.time(),
        symbol=payload.symbol.upper(),
        action=payload.action.upper(),
        price=payload.price,
        volume=payload.volume,
        strategy_id=payload.strategy_id,
        timeframe=payload.timeframe,
        confidence=payload.confidence,
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        reason=payload.reason,
        status="accepted",
    )

    if not signal_store.add(signal):
        return JSONResponse(
            status_code=200,
            content={"status": "duplicate", "message": "Signal already processed"},
        )

    logger.info(
        "WEBHOOK | %s %s @ %.2f vol=%.4f strategy=%s tf=%s",
        signal.action, signal.symbol, signal.price, signal.volume,
        signal.strategy_id, signal.timeframe,
    )

    for cb in trading_callbacks:
        try:
            await cb(signal)
        except Exception as e:
            logger.error("Trading callback error: %s", e)
            signal.status = "error"
            signal.error = str(e)

    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "signal_id": len(signal_store.signals) - 1,
            "symbol": signal.symbol,
            "action": signal.action,
        },
    )


@app.get("/signals")
async def get_signals(symbol: Optional[str] = None, limit: int = 50):
    if symbol:
        signals = signal_store.get_by_symbol(symbol, limit)
    else:
        signals = signal_store.get_recent(limit)
    return [
        {
            "timestamp": s.timestamp,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.timestamp)),
            "symbol": s.symbol,
            "action": s.action,
            "price": s.price,
            "volume": s.volume,
            "strategy": s.strategy_id,
            "timeframe": s.timeframe,
            "confidence": s.confidence,
            "stop_loss": s.stop_loss,
            "take_profit": s.take_profit,
            "reason": s.reason,
            "status": s.status,
        }
        for s in signals
    ]


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "uptime": time.time(),
        "signals_received": len(signal_store.signals),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>TradingView Webhook Monitor</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body { background: #0f172a; color: #e2e8f0; font-family: monospace; padding: 20px; }
        h1 { color: #3b82f6; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #334155; padding: 8px 12px; text-align: left; }
        th { background: #1e293b; color: #94a3b8; }
        tr:nth-child(even) { background: #1e293b; }
        .buy { color: #22c55e; font-weight: bold; }
        .sell { color: #ef4444; font-weight: bold; }
        .close { color: #f59e0b; font-weight: bold; }
    </style>
</head>
<body>
    <h1>TradingView Webhook Monitor</h1>
    <p>Auto-refreshes every 10 seconds</p>
    <div id="signals">Loading...</div>
    <script>
        fetch('/signals?limit=30').then(r=>r.json()).then(data=>{
            let html = '<table><tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Vol</th><th>Strategy</th><th>TF</th><th>Reason</th></tr>';
            data.reverse().forEach(s => {
                let cls = s.action.toLowerCase();
                html += `<tr><td>${s.time}</td><td>${s.symbol}</td><td class="${cls}">${s.action}</td><td>${s.price.toFixed(2)}</td><td>${s.volume.toFixed(4)}</td><td>${s.strategy}</td><td>${s.timeframe}</td><td>${s.reason}</td></tr>`;
            });
            html += '</table>';
            document.getElementById('signals').innerHTML = html;
        });
    </script>
</body>
</html>
"""
