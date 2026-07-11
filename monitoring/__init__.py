from monitoring.telegram import (
    send_message as tg_send,
    notify_trade as tg_trade,
    notify_daily_summary as tg_daily,
    notify_kill_switch as tg_kill,
    notify_bot_start as tg_start,
    notify_error as tg_error,
)

try:
    from monitoring.whatsapp import (
        notify_trade as wa_trade,
        notify_daily_summary as wa_daily,
        notify_kill_switch as wa_kill,
        notify_bot_start as wa_start,
        notify_error as wa_error,
    )
except ImportError:
    wa_trade = wa_daily = wa_kill = wa_start = wa_error = None


def notify_trade(symbol, action, price, allocation, stop_loss):
    tg_trade(symbol, action, price, allocation, stop_loss)
    if wa_trade:
        wa_trade(symbol, action, price, allocation, stop_loss)

def notify_daily_summary(pnl, trades, equity, positions):
    tg_daily(pnl, trades, equity, positions)
    if wa_daily:
        wa_daily(pnl, trades, equity, positions)

def notify_kill_switch(reason, pnl):
    tg_kill(reason, pnl)
    if wa_kill:
        wa_kill(reason, pnl)

def notify_bot_start(mode, symbols):
    tg_start(mode, symbols)
    if wa_start:
        wa_start(mode, symbols)

def notify_error(error, context=""):
    tg_error(error, context)
    if wa_error:
        wa_error(error, context)
