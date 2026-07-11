#!/usr/bin/env python3
"""Telegram alert integration for trade notifications."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLED = bool(BOT_TOKEN and CHAT_ID)

if ENABLED:
    logger.info("Telegram alerts ENABLED (chat_id=%s)", CHAT_ID)
else:
    logger.info("Telegram alerts disabled (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    if not ENABLED:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning("Telegram send failed: %s", resp.text[:200])
        return False
    except Exception as e:
        logger.error("Telegram error: %s", e)
        return False


def notify_trade(symbol: str, action: str, price: float, allocation: float, stop_loss: float) -> bool:
    emoji = "\U0001f7e2" if action == "BUY" else "\U0001f534"
    text = (
        f"{emoji} <b>TRADE EXECUTED</b>\n\n"
        f"<b>Symbol:</b> {symbol}\n"
        f"<b>Action:</b> {action}\n"
        f"<b>Price:</b> ${price:,.4f}\n"
        f"<b>Allocation:</b> {allocation:.1%}\n"
        f"<b>Stop Loss:</b> ${stop_loss:,.4f}\n"
        f"<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_message(text)


def notify_daily_summary(pnl: float, trades: int, equity: float, positions: dict) -> bool:
    pos_lines = "\n".join(f"  {s}: {q:.4f}" for s, q in positions.items()) if positions else "  No positions"
    emoji = "\U0001f4c8" if pnl >= 0 else "\U0001f4c9"
    text = (
        f"{emoji} <b>DAILY SUMMARY</b>\n\n"
        f"<b>P&amp;L:</b> ${pnl:+,.2f}\n"
        f"<b>Trades:</b> {trades}\n"
        f"<b>Equity:</b> ${equity:,.2f}\n"
        f"<b>Positions:</b>\n{pos_lines}\n"
        f"<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_message(text)


def notify_kill_switch(reason: str, pnl: float) -> bool:
    text = (
        f"\U0001f6a8 <b>KILL SWITCH ACTIVATED</b>\n\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>P&amp;L:</b> ${pnl:+,.2f}\n"
        f"<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"All trading has been halted."
    )
    return send_message(text)


def notify_bot_start(mode: str, symbols: tuple) -> bool:
    text = (
        f"\u2601\ufe0f <b>BOT STARTED</b>\n\n"
        f"<b>Mode:</b> {mode}\n"
        f"<b>Symbols:</b> {', '.join(symbols)}\n"
        f"<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_message(text)


def notify_error(error: str, context: str = "") -> bool:
    text = (
        f"\u26a0\ufe0f <b>ERROR</b>\n\n"
        f"<b>Context:</b> {context}\n"
        f"<b>Error:</b> {error[:500]}\n"
        f"<b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_message(text)
