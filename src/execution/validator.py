"""Order validator — validates and sanitizes order requests before submission."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

VALID_ACTIONS = {"buy", "sell"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")


@dataclass
class OrderRequest:
    """Order request to be validated."""

    symbol: str
    action: str
    size_usd: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    decision_id: Optional[int] = None


class OrderValidator:
    """Validates order requests against format, limits, and duplication rules."""

    def __init__(
        self,
        max_order_size: float = 100000.0,
        min_order_size: float = 1.0,
        precision: int = 8,
    ) -> None:
        self.max_order_size = max_order_size
        self.min_order_size = min_order_size
        self.precision = precision
        self._recent_orders: set[str] = set()

    def validate(self, order: OrderRequest) -> list[str]:
        """Validate an order request and return list of error messages.

        Returns empty list if order is valid.
        """
        errors: list[str] = []

        errors.extend(self._validate_symbol(order.symbol))
        errors.extend(self._validate_action(order.action))
        errors.extend(self._validate_size(order.size_usd))
        errors.extend(self._validate_limits(order.size_usd))
        errors.extend(self._validate_not_duplicate(order))

        return errors

    def _validate_symbol(self, symbol: str) -> list[str]:
        """Validate symbol format (e.g. 'BTC/USDT')."""
        errors: list[str] = []
        if not isinstance(symbol, str) or not symbol:
            errors.append("Symbol must be a non-empty string")
            return errors
        if not SYMBOL_PATTERN.match(symbol):
            errors.append(f"Invalid symbol format: '{symbol}'. Expected format: 'BASE/QUOTE' (e.g. 'BTC/USDT')")
        return errors

    def _validate_action(self, action: str) -> list[str]:
        """Validate action is one of the allowed values."""
        errors: list[str] = []
        if action not in VALID_ACTIONS:
            errors.append(f"Invalid action: '{action}'. Must be one of {VALID_ACTIONS}")
        return errors

    def _validate_size(self, size: float) -> list[str]:
        """Validate order size is positive."""
        errors: list[str] = []
        if not isinstance(size, (int, float)) or size <= 0:
            errors.append(f"Order size must be positive, got: {size}")
        return errors

    def _validate_limits(self, size: float) -> list[str]:
        """Validate order size is within configured limits."""
        errors: list[str] = []
        if size < self.min_order_size:
            errors.append(f"Order size {size} below minimum {self.min_order_size}")
        if size > self.max_order_size:
            errors.append(f"Order size {size} exceeds maximum {self.max_order_size}")
        return errors

    def _validate_not_duplicate(self, order: OrderRequest) -> list[str]:
        """Check if order is a duplicate of a recent order."""
        errors: list[str] = []
        order_key = f"{order.symbol}:{order.action}:{order.size_usd}"
        if order_key in self._recent_orders:
            errors.append(f"Duplicate order detected: {order_key}")
        return errors

    def sanitize(self, order: OrderRequest) -> OrderRequest:
        """Sanitize order values to exchange precision.

        Rounds size to configured decimal precision.
        """
        size_decimal = Decimal(str(order.size_usd))
        rounded = size_decimal.quantize(
            Decimal(10) ** -self.precision,
            rounding=ROUND_DOWN,
        )
        order.size_usd = float(rounded)

        if order.price is not None:
            price_decimal = Decimal(str(order.price))
            order.price = float(price_decimal.quantize(
                Decimal(10) ** -self.precision,
                rounding=ROUND_DOWN,
            ))

        return order

    def record_order(self, order: OrderRequest) -> None:
        """Record an order to prevent duplicates.

        Call this after successful order submission.
        """
        order_key = f"{order.symbol}:{order.action}:{order.size_usd}"
        self._recent_orders.add(order_key)

        if len(self._recent_orders) > 1000:
            self._recent_orders = set(list(self._recent_orders)[-500:])

    def clear_recent(self) -> None:
        """Clear recent orders history."""
        self._recent_orders.clear()
