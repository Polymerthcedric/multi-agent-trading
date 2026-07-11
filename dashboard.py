from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Dict, List, Optional

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from config.settings import Settings
from agents.predictive import PredictiveAgent
from agents.context import ContextAgent
from agents.volatility import VolatilityAgent
from agents.risk_manager import RiskManager, RiskLimits
from connectors.tv_datafeed import TradingViewFeed, TVSnapshot
from connectors.platform import PaperTradingConnector, Balance
from connectors.historical import HistoricalDataFeed
from execution.broker import Broker
from execution.engine import SearchEngine
from engine.state import MarketState
from engine.evaluator import StateEvaluator
from engine.watchdog import DataQualityWatchdog

_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def _run_async(coro):
    loop = _get_loop()
    return loop.run_until_complete(coro)

st.set_page_config(page_title="Multi-Agent Trading Dashboard", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stApp { background: #0f172a; }
    .metric-card { background: #1e293b; border-radius: 12px; padding: 16px; border: 1px solid #334155; transition: border-color 0.2s; }
    .metric-card:hover { border-color: #475569; }
    .agent-card { background: #1e293b; border-radius: 8px; padding: 12px; border-left: 4px solid #3b82f6; margin: 8px 0; transition: border-color 0.2s; }
    .agent-card:hover { border-left-width: 6px; }
    .agent-card.predictive { border-left-color: #8b5cf6; }
    .agent-card.context { border-left-color: #06b6d4; }
    .agent-card.volatility { border-left-color: #f59e0b; }
    .agent-card.risk { border-left-color: #ef4444; }
    .agent-card.search { border-left-color: #10b981; }
    .buy-badge { color: #22c55e; font-weight: bold; }
    .sell-badge { color: #ef4444; font-weight: bold; }
    .hold-badge { color: #6b7280; font-weight: bold; }
    .block-container { padding-top: 1rem; }
    .stSidebar { background: #0f172a; }
    .stSidebar .stButton button { width: 100%; }
    a { color: #60a5fa; text-decoration: none; }
    a:hover { text-decoration: underline; }
</style>
""", unsafe_allow_html=True)

SYMBOLS = ("GOLD/USD", "SILVER/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AAPL", "MSFT", "GOOGL", "SPY", "QQQ")
SYMBOL_COLORS = {
    "GOLD/USD": "#ffd700", "SILVER/USD": "#c0c0c0",
    "EUR/USD": "#005daa", "GBP/USD": "#1b4580", "USD/JPY": "#e60012",
    "AAPL": "#555555", "MSFT": "#00a4ef", "GOOGL": "#4285f4",
    "SPY": "#ff6600", "QQQ": "#005daa",
}

@st.cache_resource(ttl=120)
def init_feed():
    return TradingViewFeed(symbols=SYMBOLS)

@st.cache_resource(ttl=300)
def init_agents():
    return (
        PredictiveAgent(),
        ContextAgent(),
        {s: VolatilityAgent() for s in SYMBOLS},
        RiskManager(initial_portfolio_value=100000.0),
    )

def init_connector():
    return PaperTradingConnector(initial_balance=100000.0, tv_feed=init_feed())

def init_broker():
    return Broker(init_connector())

def init_searchengine(max_depth=5, n_simulations=80):
    return SearchEngine(max_depth=max_depth, n_simulations=n_simulations, time_limit_ms=3000.0, noise_scale=0.015)

@st.cache_resource(ttl=3600)
def init_historical():
    return HistoricalDataFeed()

@st.cache_resource(ttl=120)
def init_watchdog():
    return DataQualityWatchdog(max_stale_seconds=3600.0, max_consecutive_failures=3)

def fetch_live_data():
    async def _fetch():
        feed = init_feed()
        wd = init_watchdog()
        snapshots, phs, mds = {}, {}, {}
        for sym in SYMBOLS:
            try:
                s = await feed.get_snapshot(sym)
                if s and s.price > 0:
                    snapshots[sym] = s
                    phs[sym] = feed.get_price_history(sym)
                    mds[sym] = feed.to_market_data(sym, s)
                    wd.record_success("TradingView", sym)
                else:
                    wd.record_failure("TradingView", sym, "no_data_or_zero_price")
            except Exception as e:
                wd.record_failure("TradingView", sym, str(e)[:80])
        return snapshots, phs, mds
    return _run_async(_fetch())

def run_agent_pipeline(mds):
    async def _run():
        pred, ctx, vmap, risk = init_agents()
        results = {}
        for sym in SYMBOLS:
            md = mds.get(sym)
            if md:
                pr = await pred.analyze(md)
                cr = await ctx.analyze(md)
                vr = await vmap[sym].analyze(md)
                dec = await risk.evaluate(prediction=asdict(pr), context=asdict(cr), volatility=asdict(vr), market_data=md)
                results[sym] = (pr, cr, vr, dec)
        return results
    return _run_async(_run())

def run_search_engine(mds, max_depth=5, n_simulations=80):
    async def _run():
        se = init_searchengine(max_depth, n_simulations)
        search_results = {}
        for sym in SYMBOLS:
            md = mds.get(sym)
            if md:
                await se.update_state(sym, md)
                action, score, metrics = await se.search_best_action(sym)
                search_results[sym] = {"action": action, "score": score, "metrics": metrics}
        se.save_metrics()
        return search_results
    return _run_async(_run())

def render_market_card(sym: str, snap: TVSnapshot, ph: List[float]):
    color = SYMBOL_COLORS.get(sym, "#3b82f6")
    rec = snap.recommendation
    rc = {"STRONG_BUY": "green", "BUY": "lime", "NEUTRAL": "gray", "SELL": "orange", "STRONG_SELL": "red"}.get(rec, "gray")
    st.markdown(f"""
    <div class="metric-card">
        <h3 style="color:{color}; margin:0 0 4px 0;">{sym}</h3>
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:26px; font-weight:bold;">${snap.price:,.2f}</span>
            <span style="color:{rc}; font-weight:bold;">{rec}</span>
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:2px; margin-top:6px; font-size:12px;">
            <span>RSI: <b>{snap.rsi:.1f}</b></span>
            <span>ATR: <b>{snap.atr:.4f}</b></span>
            <span>SMA20: <b>${snap.sma20:,.2f}</b></span>
            <span>EMA20: <b>${snap.ema20:,.2f}</b></span>
            <span>ADX: <b>{snap.adx:.1f}</b></span>
            <span>MACD: <b>{snap.macd:.4f}</b></span>
        </div>
        <div style="font-size:11px; color:#94a3b8;">TV: ▲{snap.buy_signals} / ▼{snap.sell_signals}</div>
    </div>
    """, unsafe_allow_html=True)
    if len(ph) >= 2:
        fig = go.Figure(go.Scatter(y=ph, mode="lines", line=dict(color=color, width=2),
            fill="tozeroy", fillcolor=f"rgba{tuple(int(color.lstrip('#')[i:i+2],16) for i in (0,2,4)) + (0.1,)}"))
        fig.update_layout(height=100, margin=dict(l=0,r=0,t=0,b=0), showlegend=False,
            xaxis_showticklabels=False, yaxis_showticklabels=False, xaxis_showgrid=False, yaxis_showgrid=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width='stretch', key=f"mc_{sym.replace('/','').replace('.','')}")

def render_agent_panel(results, search_results):
    sym = st.selectbox("Symbol", SYMBOLS, key="agent_sym")
    if sym not in results:
        st.info("No data"); return
    pr, cr, vr, dec = results[sym]
    pd_, cd, vd, dd = asdict(pr), asdict(cr), asdict(vr), asdict(dec)
    sr = search_results.get(sym, {})

    c1, c2, c3, c4, c5 = st.columns(5)
    dc_ = {"Bullish": "green", "Bearish": "red", "Neutral": "gray"}.get(pd_["direction"], "gray")
    with c1:
        st.markdown(f"""<div class="agent-card predictive"><small style="color:#8b5cf6;">PREDICTIVE</small><br>
            <span style="font-size:18px;font-weight:bold;color:{dc_};">{pd_["direction"]}</span><br>
            <span>Conf: <b>{pd_["confidence"]:.2%}</b></span>
            <span style="font-size:11px;color:#94a3b8;">Net: {pd_["reasoning"].get("net_score",0):+.2f}</span></div>""", unsafe_allow_html=True)
    rc_ = {"bullish":"green","bearish":"red","neutral":"gray"}.get(cd["regime"],"gray")
    ac_ = {"bullish":"green","bearish":"red","neutral":"gray"}.get(cd["signal_alignment"],"gray")
    with c2:
        st.markdown(f"""<div class="agent-card context"><small style="color:#06b6d4;">CONTEXT</small><br>
            <span>Regime: <b style="color:{rc_};">{cd["regime"]}</b></span><br>
            <span>Align: <b style="color:{ac_};">{cd["signal_alignment"]}</b></span>
            <span style="font-size:11px;color:#94a3b8;">S/R: ${cd["support_level"]:,.0f}/${cd["resistance_level"]:,.0f}</span></div>""", unsafe_allow_html=True)
    vc_ = {"high_vol_chaos":"red","low_vol_trend":"orange","mean_reverting":"gray"}.get(vd["volatility_regime"],"gray")
    with c3:
        st.markdown(f"""<div class="agent-card volatility"><small style="color:#f59e0b;">VOLATILITY</small><br>
            <span>Regime: <b style="color:{vc_};">{vd["volatility_regime"]}</b></span><br>
            <span>ATR: <b>{vd["atr"]:.4f}</b> | Z: {vd["z_score"]:+.2f}</span>
            <span style="font-size:11px;color:#94a3b8;">Mult: {vd["risk_multiplier"]:.2f}x</span></div>""", unsafe_allow_html=True)
    act = dd["action"]; ac_cls = {"BUY":"buy-badge","SELL":"sell-badge","HOLD":"hold-badge"}.get(act,"hold-badge")
    with c4:
        st.markdown(f"""<div class="agent-card risk"><small style="color:#ef4444;">RISK</small><br>
            <span class="{ac_cls}" style="font-size:18px;">{act}</span><br>
            <span>Alloc: <b>{dd.get("allocation_pct",0)*100:.1f}%</b></span>
            <span style="font-size:11px;color:#94a3b8;">Stop: ${dd.get("stop_loss",0):,.2f}</span></div>""", unsafe_allow_html=True)
    sa = sr.get("action","HOLD"); ss = sr.get("score",0.0)
    sa_cls = {"BUY_LIMIT":"buy-badge","SELL_LIMIT":"sell-badge","HOLD":"hold-badge","RISK_CLOSE":"hold-badge"}.get(sa,"hold-badge")
    dt = sr.get("direction_tracker", {})
    dt_acc = dt.get("accuracy", 0.0)
    dt_roll = dt.get("total_rollouts", 0)
    with c5:
        st.markdown(f"""<div class="agent-card search"><small style="color:#10b981;">SEARCH ENGINE</small><br>
            <span class="{sa_cls}" style="font-size:18px;">{sa}</span><br>
            <span>Score: <b>{ss:.4f}</b></span>
            <span style="font-size:11px;color:#94a3b8;">Sims: {sr.get("metrics",{}).get("simulations_run",0)}</span>
            <span style="font-size:11px;color:#94a3b8;">DirMatch: {dt_acc:.1%} ({dt_roll} rollouts)</span></div>""", unsafe_allow_html=True)

    with st.expander("Raw Reasoning"):
        t1, t2, t3, t4, t5 = st.tabs(["Predictive","Context","Volatility","Risk","Search"])
        with t1: st.json(pd_["reasoning"])
        with t2: st.json(cd["reasoning"])
        with t3: st.json(vd["reasoning"])
        with t4: st.json(dd["reasoning"])
        with t5: st.json(sr.get("metrics",{}))

def render_portfolio(balance, connector, searchengine):
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Total Equity", f"${balance.total_equity:,.2f}")
    with c2: st.metric("Cash", f"${balance.cash:,.2f}")
    with c3:
        exp = sum(balance.positions.values())/(balance.total_equity or 1)*100 if balance.positions else 0
        st.metric("Exposure", f"{exp:.1f}%")
    st.markdown("### Positions")
    if balance.positions:
        for sym, qty in balance.positions.items():
            st.write(f"{sym}: {qty:.6f}")
    else:
        st.info("No open positions")
    st.markdown("### Trade Log")
    history = connector.trade_history
    if history:
        for t in reversed(history[-20:]):
            ts = time.strftime("%H:%M:%S", time.localtime(t.timestamp))
            em = "\U0001f7e2" if t.side=="buy" else "\U0001f534"
            st.write(f"{em} `{ts}` {t.symbol} **{t.side.upper()}** {t.filled_quantity:.6f} @ ${t.avg_fill_price:,.2f}")
    else:
        st.info("No trades yet")

def render_historical():
    hf = init_historical()
    avail = hf.is_available()
    st.markdown(f"**Historical Backtesting** ({'yfinance available' if avail else 'synthetic mode'})")
    col1, col2 = st.columns([1, 1])
    with col1:
        sym = st.selectbox("Symbol", SYMBOLS, key="hist_sym")
    with col2:
        days = st.slider("Days", 7, 365, 90, key="hist_days")
    if st.button("Fetch Historical Data", type="primary"):
        with st.spinner(f"Fetching {days}d for {sym}..."):
            bars = hf.fetch(sym, days=days)
            if bars:
                closes = [b["close"] for b in bars]
                fig = go.Figure(go.Scatter(y=closes, mode="lines", line=dict(color=SYMBOL_COLORS.get(sym,"#3b82f6"), width=1.5)))
                fig.update_layout(height=400, margin=dict(l=0,r=0,t=0,b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False), yaxis=dict(showgrid=False))
                st.plotly_chart(fig, width='stretch')
                st.write(f"Bars: {len(bars)} | Latest: ${bars[-1]['close']:,.2f}")

def render_risk_monitor():
    st.markdown("### Circuit Breakers")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Max Daily Loss", "3%", "Halt trading")
    with c2:
        st.metric("Max Weekly Loss", "5%", "Extended halt")
    with c3:
        st.metric("Kill Switch", "7%", "Full shutdown")
    with c4:
        st.metric("Max Trades/Day", "15", "Limit reached = HOLD")

    st.markdown("### Risk Parameters")
    st.markdown("""
    | Parameter | Value | Description |
    |-----------|-------|-------------|
    | Min Confidence | 0.55 | Below this = HOLD |
    | Max Allocation | 20% | Per asset |
    | Trailing Stop | 2% | Below fill price |
    | Max Risk/Trade | 1.5% | Of portfolio |
    | Kelly Fraction | 0.25-0.50 | Position sizing |
    """)

def main():
    feed = init_feed()
    if not feed.is_available():
        st.error("tradingview_ta not installed. Run: pip install tradingview-ta"); st.stop()

    st.sidebar.title("Multi-Agent Trading")
    st.sidebar.markdown("---")
    auto = st.sidebar.checkbox("Auto-refresh (30s)", value=True)
    go_btn = st.sidebar.button("Refresh Now", type="primary", use_container_width=True)
    st.sidebar.markdown("### Commodities")
    st.sidebar.markdown("- GOLD/USD\n- SILVER/USD")
    st.sidebar.markdown("### Forex")
    st.sidebar.markdown("- EUR/USD\n- GBP/USD\n- USD/JPY")
    st.sidebar.markdown("### Stocks & ETFs")
    st.sidebar.markdown("- AAPL\n- MSFT\n- GOOGL\n- SPY\n- QQQ")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Search Engine Config")
    sd = st.sidebar.slider("Search Depth", 2, 10, 5, key="search_depth")
    ns = st.sidebar.slider("Simulations", 20, 500, 80, step=10, key="n_sims")

    refresh = go_btn or (auto and "last_refresh" in st.session_state and time.time() - st.session_state.last_refresh > 30)
    if refresh or "snapshots" not in st.session_state:
        with st.spinner("Fetching live data + running agents + search..."):
            try:
                snaps, phs, mds = fetch_live_data()
                st.session_state.snapshots = snaps
                st.session_state.price_histories = phs

                st.session_state.results = run_agent_pipeline(mds)
                st.session_state.search_results = run_search_engine(mds, max_depth=sd, n_simulations=ns)
                st.session_state.balance = _run_async(init_connector().get_balance())
                st.session_state.last_refresh = time.time()
            except Exception as e:
                st.error(f"Error: {e}")
                import traceback; st.exception(e)

    if "snapshots" not in st.session_state:
        st.info("Click Refresh to load live data."); return

    bal = st.session_state.balance
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.session_state.last_refresh))
    st.markdown(f"<div style='display:flex;justify-content:space-between;color:#94a3b8;margin-bottom:8px;'>"
        f"<span>Updated: {last}</span><span>TV (1h) | Paper: ${bal.total_equity:,.2f}</span></div>", unsafe_allow_html=True)

    t_market, t_agents, t_portfolio, t_hist, t_risk = st.tabs(["Market", "Agents + Search", "Portfolio", "Backtest", "Risk Monitor"])

    with t_market:
        cols = st.columns(3)
        for i, sym in enumerate(SYMBOLS):
            with cols[i % 3]:
                snap = st.session_state.snapshots.get(sym)
                if snap: render_market_card(sym, snap, st.session_state.price_histories.get(sym, []))
        import pandas as pd
        rows = []
        for sym in SYMBOLS:
            s = st.session_state.snapshots.get(sym)
            if s: rows.append({"Symbol": sym, "Price": s.price, "RSI": s.rsi, "ADX": s.adx, "Rec": s.recommendation})
        if rows:
            df = pd.DataFrame(rows)
            fig = px.bar(df, x="Symbol", y="Price", color="Symbol",
                color_discrete_map=SYMBOL_COLORS, text_auto=".3s", height=300)
            fig.update_layout(showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width='stretch')

    with t_agents:
        render_agent_panel(st.session_state.results, st.session_state.search_results)

    with t_portfolio:
        render_portfolio(st.session_state.balance, init_connector(), init_searchengine())

    with t_hist:
        render_historical()

    with t_risk:
        render_risk_monitor()

    wd = init_watchdog()
    wd_sum = wd.summary()
    if wd_sum["critical"]:
        st.sidebar.warning("Data Quality Alert: {}/{} sources failing".format(
            wd_sum["sources_failing"], wd_sum["sources_monitored"]))
    else:
        st.sidebar.info("Data Quality OK ({}/{} sources)".format(
            wd_sum["sources_monitored"] - wd_sum["sources_failing"], wd_sum["sources_monitored"]))

    st.sidebar.markdown("### Self-Learning")
    st.sidebar.caption("Feedback loop active — params auto-tune every 25 trades")
    st.sidebar.caption("See `engine/self_learner.py`")

    st.sidebar.markdown("---")
    st.sidebar.caption("Multi-Agent Trading Framework v3")
    st.sidebar.markdown("[Fidel Cedric Odoyo](https://github.com/Polymerthcedric)")

if __name__ == "__main__":
    main()
