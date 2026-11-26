from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
from typing import Dict, List, Optional, Sequence

from config.settings import Settings
from agents.decision_log import DecisionLogger, DecisionRecord
from agents.research_policy import MultiAgentResearchPolicy
from connectors.platform import PaperTradingConnector
from execution.broker import Broker, ACTION_LABEL_TO_INT
from engine.environment import TradingEnvironment
from engine.ledger import RuntimeLedger, LedgerEntry
from engine.policy import PolicyDecision, PolicyRiskConfig, PortfolioSnapshot
from memory.feedback_loop import TradeLedger, TradeRecord

try:
    from monitoring import notify_trade, notify_kill_switch, notify_bot_start, notify_error
except ImportError:
    notify_trade = notify_kill_switch = notify_bot_start = notify_error = None

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 10
ERROR_BACKOFF_BASE = 5.0
STARTING_PORTFOLIO_VALUE = 100000.0

try:
    from agents.portfolio_risk import PortfolioRiskMonitor
    _PORTFOLIO_RISK_IMPORT_ERROR: Optional[Exception] = None
except ImportError as exc:  # optional dependency/module unavailable
    PortfolioRiskMonitor = None  # type: ignore[assignment]
    _PORTFOLIO_RISK_IMPORT_ERROR = exc


def _safe_number(value: object) -> Optional[float]:
    """Finite float (any sign) or ``None``."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_close(value: object) -> Optional[float]:
    """Finite, strictly positive price or ``None``."""
    number = _safe_number(value)
    return number if number is not None and number > 0 else None


class TradingOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self.decision_log = DecisionLogger()

        risk_config = PolicyRiskConfig(
            max_asset_allocation=settings.max_position_size_pct,
            max_risk_per_trade=settings.max_risk_per_trade_pct,
            daily_loss_limit=settings.max_daily_loss_pct,
            weekly_loss_limit=settings.max_weekly_loss_pct,
            kill_switch_drawdown=settings.max_drawdown_halt_pct,
            max_trades_per_day=settings.max_trades_per_day,
        )
        self.policies: Dict[str, MultiAgentResearchPolicy] = {
            sym: MultiAgentResearchPolicy(sym, risk_config) for sym in settings.symbols
        }

        initial_balance = STARTING_PORTFOLIO_VALUE
        now = time.gmtime()
        self._risk_day_key = time.strftime("%Y-%m-%d", now)
        self._risk_week_key = time.strftime("%Y-%W", now)
        self._equity_peak = initial_balance
        self._day_start_equity = initial_balance
        self._week_start_equity = initial_balance
        self._daily_trade_count = 0
        self._active_stops: Dict[str, float] = {}
        self.portfolio_risk = None
        if PortfolioRiskMonitor is None:
            logger.warning(
                "PortfolioRisk | monitor unavailable (%s); cross-asset gate disabled",
                _PORTFOLIO_RISK_IMPORT_ERROR,
            )
        else:
            try:
                self.portfolio_risk = PortfolioRiskMonitor(portfolio_value=initial_balance)
            except Exception as e:
                logger.error("PortfolioRisk | initialization failed: %s", e)

        # Tracks the last close already fed per symbol and the symbols whose
        # notional we have published to the monitor (so closed positions clear).
        self._last_recorded_close: Dict[str, float] = {}
        self._risk_position_symbols: set = set()

        from connectors.tv_datafeed import TradingViewFeed
        self._tv_feed = TradingViewFeed(symbols=settings.symbols, mode="PAPER")
        self.connector = PaperTradingConnector(initial_balance=initial_balance, tv_feed=self._tv_feed)
        self.broker = Broker(self.connector)
        self.environments: Dict[str, TradingEnvironment] = {
            sym: TradingEnvironment(initial_balance=initial_balance) for sym in settings.symbols
        }
        self.runtime_ledger = RuntimeLedger()
        self.trade_ledger = TradeLedger()

        self._running = False
        self._trade_count = 0
        self._consecutive_errors = 0
        self._last_processed_timestamp: Dict[str, float] = {}

    async def run(self) -> None:
        self._running = True
        logger.info("Symbols=%s | PaperTrading | yfinance primary", self.settings.symbols)

        if notify_bot_start:
            try:
                notify_bot_start("PAPER", self.settings.symbols)
            except Exception:
                pass

        while self._running:
            for symbol in self.settings.symbols:
                try:
                    market_data = await self.connector.get_market_data(symbol)
                except Exception as e:
                    logger.error("Market data error for %s: %s", symbol, e)
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.critical("Too many consecutive errors — stopping")
                        if notify_kill_switch:
                            try:
                                notify_kill_switch("Max consecutive errors", 0.0)
                            except Exception:
                                pass
                        self._running = False
                        break
                    await asyncio.sleep(ERROR_BACKOFF_BASE * (2 ** min(self._consecutive_errors, 5)))
                    continue

                self._consecutive_errors = 0
                timestamp = _safe_number(market_data.get("timestamp"))
                if timestamp is None or timestamp <= 0:
                    logger.error("Market data for %s has no valid timestamp; skipping", symbol)
                    continue
                if timestamp <= self._last_processed_timestamp.get(symbol, 0.0):
                    continue
                self._last_processed_timestamp[symbol] = timestamp

                try:
                    self._feed_market_returns(symbol, market_data)
                    balance = await self.connector.get_balance()
                    risk_sync_ok = await self._sync_portfolio_risk(
                        balance, {symbol: market_data.get("price", 0.0)},
                    )
                    self._update_risk_state(balance.total_equity)
                    portfolio = self._portfolio_snapshot(
                        symbol,
                        market_data,
                        balance,
                        allow_new_positions=(
                            risk_sync_ok and self._portfolio_risk_allows_new_long(symbol)
                        ),
                    )
                    decision = self.policies[symbol].decide(market_data, portfolio)
                    if (
                        portfolio.position_quantity > 0
                        and decision.action != "SELL"
                        and decision.stop_loss > portfolio.active_stop_loss
                    ):
                        self._active_stops[symbol] = decision.stop_loss
                    outputs = decision.agent_outputs
                    pred_dict = outputs.get("prediction", {})
                    ctx_dict = outputs.get("context", {})
                    vol_dict = outputs.get("volatility", {})
                    debate_dict = outputs.get("debate", {})

                    reasoning_chain = [
                        f"Predictive: {pred_dict.get('direction', 'unknown')} "
                        f"(heuristic confidence={decision.confidence:.3f})",
                        f"Context: {ctx_dict.get('signal_alignment', 'neutral')} "
                        f"regime={ctx_dict.get('regime', '?')}",
                        f"Volatility: {vol_dict.get('volatility_regime', '?')} "
                        f"mult={vol_dict.get('risk_multiplier', 1.0):.2f}",
                        f"Debate: explanatory only; winner={debate_dict.get('winner', 'unknown')}",
                        f"Risk: {decision.action} allocation={decision.allocation_pct:.4f} "
                        f"reasons={','.join(decision.reasons)}",
                    ]

                    record = DecisionRecord(
                        timestamp=time.time(),
                        symbol=symbol,
                        action=decision.action,
                        confidence=decision.confidence,
                        adjusted_confidence=decision.confidence,
                        allocation_pct=decision.allocation_pct,
                        stop_loss=decision.stop_loss,
                        price=market_data.get("price", 0),
                        agent_outputs={
                            "prediction": pred_dict,
                            "context": ctx_dict,
                            "volatility": vol_dict,
                        },
                        debate_result=debate_dict,
                        sentiment_result={"status": "excluded_from_decisions"},
                        risk_check={
                            "signal": decision.signal,
                            "reasons": list(decision.reasons),
                            "allocation_pct": decision.allocation_pct,
                        },
                        market_snapshot=market_data,
                        reasoning_chain=reasoning_chain,
                    )
                    self.decision_log.log(record)

                except Exception as e:
                    logger.error("Policy evaluation error for %s: %s", symbol, e)
                    continue

                logger.info(
                    "RESULT symbol=%s signal=%s action=%s alloc=%.2f%% stop=%.2f conf=%.3f",
                    symbol, decision.signal,
                    decision.action, decision.allocation_pct * 100,
                    decision.stop_loss, decision.confidence,
                )

                if decision.action != "HOLD":
                    await self._execute_trade(
                        symbol=symbol,
                        decision=decision,
                        market_data=market_data,
                    )
                try:
                    balance = await self.connector.get_balance()
                    self._update_risk_state(balance.total_equity)
                    await self._sync_portfolio_risk(
                        balance, {symbol: market_data.get("price", 0.0)},
                    )
                except Exception as e:
                    logger.warning("Portfolio risk sync skipped for %s: %s", symbol, e)

            await asyncio.sleep(self.settings.simulation_tick_interval_sec)

        self.runtime_ledger.save()
        self.trade_ledger.save()
        self._running = False
        logger.info("Orchestrator | simulation complete — %d trades executed", self._trade_count)

    async def _execute_trade(
        self,
        symbol: str,
        decision: PolicyDecision,
        market_data: Dict,
    ) -> None:
        action_label = decision.action
        price = float(market_data["price"])
        allocation_pct = decision.allocation_pct
        outputs = decision.agent_outputs
        prediction = outputs.get("prediction", {})
        context = outputs.get("context", {})
        volatility = outputs.get("volatility", {})
        action_int = ACTION_LABEL_TO_INT.get(action_label, 0)
        balance = await self.connector.get_balance()
        portfolio_value = balance.total_equity

        if action_label == "BUY":
            sync_ok = await self._sync_portfolio_risk(balance, {symbol: price})
            if not sync_ok or self._reject_new_long_if_risky(symbol, balance):
                return

        order = await self.broker.execute_action(
            action=action_int,
            symbol=symbol,
            price=price,
            allocation_pct=allocation_pct,
            portfolio_value=portfolio_value,
        )

        if order is None or order.status != "filled":
            self.decision_log.update_execution(symbol, "rejected")
            return

        self._trade_count += 1
        self._daily_trade_count += 1
        self.decision_log.update_execution(symbol, "executed", order.avg_fill_price, order.filled_quantity)
        if action_label == "BUY":
            self._active_stops[symbol] = max(
                0.0, order.avg_fill_price - decision.stop_distance,
            )
        elif action_label == "SELL":
            self._active_stops.pop(symbol, None)

        env = self.environments[symbol]
        reward = env.apply_trade(action_int, order.avg_fill_price, order.filled_quantity)

        # Use the connector equity for portfolio drawdown. Each TradingEnvironment
        # starts from the full paper balance and tracks one symbol, so its value
        # is not the current total portfolio value.
        post_trade_balance = None
        try:
            post_trade_balance = await self.connector.get_balance()
        except Exception as e:
            logger.warning("Portfolio value refresh failed after %s %s: %s", action_label, symbol, e)
        post_trade_equity = (
            post_trade_balance.total_equity if post_trade_balance is not None else portfolio_value
        )
        self._update_risk_state(post_trade_equity)
        # Refresh monitor state from the connector now that the fill has
        # changed cash and positions (as trades happen, not just next tick).
        await self._sync_portfolio_risk(
            post_trade_balance, {symbol: order.avg_fill_price},
        )

        ledger_entry = LedgerEntry(
            timestamp=time.time(),
            symbol=symbol,
            action=action_int,
            action_label=action_label,
            price=order.avg_fill_price,
            quantity=order.filled_quantity,
            state_vector=[
                round(float(volatility.get("atr", 0.0)), 4),
                round(float(volatility.get("z_score", 0.0)), 4),
                round(float(prediction.get("confidence", 0.0)), 4),
                round(env.portfolio_value, 2),
                round(env.cash, 2),
            ],
            reward=round(reward, 6),
            portfolio_value_before=round(portfolio_value, 2),
            portfolio_value_after=round(post_trade_equity, 2),
            transaction_cost=order.commission,
            slippage=abs(order.avg_fill_price - price) * order.filled_quantity,
            agent_reasoning={"prediction": prediction, "context": context, "volatility": volatility},
        )
        self.runtime_ledger.record(ledger_entry)

        if action_label == "BUY":
            self.trade_ledger.record_trade(TradeRecord(
                timestamp=time.time(),
                symbol=symbol,
                direction="BUY",
                entry_price=order.avg_fill_price,
                quantity=order.filled_quantity,
                entry_fee=order.commission,
                volatility_at_entry=float(volatility.get("atr", 0.0)),
                volatility_regime=str(volatility.get("volatility_regime", "")),
                agent_confidences={
                    "predictive": float(prediction.get("confidence", 0.0)),
                    "context_alignment": 0.0,
                },
                risk_multiplier=float(volatility.get("risk_multiplier", 1.0)),
            ))
            if notify_trade:
                try:
                    notify_trade(
                        symbol,
                        "BUY",
                        order.avg_fill_price,
                        allocation_pct,
                        self._active_stops[symbol],
                    )
                except Exception:
                    pass

        if action_label == "SELL":
            self.trade_ledger.close_trade(
                symbol,
                order.avg_fill_price,
                exit_fee=order.commission,
            )

    # ------------------------------------------------------------------
    # Cross-asset portfolio risk helpers
    # ------------------------------------------------------------------

    def _update_risk_state(self, equity: float) -> None:
        now = time.gmtime()
        day_key = time.strftime("%Y-%m-%d", now)
        week_key = time.strftime("%Y-%W", now)
        if day_key != self._risk_day_key:
            self._risk_day_key = day_key
            self._day_start_equity = equity
            self._daily_trade_count = 0
        if week_key != self._risk_week_key:
            self._risk_week_key = week_key
            self._week_start_equity = equity
        self._equity_peak = max(self._equity_peak, equity)

    def _portfolio_snapshot(
        self,
        symbol: str,
        market_data: Dict,
        balance,
        *,
        allow_new_positions: bool,
    ) -> PortfolioSnapshot:
        equity = _safe_number(balance.total_equity) or 0.0
        cash = _safe_number(balance.cash) or 0.0
        price = _safe_close(market_data.get("price"))
        prices = dict(self._last_recorded_close)
        if price is not None:
            prices[symbol] = price
        exposure = sum(
            abs(_safe_number(quantity) or 0.0) * prices.get(held_symbol, 0.0)
            for held_symbol, quantity in (balance.positions or {}).items()
        )
        unpriced_positions = any(
            abs(_safe_number(quantity) or 0.0) > 0
            and prices.get(held_symbol, 0.0) <= 0
            for held_symbol, quantity in (balance.positions or {}).items()
        )
        return PortfolioSnapshot(
            equity=equity,
            cash=cash,
            position_quantity=_safe_number((balance.positions or {}).get(symbol)) or 0.0,
            total_exposure_pct=exposure / equity if equity > 0 else 1.0,
            peak_equity=self._equity_peak,
            daily_pnl_pct=(
                (equity - self._day_start_equity) / self._day_start_equity
                if self._day_start_equity > 0 else 0.0
            ),
            weekly_pnl_pct=(
                (equity - self._week_start_equity) / self._week_start_equity
                if self._week_start_equity > 0 else 0.0
            ),
            drawdown_pct=(equity / self._equity_peak - 1.0) if self._equity_peak > 0 else 0.0,
            daily_trades=self._daily_trade_count,
            active_stop_loss=self._active_stops.get(symbol, 0.0),
            allow_new_positions=allow_new_positions and not unpriced_positions,
        )

    def _portfolio_risk_status(
        self, symbol: str,
    ) -> tuple[bool, List[str], List[str]]:
        if self.portfolio_risk is None:
            logger.error("PortfolioRisk | unavailable; blocking new long for %s", symbol)
            return False, ["portfolio_risk_unavailable"], []
        try:
            assessment = self.portfolio_risk.check_portfolio_risk()
        except Exception as error:
            logger.error(
                "PortfolioRisk | assessment failed for %s; blocking new long: %s",
                symbol, error,
            )
            return False, ["portfolio_risk_assessment_failed"], []
        if assessment.allow_new_position:
            return True, [], list(assessment.correlation_warnings or [])
        reasons = list((assessment.reasoning or {}).get("deny_reasons", []))
        warnings = list(assessment.correlation_warnings or [])
        return False, reasons or ["portfolio_risk_gate"], warnings

    def _portfolio_risk_allows_new_long(self, symbol: str) -> bool:
        allowed, reasons, warnings = self._portfolio_risk_status(symbol)
        if allowed:
            return True
        logger.warning(
            "PortfolioRisk | new long %s blocked: deny_reasons=%s warnings=%s",
            symbol, reasons, warnings,
        )
        return False

    @staticmethod
    def _close_returns(
        closes: Sequence[float], previous_close: Optional[float] = None,
    ) -> tuple[List[float], Optional[float]]:
        """Convert close prices to simple returns; skip stale/duplicate prices.

        ``previous_close`` is the last close already ingested, so a rolling
        history window is not replayed into the monitor on every tick. Returns
        ``(new_returns, last_valid_close)``.
        """
        returns: List[float] = []
        prev: Optional[float] = None
        seen_previous = previous_close is None
        for raw in closes:
            price = _safe_close(raw)
            if price is None:
                continue
            if not seen_previous:
                if price == previous_close:
                    seen_previous = True
                prev = price
                continue
            if prev is not None and price != prev:
                ret = price / prev - 1.0
                if math.isfinite(ret):
                    returns.append(ret)
            prev = price

        if not seen_previous and prev is not None and previous_close:
            # The history rolled past the last observed close; bridge from it
            # to the newest available close rather than dropping the update.
            ret = prev / previous_close - 1.0
            if math.isfinite(ret):
                returns.append(ret)
        return returns, prev

    def _feed_market_returns(self, symbol: str, market_data: Dict) -> None:
        """Feed recent close-to-close returns into the portfolio monitor.

        Resolution note: if the feed exposes a price history we use it; those
        entries are close prices captured on fresh feed fetches (hourly
        TradingView or yfinance-backed), not guaranteed daily bars, and the
        feed caches snapshots for ~60s. Otherwise we fall back to successive
        market-data snapshot closes. Either way these are close-to-close
        returns at bar/snapshot resolution, not tick returns, so the resulting
        correlations and VaR are indicative rather than high-frequency exact.
        """
        if self.portfolio_risk is None:
            return
        try:
            history: Sequence[float] = []
            feed = getattr(self, "_tv_feed", None)
            if feed is not None and hasattr(feed, "get_price_history"):
                history = list(feed.get_price_history(symbol) or [])
            current = _safe_close((market_data or {}).get("price"))
            closes = list(history)
            if current is not None and (not closes or current != _safe_close(closes[-1])):
                closes.append(current)

            returns, last_close = self._close_returns(
                closes, self._last_recorded_close.get(symbol),
            )
            if returns:
                self.portfolio_risk.record_returns_batch(symbol, returns)
            if last_close is not None:
                self._last_recorded_close[symbol] = last_close
        except Exception as e:
            logger.error("PortfolioRisk | return feed failed for %s: %s", symbol, e)

    async def _sync_portfolio_risk(
        self, balance=None, price_updates: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Keep monitor portfolio value and signed notionals in step with exchange state.

        Positions are connector quantities (negative for shorts) multiplied by
        the latest close we have seen, preserving sign for the monitor. A
        position with no known price is treated as zero notional; it picks up
        its value once market data for that symbol arrives.
        """
        if self.portfolio_risk is None:
            return False
        try:
            if balance is None:
                balance = await self.connector.get_balance()
            self.portfolio_risk.update_portfolio_value(balance.total_equity)

            prices = dict(self._last_recorded_close)
            for sym, raw_price in (price_updates or {}).items():
                price = _safe_close(raw_price)
                if price is not None:
                    prices[sym] = price

            positions = dict(balance.positions or {})
            held_symbols = set()
            for sym, raw_qty in positions.items():
                qty = _safe_number(raw_qty)
                if qty is None:
                    continue
                held_symbols.add(sym)
                self.portfolio_risk.set_position(sym, qty * prices.get(sym, 0.0))
            for sym in self._risk_position_symbols - held_symbols:
                self.portfolio_risk.set_position(sym, 0.0)
            self._risk_position_symbols = held_symbols
            return True
        except Exception as e:
            logger.error("PortfolioRisk | portfolio sync failed: %s", e)
            return False

    def _reject_new_long_if_risky(self, symbol: str, balance) -> bool:
        """Return True when a BUY must be skipped and logged as rejected.

        The caller uses this only for BUY orders, so additions to an existing
        long are checked too. Missing or failed risk assessments fail closed.
        SELLs never call this method, so risk reduction remains available.
        """
        allowed, reasons, warnings = self._portfolio_risk_status(symbol)
        if allowed:
            return False

        logger.warning(
            "PortfolioRisk | new long %s rejected: deny_reasons=%s warnings=%s",
            symbol, reasons, warnings,
        )
        try:
            for record in reversed(self.decision_log.records):
                if record.symbol == symbol and record.execution_status == "pending":
                    record.reasoning_chain.append(
                        "PortfolioRisk: new long rejected "
                        f"({', '.join(map(str, reasons)) or 'risk limits'})",
                    )
                    record.risk_check["portfolio_risk"] = {
                        "deny_reasons": reasons,
                        "correlation_warnings": warnings,
                    }
                    break
            self.decision_log.update_execution(symbol, "rejected")
        except Exception as e:
            logger.error("PortfolioRisk | decision log update failed for %s: %s", symbol, e)
        return True

    def stop(self) -> None:
        self._running = False
        self.runtime_ledger.save()
        self.trade_ledger.save()
        logger.info("Orchestrator | shutdown — ledger saved")


async def main() -> None:
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    logger.info("=" * 60)
    logger.info("Multi-Agent Trading Research — Paper Mode (no live orders)")
    logger.info("Assets: Gold, Silver, Forex, Stocks, ETFs")
    logger.info(
        "Data: yfinance primary | Policy: Predictive + Context + Volatility; "
        "debate is explanatory, sentiment excluded"
    )
    logger.info("=" * 60)

    orchestrator = TradingOrchestrator(settings)
    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
        orchestrator.stop()
    except Exception as e:
        logger.critical("Fatal error: %s", e)
        import traceback
        traceback.print_exc()
        orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
