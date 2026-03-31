"""Trading simulator for backtesting.

Tracks portfolio state, simulates fills with slippage and fees,
and records trade history.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TradeRecord:
    """A single completed trade."""

    symbol: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    entry_time: datetime
    exit_time: datetime
    fees: float
    slippage: float


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state."""

    timestamp: datetime
    cash: float
    position_size: float
    position_price: float
    portfolio_value: float
    step_index: int


@dataclass
class SimulatedFill:
    """Result of a simulated order fill."""

    filled: bool
    price: float
    size: float
    fee: float
    slippage: float
    reason: str = ""


class TradingSimulator:
    """Simulates trading with configurable slippage and fees.

    Starts with initial capital, tracks positions and cash,
    and records every trade for later metric computation.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        fee_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        symbol: str = "BTC/USDT",
    ) -> None:
        self._initial_capital = initial_capital
        self._fee_pct = fee_pct
        self._slippage_pct = slippage_pct
        self._symbol = symbol

        self._cash = initial_capital
        self._position_size = 0.0
        self._entry_price = 0.0
        self._entry_time: Optional[datetime] = None
        self._portfolio_value = initial_capital

        self._trades: list[TradeRecord] = []
        self._snapshots: list[PortfolioSnapshot] = []
        self._peak_value = initial_capital

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def position_size(self) -> float:
        return self._position_size

    @property
    def is_in_position(self) -> bool:
        return self._position_size > 0

    @property
    def portfolio_value(self) -> float:
        return self._portfolio_value

    @property
    def trades(self) -> list[TradeRecord]:
        return list(self._trades)

    @property
    def snapshots(self) -> list[PortfolioSnapshot]:
        return list(self._snapshots)

    @property
    def initial_capital(self) -> float:
        return self._initial_capital

    def _apply_slippage(self, price: float, side: str) -> float:
        if side == "buy":
            return price * (1.0 + self._slippage_pct)
        return price * (1.0 - self._slippage_pct)

    def _calc_fee(self, amount: float) -> float:
        return amount * self._fee_pct

    def _update_portfolio_value(self, current_price: float) -> None:
        position_value = self._position_size * current_price if self._position_size > 0 else 0.0
        self._portfolio_value = self._cash + position_value
        if self._portfolio_value > self._peak_value:
            self._peak_value = self._portfolio_value

    def snapshot(self, timestamp: datetime, current_price: float, step_index: int) -> None:
        self._update_portfolio_value(current_price)
        self._snapshots.append(
            PortfolioSnapshot(
                timestamp=timestamp,
                cash=round(self._cash, 2),
                position_size=round(self._position_size, 8),
                position_price=round(self._entry_price, 2) if self._entry_price else 0.0,
                portfolio_value=round(self._portfolio_value, 2),
                step_index=step_index,
            )
        )

    def simulate_buy(
        self,
        price: float,
        timestamp: datetime,
        allocation_pct: float = 1.0,
    ) -> SimulatedFill:
        if self._position_size > 0:
            return SimulatedFill(filled=False, price=price, size=0, fee=0, slippage=0, reason="already_in_position")

        alloc = self._cash * allocation_pct
        slipped = self._apply_slippage(price, "buy")
        fee = self._calc_fee(alloc)
        net_alloc = alloc - fee

        if net_alloc <= 0:
            return SimulatedFill(filled=False, price=price, size=0, fee=0, slippage=0, reason="insufficient_capital")

        size = net_alloc / slipped
        self._cash -= alloc
        self._position_size = size
        self._entry_price = slipped
        self._entry_time = timestamp

        logger.info(
            "simulated_buy",
            symbol=self._symbol,
            price=round(slipped, 2),
            size=round(size, 8),
            fee=round(fee, 2),
        )

        return SimulatedFill(
            filled=True,
            price=round(slipped, 2),
            size=round(size, 8),
            fee=round(fee, 2),
            slippage=round(slipped - price, 2),
        )

    def simulate_sell(self, price: float, timestamp: datetime) -> SimulatedFill:
        if self._position_size <= 0:
            return SimulatedFill(filled=False, price=price, size=0, fee=0, slippage=0, reason="no_position")

        gross = self._position_size * price
        slipped = self._apply_slippage(price, "sell")
        net_proceeds = self._position_size * slipped
        fee = self._calc_fee(net_proceeds)
        net = net_proceeds - fee

        pnl = net - (self._position_size * self._entry_price)
        pnl_pct = pnl / (self._position_size * self._entry_price) if self._entry_price > 0 else 0.0

        trade = TradeRecord(
            symbol=self._symbol,
            side="long",
            entry_price=round(self._entry_price, 2),
            exit_price=round(slipped, 2),
            size=round(self._position_size, 8),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            entry_time=self._entry_time or timestamp,
            exit_time=timestamp,
            fees=round(fee, 2),
            slippage=round(price - slipped, 2),
        )
        self._trades.append(trade)

        self._cash += net
        self._position_size = 0.0
        self._entry_price = 0.0
        self._entry_time = None

        logger.info(
            "simulated_sell",
            symbol=self._symbol,
            price=round(slipped, 2),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
        )

        return SimulatedFill(
            filled=True,
            price=round(slipped, 2),
            size=round(trade.size, 8),
            fee=round(fee, 2),
            slippage=round(price - slipped, 2),
        )

    def force_close(self, price: float, timestamp: datetime) -> Optional[SimulatedFill]:
        if self._position_size <= 0:
            return None
        return self.simulate_sell(price, timestamp)

    def finalize(self) -> dict[str, Any]:
        if self._position_size > 0 and self._snapshots:
            last_price = self._snapshots[-1].position_price if self._snapshots[-1].position_price > 0 else self._entry_price
            if last_price > 0:
                self.simulate_sell(last_price, self._snapshots[-1].timestamp)

        total_pnl = self._portfolio_value - self._initial_capital
        return {
            "final_value": round(self._portfolio_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / self._initial_capital, 4),
            "total_trades": len(self._trades),
            "cash": round(self._cash, 2),
        }
