from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from connectors.platform import BaseExchangeConnector, OrderResult

logger = logging.getLogger(__name__)

ACTION_MAP: Dict[int, str] = {0: "HOLD", 1: "BUY", 2: "SELL"}
ACTION_LABEL_TO_INT: Dict[str, int] = {"HOLD": 0, "BUY": 1, "SELL": 2}

MAX_ORDER_SIZE: float = 1.0


@dataclass
class ExecutionConstraints:
    max_order_size: float = MAX_ORDER_SIZE
    max_position_pct: float = 0.25
    slippage_bps: float = 2.0
    spread_bps: float = 1.0
    commission_pct: float = 0.001


@dataclass
class FilledCostBreakdown:
    theoretical_price: float = 0.0
    fill_price: float = 0.0
    slippage_cost: float = 0.0
    spread_cost: float = 0.0
    commission_cost: float = 0.0
    total_cost_pct: float = 0.0
    net_price: float = 0.0


class Broker:
    """Executes trades with slippage/spread/commission cost modelling.

    Slippage formula (aligned with risk_manager):
        fill_price = price * (1 ± slippage_bps/10000 ± spread_bps/20000)
    where ± is + for buy, - for sell.
    """

    def __init__(
        self,
        connector: BaseExchangeConnector,
        constraints: Optional[ExecutionConstraints] = None,
    ) -> None:
        self.connector = connector
        self.constraints = constraints or ExecutionConstraints()

    def estimate_fill_price(self, side: str, price: float) -> FilledCostBreakdown:
        cons = self.constraints
        if side == "buy":
            fill_price = price * (1.0 + cons.slippage_bps / 10000.0 + cons.spread_bps / 20000.0)
        else:
            fill_price = price * (1.0 - cons.slippage_bps / 10000.0 - cons.spread_bps / 20000.0)
        slip_cost = abs(fill_price - price)
        spread_cost = price * cons.spread_bps / 10000.0
        comm_cost = price * cons.commission_pct
        total_cost = slip_cost + spread_cost + comm_cost
        total_pct = total_cost / price if price > 0 else 0.0
        return FilledCostBreakdown(
            theoretical_price=price,
            fill_price=round(fill_price, 8),
            slippage_cost=round(slip_cost, 8),
            spread_cost=round(spread_cost, 8),
            commission_cost=round(comm_cost, 8),
            total_cost_pct=round(total_pct, 6),
            net_price=round(fill_price + (comm_cost if side == "buy" else -comm_cost), 8),
        )

    def risk_adjusted_quantity(self, side: str, price: float, allocation_pct: float, portfolio_value: float, max_risk_per_trade: float) -> Tuple[float, float, FilledCostBreakdown]:
        cost_breakdown = self.estimate_fill_price(side, price)
        fill_price = cost_breakdown.fill_price
        theoretical_notional = portfolio_value * allocation_pct
        raw_qty = theoretical_notional / price if price > 0 else 0.0
        fill_notional = raw_qty * fill_price
        actual_risk = fill_notional * cost_breakdown.total_cost_pct
        max_risk_notional = portfolio_value * max_risk_per_trade
        if actual_risk > max_risk_notional and actual_risk > 0:
            risk_scale = max_risk_notional / actual_risk
            raw_qty *= risk_scale
        raw_qty = min(raw_qty, self.constraints.max_order_size)
        return raw_qty, fill_price, cost_breakdown

    async def execute_action(
        self,
        action: int,
        symbol: str,
        price: float,
        allocation_pct: float,
        portfolio_value: float,
        max_risk_per_trade: float = 0.02,
    ) -> Optional[OrderResult]:
        label = ACTION_MAP.get(action, "HOLD")
        if label == "HOLD":
            return None
        side = "buy" if label == "BUY" else "sell"
        quantity, fill_price, cost = self.risk_adjusted_quantity(side, price, allocation_pct, portfolio_value, max_risk_per_trade)
        if quantity <= 0:
            logger.warning("Broker | quantity <= 0 after risk adjustment -> HOLD")
            return None
        result = await self.connector.execute_order(symbol, side, quantity)
        logger.info(
            "Broker | %s %s %.6f theo=%.2f fill=%.2f cost=%.4f%% slippage=%.2fbps spread=%.2fbps comm=%.4f%% | status=%s",
            side, symbol, quantity, price, fill_price,
            cost.total_cost_pct * 100, self.constraints.slippage_bps,
            self.constraints.spread_bps, self.constraints.commission_pct * 100,
            result.status,
        )
        return result

    async def get_balance_snapshot(self):
        return await self.connector.get_balance()

    async def get_market_data(self, symbol: str):
        return await self.connector.get_market_data(symbol)
