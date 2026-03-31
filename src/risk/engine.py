"""Risk Engine — validates orders against risk rules before execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import structlog

from src.database.repository import Repository
from src.execution.validator import OrderRequest
from src.risk.position_sizing import calculate_position_size, check_exposure

logger = structlog.get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of risk validation."""

    passed: bool
    reason: str = ""


class RiskEngine:
    """Independent risk engine that validates all orders before execution.

    Never bypassed — every order must pass risk checks.
    """

    def __init__(self, config: dict[str, Any], repository: Repository) -> None:
        self.config = config
        self.repository = repository

        risk_cfg = config.get("risk", {})
        self.max_positions: int = risk_cfg.get("max_positions", 5)
        self.risk_per_trade: float = risk_cfg.get("risk_per_trade", 0.02)
        self.max_exposure: float = risk_cfg.get("max_exposure", 0.5)
        self.stop_loss_pct: float = risk_cfg.get("stop_loss", 0.05)
        self.max_daily_loss: float = risk_cfg.get("max_daily_loss", 0.05)
        self.max_drawdown: float = risk_cfg.get("max_drawdown", 0.15)

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is currently active."""
        try:
            return self.repository.is_kill_switch_active()
        except Exception as exc:
            logger.error("Failed to check kill switch", error=str(exc))
            return True

    def _check_daily_loss(self, total_balance: float) -> tuple[bool, str]:
        """Check if daily loss limit has been exceeded."""
        try:
            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

            orders = self.repository.get_orders(limit=1000)
            daily_pnl = 0.0

            for order in orders:
                if order.timestamp >= start_of_day and order.status in ("filled", "rejected"):
                    if order.status == "rejected":
                        daily_pnl -= order.size_usd * 0.01

            if total_balance > 0:
                daily_loss_pct = abs(daily_pnl) / total_balance
                if daily_loss_pct >= self.max_daily_loss:
                    return False, f"Daily loss limit reached: {daily_loss_pct:.2%}"

            return True, ""
        except Exception as exc:
            logger.warning("Failed to check daily loss", error=str(exc))
            return True, ""

    def _check_drawdown(self, total_balance: float) -> tuple[bool, str]:
        """Check if max drawdown has been exceeded."""
        try:
            snapshot = self.repository.get_latest_snapshot()
            if snapshot and snapshot.drawdown_pct >= self.max_drawdown:
                return False, f"Max drawdown exceeded: {snapshot.drawdown_pct:.2%}"
            return True, ""
        except Exception as exc:
            logger.warning("Failed to check drawdown", error=str(exc))
            return True, ""

    def _check_max_positions(self, current_positions: int) -> tuple[bool, str]:
        """Check if max position limit would be exceeded."""
        if current_positions >= self.max_positions:
            return False, f"Max positions reached: {current_positions}/{self.max_positions}"
        return True, ""

    def _check_exposure(
        self,
        positions: list[dict[str, Any]],
        order_size: float,
        total_balance: float,
    ) -> tuple[bool, str]:
        """Check if order would exceed max exposure."""
        if total_balance <= 0:
            return False, "Invalid total balance"

        current_exposure = sum(p.get("size_usd", 0.0) for p in positions)
        new_exposure = current_exposure + order_size
        exposure_pct = new_exposure / total_balance

        if exposure_pct > self.max_exposure:
            return False, f"Max exposure exceeded: {exposure_pct:.2%} > {self.max_exposure:.2%}"
        return True, ""

    def _check_stop_loss(self, order: OrderRequest) -> tuple[bool, str]:
        """Check that stop loss is set for the order."""
        if order.action in ("buy", "sell") and order.stop_loss is None:
            return False, "Stop loss is mandatory for all orders"
        return True, ""

    def _check_order_size(self, order: OrderRequest, total_balance: float) -> tuple[bool, str]:
        """Check that order size is within limits."""
        if order.size_usd <= 0:
            return False, "Order size must be positive"

        max_single_trade = total_balance * self.risk_per_trade / self.stop_loss_pct
        if order.size_usd > max_single_trade:
            return False, f"Order size {order.size_usd:.2f} exceeds max {max_single_trade:.2f}"
        return True, ""

    def validate_order(
        self,
        order: OrderRequest,
        total_balance: float = 0.0,
        current_positions: int = 0,
        positions: Optional[list[dict[str, Any]]] = None,
    ) -> ValidationResult:
        """Validate an order against all risk rules.

        Args:
            order: The order request to validate.
            total_balance: Current total account balance.
            current_positions: Number of currently open positions.
            positions: List of current position dicts.

        Returns:
            ValidationResult with passed=True if all checks pass.
        """
        if self.is_kill_switch_active():
            logger.warning("Order rejected: kill switch active", symbol=order.symbol)
            return ValidationResult(passed=False, reason="Kill switch is active")

        checks = [
            self._check_stop_loss(order),
            self._check_order_size(order, total_balance),
            self._check_max_positions(current_positions),
            self._check_daily_loss(total_balance),
            self._check_drawdown(total_balance),
        ]

        if positions is not None:
            checks.append(self._check_exposure(positions, order.size_usd, total_balance))

        for passed, reason in checks:
            if not passed:
                logger.warning("Order rejected", symbol=order.symbol, reason=reason)
                return ValidationResult(passed=False, reason=reason)

        logger.info("Order validated", symbol=order.symbol, action=order.action)
        return ValidationResult(passed=True)

    def calculate_position_size(
        self,
        balance: float,
        risk_per_trade: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
    ) -> float:
        """Calculate position size using risk parameters.

        Args:
            balance: Account balance.
            risk_per_trade: Override for risk per trade fraction.
            stop_loss_pct: Override for stop loss percentage.

        Returns:
            Position size in USD.
        """
        rpt = risk_per_trade if risk_per_trade is not None else self.risk_per_trade
        slp = stop_loss_pct if stop_loss_pct is not None else self.stop_loss_pct
        return calculate_position_size(balance, rpt, slp)
