"""
WhatsApp Alerts — Kenya Simple Edition
Uses CallMeBot API (free, no signup, no credit card)

Setup:
1. Save +254 798 348 449 (CallMeBot) in your phone contacts
2. Send "I allow callmebot to send me notifications" to that number
3. You'll get an API key in reply — put it in .env as WHATSAPP_API_KEY
4. Set WHATSAPP_PHONE to your number: 254XXXXXXXXX
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

API_KEY = os.getenv("WHATSAPP_API_KEY", "")
PHONE = os.getenv("WHATSAPP_PHONE", "")
ENABLED = bool(API_KEY and PHONE)

if ENABLED:
    logger.info("WhatsApp alerts ENABLED (phone=%s)", PHONE)
else:
    logger.info("WhatsApp alerts disabled (set WHATSAPP_API_KEY + WHATSAPP_PHONE)")


def _send(text: str) -> bool:
    if not ENABLED:
        return False
    try:
        url = "https://api.callmebot.com/whatsapp.php"
        resp = requests.get(url, params={
            "phone": PHONE,
            "text": text,
            "apikey": API_KEY,
        }, timeout=15)
        if resp.status_code == 200 and "message" in resp.text.lower():
            return True
        logger.warning("WhatsApp send failed: %s", resp.text[:200])
        return False
    except Exception as e:
        logger.error("WhatsApp error: %s", e)
        return False


def notify_trade(symbol: str, action: str, price: float, allocation: float, stop_loss: float) -> bool:
    emoji = "\U0001f7e2" if action == "BUY" else "\U0001f534"
    text = (
        f"{emoji} *TRADE*\n"
        f"*{symbol}*\n"
        f"Action: {action}\n"
        f"Price: ${price:,.4f}\n"
        f"Size: {allocation:.1%} of portfolio\n"
        f"Stop: ${stop_loss:,.4f}\n"
        f"Time: {time.strftime('%H:%M:%S')}"
    )
    return _send(text)


def notify_daily_summary(pnl: float, trades: int, equity: float, positions: dict) -> bool:
    pos_lines = "\n".join(f"  {s}: {q:.4f}" for s, q in positions.items()) if positions else "  None"
    emoji = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
    text = (
        f"{emoji} *DAILY SUMMARY*\n"
        f"P&L: ${pnl:+,.2f}\n"
        f"Trades: {trades}\n"
        f"Equity: ${equity:,.2f}\n"
        f"Positions:\n{pos_lines}"
    )
    return _send(text)


def notify_kill_switch(reason: str, pnl: float) -> bool:
    text = (
        f"\U0001f6a8 *KILL SWITCH*\n"
        f"Reason: {reason}\n"
        f"P&L: ${pnl:+,.2f}\n"
        f"All trading halted!"
    )
    return _send(text)


def notify_bot_start(mode: str, symbols: tuple) -> bool:
    text = (
        f"\u2601\ufe0f *BOT STARTED*\n"
        f"Mode: {mode}\n"
        f"Tracking: {', '.join(symbols)}"
    )
    return _send(text)


def notify_error(error: str, context: str = "") -> bool:
    text = (
        f"\u26a0\ufe0f *ERROR*\n"
        f"Context: {context}\n"
        f"Error: {error[:300]}"
    )
    return _send(text)
