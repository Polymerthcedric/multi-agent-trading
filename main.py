from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
from dataclasses import asdict
from typing import Dict, List, Optional, Sequence

from config.settings import Settings
from agents.predictive import PredictiveAgent
from agents.context import ContextAgent
from agents.volatility import VolatilityAgent
from agents.sentiment import SentimentAgent
from agents.debate import BullBearDebate
from agents.decision_log import DecisionLogger, DecisionRecord
from agents.risk_manager import RiskManager
from connectors.platform import PaperTradingConnector, OrderResult
from execution.broker import Broker, ACTION_LABEL_TO_INT
from execution.engine import SearchEngine
from engine.environment import TradingEnvironment
from engine.ledger import RuntimeLedger, LedgerEntry
from memory.feedback_loop import TradeLedger, TradeRecord, SelfLearningCritic

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

        self.predictive = PredictiveAgent()
        self.context = ContextAgent()
        self.sentiment = SentimentAgent()
        self.debate = BullBearDebate()
        self.decision_log = DecisionLogger()

        self.volatility_map: Dict[str, VolatilityAgent] = {
            sym: VolatilityAgent() for sym in settings.symbols
        }
        self.risk = RiskManager()

        initial_balance = STARTING_PORTFOLIO_VALUE
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
        self.search_engine = SearchEngine(
            max_depth=5, n_simulations=80, time_limit_ms=3000.0, noise_scale=0.015,
        )
        self.environments: Dict[str, TradingEnvironment] = {
            sym: TradingEnvironment(initial_balance=initial_balance) for sym in settings.symbols
        }
        self.runtime_ledger = RuntimeLedger()
        self.trade_ledger = TradeLedger()
        self.critic = SelfLearningCritic(cadence=settings.learning_cadence_trades)

        self._running = False
        self._trade_count = 0
        self._consecutive_errors = 0

    async def run(self) -> None:
        self._running = True
        logger.info("Symbols=%s | PaperTrading | yfinance primary", self.settings.symbols)

        if notify_bot_start:
            try:
                notify_bot_start("PAPER", self.settings.symbols)
            except Exception:
                pass

        step = 0
        max_steps = self.settings.max_daily_trades * len(self.settings.symbols)
        while self._running and step < max_steps:
            step += 1

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

                # Feed close-to-close returns for correlation/VaR before the
                # pipeline runs; failures are contained inside the helper.
                self._feed_market_returns(symbol, market_data)

                try:
                    prediction = await self.predictive.analyze(market_data)
                    context_result = await self.context.analyze(market_data)
                    vol_agent = self.volatility_map[symbol]
                    volatility_result = await vol_agent.analyze(market_data)
                    sentiment_result = await self.sentiment.analyze(symbol, market_data)

                    pred_dict = asdict(prediction)
                    ctx_dict = asdict(context_result)
                    vol_dict = asdict(volatility_result)
                    sent_dict = {
                        "label": sentiment_result.label,
                        "score": sentiment_result.score,
                        "confidence": sentiment_result.confidence,
                        "news_count": sentiment_result.news_count,
                    }

                    debate_result = self.debate.debate(
                        symbol=symbol,
                        prediction=pred_dict,
                        context=ctx_dict,
                        volatility=vol_dict,
                        sentiment=sent_dict,
                        market_data=market_data,
                        original_confidence=prediction.confidence,
                    )

                    adjusted_prediction = dict(pred_dict)
                    adjusted_prediction["confidence"] = debate_result.adjusted_confidence

                    decision = await self.risk.evaluate(
                        prediction=adjusted_prediction,
                        context=ctx_dict,
                        volatility=vol_dict,
                        market_data=market_data,
                    )

                    reasoning_chain = []
                    reasoning_chain.append(f"Predictive: {prediction.direction} (conf={prediction.confidence:.3f})")
                    reasoning_chain.append(f"Context: {ctx_dict.get('signal_alignment', 'neutral')} regime={ctx_dict.get('regime', '?')}")
                    reasoning_chain.append(f"Volatility: {vol_dict.get('volatility_regime', '?')} mult={vol_dict.get('risk_multiplier', 1.0):.2f}")
                    reasoning_chain.append(f"Sentiment: {sentiment_result.label} (score={sentiment_result.score:.3f}, news={sentiment_result.news_count})")
                    reasoning_chain.append(f"Debate: bull={debate_result.bull_argument.strength:.3f} bear={debate_result.bear_argument.strength:.3f} -> {debate_result.winner}")
                    reasoning_chain.append(f"Confidence: {prediction.confidence:.3f} -> {debate_result.adjusted_confidence:.3f} (debate adjustment)")
                    reasoning_chain.append(f"Risk: {decision.action} alloc={decision.allocation_pct:.4f}")

                    record = DecisionRecord(
                        timestamp=time.time(),
                        symbol=symbol,
                        action=decision.action,
                        confidence=prediction.confidence,
                        adjusted_confidence=debate_result.adjusted_confidence,
                        allocation_pct=decision.allocation_pct,
                        stop_loss=decision.stop_loss,
                        price=market_data.get("price", 0),
                        agent_outputs={
                            "prediction": pred_dict,
                            "context": ctx_dict,
                            "volatility": vol_dict,
                        },
                        debate_result=debate_result.reasoning,
                        sentiment_result=sentiment_result.reasoning,
                        risk_check=decision.reasoning,
                        market_snapshot=market_data,
                        reasoning_chain=reasoning_chain,
                    )
                    self.decision_log.log(record)

                except Exception as e:
                    logger.error("Agent pipeline error for %s: %s", symbol, e)
                    continue

                logger.info(
                    "RESULT symbol=%s action=%s alloc=%.2f%% stop=%.2f conf=%.3f->%.3f",
                    symbol, decision.action, decision.allocation_pct * 100,
                    decision.stop_loss, prediction.confidence, debate_result.adjusted_confidence,
                )

                if decision.action != "HOLD":
                    await self._execute_trade(
                        symbol=symbol,
                        action_label=decision.action,
                        allocation_pct=decision.allocation_pct,
                        price=market_data["price"],
                        prediction=prediction,
                        context=context_result,
                        volatility=volatility_result,
                        decision=decision,
                    )
                else:
                    try:
                        await self.search_engine.update_state(symbol, market_data)
                        search_action, search_score, search_metrics = await self.search_engine.search_best_action(symbol)
                        logger.info(
                            "SEARCH symbol=%s action=%s score=%.4f",
                            symbol, search_action, search_score,
                        )
                    except Exception as e:
                        logger.warning("Search engine error for %s: %s", symbol, e)

                try:
                    balance = await self.connector.get_balance()
                    self.risk.update_portfolio_value(balance.total_equity)
                    await self._sync_portfolio_risk(
                        balance, {symbol: market_data.get("price", 0.0)},
                    )
                except Exception as e:
                    logger.warning("Portfolio risk sync skipped for %s: %s", symbol, e)

            await asyncio.sleep(self.settings.simulation_tick_interval_sec)

        self.runtime_ledger.save()
        self.trade_ledger.save()
        self.search_engine.save_metrics()
        self._running = False
        logger.info("Orchestrator | simulation complete — %d trades executed", self._trade_count)

    async def _execute_trade(
        self,
        symbol: str,
        action_label: str,
        allocation_pct: float,
        price: float,
        prediction, context, volatility,
        decision=None,
    ) -> None:
        action_int = ACTION_LABEL_TO_INT.get(action_label, 0)
        balance = await self.connector.get_balance()
        portfolio_value = balance.total_equity

        if action_label == "BUY":
            # Only a genuinely new long is gated; SELLs (and adding to an
            # existing position) stay available so risk can always be reduced.
            await self._sync_portfolio_risk(balance, {symbol: price})
            if self._reject_new_long_if_risky(symbol, balance):
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
        self.decision_log.update_execution(symbol, "executed", order.avg_fill_price, order.filled_quantity)

        env = self.environments[symbol]
        reward = env.apply_trade(action_int, order.avg_fill_price, order.filled_quantity)

        self.risk.update_portfolio_value(env.portfolio_value)
        # Refresh monitor state from the connector now that the fill has
        # changed cash and positions (as trades happen, not just next tick).
        await self._sync_portfolio_risk(price_updates={symbol: order.avg_fill_price})

        ledger_entry = LedgerEntry(
            timestamp=time.time(),
            symbol=symbol,
            action=action_int,
            action_label=action_label,
            price=order.avg_fill_price,
            quantity=order.filled_quantity,
            state_vector=[
                round(volatility.atr, 4),
                round(volatility.z_score, 4),
                round(prediction.confidence if hasattr(prediction, "confidence") else 0.0, 4),
                round(env.portfolio_value, 2),
                round(env.cash, 2),
            ],
            reward=round(reward, 6),
            portfolio_value_before=round(portfolio_value, 2),
            portfolio_value_after=round(env.portfolio_value, 2),
            transaction_cost=portfolio_value * env.tc_pct,
            slippage=portfolio_value * env.slippage_pct,
            agent_reasoning={
                "prediction": asdict(prediction),
                "context": asdict(context),
                "volatility": asdict(volatility),
            },
        )
        self.runtime_ledger.record(ledger_entry)

        if action_label == "BUY":
            self.trade_ledger.record_trade(TradeRecord(
                timestamp=time.time(),
                symbol=symbol,
                direction="BUY",
                entry_price=order.avg_fill_price,
                quantity=order.filled_quantity,
                volatility_at_entry=volatility.atr,
                volatility_regime=volatility.volatility_regime,
                agent_confidences={"predictive": prediction.confidence, "context_alignment": 0.0},
                risk_multiplier=volatility.risk_multiplier,
            ))
            alloc = decision.allocation_pct if decision else allocation_pct
            sl = decision.stop_loss if decision else 0.0
            if notify_trade:
                try:
                    notify_trade(symbol, "BUY", order.avg_fill_price, alloc, sl)
                except Exception:
                    pass

        if action_label == "SELL":
            closed = self.trade_ledger.close_trade(symbol, order.avg_fill_price)
            if closed:
                self.risk.update_daily_pnl(closed.pnl)
                learned = self.critic.evaluate(self.trade_ledger)
                if learned is not None:
                    self.risk.apply_learned_params(
                        learned.confidence_threshold,
                        learned.position_sizing_k,
                    )
                    logger.info(
                        "FEEDBACK | updated risk params: conf=%.4f kelly=%.4f perf=%.4f",
                        learned.confidence_threshold, learned.position_sizing_k, learned.performance_score,
                    )

    # ------------------------------------------------------------------
    # Cross-asset portfolio risk helpers
    # ------------------------------------------------------------------

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
    ) -> None:
        """Keep monitor portfolio value and signed notionals in step with exchange state.

        Positions are connector quantities (negative for shorts) multiplied by
        the latest close we have seen, preserving sign for the monitor. A
        position with no known price is treated as zero notional; it picks up
        its value once market data for that symbol arrives.
        """
        if self.portfolio_risk is None:
            return
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
        except Exception as e:
            logger.error("PortfolioRisk | portfolio sync failed: %s", e)

    def _reject_new_long_if_risky(self, symbol: str, balance) -> bool:
        """Return True when a new long must be skipped and logged as rejected.

        A monitor failure fails open (trading continues) but is logged. An
        existing position of either sign is never gated, so SELLs and risk
        reduction always remain available.
        """
        if self.portfolio_risk is None:
            return False
        try:
            existing_qty = _safe_number((balance.positions or {}).get(symbol, 0.0)) or 0.0
        except Exception:
            existing_qty = 0.0
        if existing_qty != 0.0:
            return False

        try:
            assessment = self.portfolio_risk.check_portfolio_risk()
        except Exception as e:
            logger.error("PortfolioRisk | risk check failed for %s: %s", symbol, e)
            return False
        if assessment.allow_new_position:
            return False

        reasons = list((assessment.reasoning or {}).get("deny_reasons", []))
        warnings = list(assessment.correlation_warnings or [])
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
        self.search_engine.save_metrics()
        logger.info("Orchestrator | shutdown — ledger saved")


async def main() -> None:
    from logging_config import setup_logging

    settings = Settings()
    setup_logging(settings)

    logger.info("=" * 60)
    logger.info("Multi-Agent Autonomous Trading — Paper Mode")
    logger.info("Assets: Gold, Silver, Forex, Stocks, ETFs")
    logger.info("Data: yfinance primary | Agents: Predictive + Context + Volatility + Sentiment + Debate")
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
