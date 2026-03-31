"""Execution Service — orchestrates order execution with risk checks
and audit logging. Supports human-in-the-loop approval."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.decision_engine import Decision
from src.database.models import OrderRecord
from src.database.repository import Repository
from src.execution.approval import ApprovalManager, ApprovalStatus
from src.execution.validator import OrderRequest, OrderValidator
from src.freqtrade_client.client import FreqtradeClient
from src.risk.engine import RiskEngine

logger = structlog.get_logger(__name__)


@dataclass
class ExecutionResult:
    """Result of an order execution attempt."""

    success: bool
    order_id: str = ""
    message: str = ""
    rejected_reason: str = ""


class RateLimiter:
    """Track and enforce rate limits on order submissions."""

    def __init__(self, max_orders_per_minute: int = 10) -> None:
        self.max_orders_per_minute = max_orders_per_minute
        self._orders: dict[str, list[float]] = defaultdict(list)

    def check(self, symbol: str) -> tuple[bool, str]:
        """Check if order is within rate limit.

        Returns:
            Tuple of (allowed, reason).
        """
        now = time.time()
        window_start = now - 60.0

        self._orders[symbol] = [
            ts for ts in self._orders[symbol] if ts > window_start
        ]

        if len(self._orders[symbol]) >= self.max_orders_per_minute:
            return False, f"Rate limit exceeded for {symbol}: {self.max_orders_per_minute}/min"

        return True, ""

    def record(self, symbol: str) -> None:
        """Record an order submission for rate limiting."""
        self._orders[symbol].append(time.time())


class ExecutionService:
    """Main execution service that routes decisions to Freqtrade.

    Every order attempt is logged to the database for audit trail.
    Supports human-in-the-loop approval mode.
    """

    def __init__(
        self,
        config: dict[str, Any],
        risk_engine: RiskEngine,
        freqtrade_client: FreqtradeClient,
        repository: Repository,
    ) -> None:
        self.config = config
        self.risk_engine = risk_engine
        self.freqtrade_client = freqtrade_client
        self.repository = repository

        exec_cfg = config.get("execution", {})
        self.dry_run: bool = exec_cfg.get("dry_run", True)

        rate_limit = exec_cfg.get("rate_limit", 10)
        self.rate_limiter = RateLimiter(max_orders_per_minute=rate_limit)

        self.validator = OrderValidator(
            max_order_size=100000.0,
            min_order_size=1.0,
            precision=8,
        )

        # Human-in-the-loop
        approval_cfg = exec_cfg.get("approval", {})
        self.approval_required: bool = approval_cfg.get("enabled", False)
        self.approval_timeout: int = approval_cfg.get("timeout_sec", 300)
        self.approval_manager = ApprovalManager(
            enabled=self.approval_required,
            timeout_sec=self.approval_timeout,
            auto_approve_dry_run=self.dry_run,
        )

    def _audit_log(
        self,
        decision: Decision,
        success: bool,
        order_id: str = "",
        reason: str = "",
        rejected_reason: str = "",
    ) -> None:
        """Save execution attempt to database for audit trail."""
        try:
            order = OrderRecord(
                decision_id=decision.id if hasattr(decision, "id") else None,
                symbol=decision.symbol,
                action=decision.action,
                size_usd=0.0,
                status="filled" if success else "rejected",
                freqtrade_order_id=order_id if order_id else None,
                reason=reason,
                rejected_reason=rejected_reason,
                timestamp=datetime.now(UTC),
            )
            self.repository.save_order(order)
            logger.info(
                "Audit log saved",
                symbol=decision.symbol,
                success=success,
                order_id=order_id,
            )
        except Exception as exc:
            logger.error("Failed to save audit log", error=str(exc))

    async def execute(self, decision: Decision) -> ExecutionResult:
        """Execute a trading decision.

        Pipeline:
            1. Skip hold decisions
            2. Human-in-the-loop approval (if enabled)
            3. Validate order format
            4. Risk engine check
            5. Rate limit check
            6. Audit log
            7. Forward to Freqtrade

        Args:
            decision: Decision object from DecisionEngine.

        Returns:
            ExecutionResult with success status and details.
        """
        logger.info(
            "Executing decision",
            symbol=decision.symbol,
            action=decision.action,
            score=decision.score,
        )

        if decision.action == "hold":
            logger.info("Hold decision, skipping execution", symbol=decision.symbol)
            return ExecutionResult(
                success=True,
                message="Hold — no action taken",
            )

        # Human-in-the-loop: create approval request
        if self.approval_required:
            approval_result = await self._handle_approval(decision)
            if not approval_result:
                return ExecutionResult(
                    success=False,
                    rejected_reason="Approval not granted",
                    message="Waiting for human approval or request expired",
                )

        order = OrderRequest(
            symbol=decision.symbol,
            action=decision.action,
            size_usd=0.0,
        )

        validation_errors = self.validator.validate(order)
        if validation_errors:
            reason = "; ".join(validation_errors)
            logger.warning("Order validation failed", symbol=decision.symbol, errors=reason)
            self._audit_log(decision, success=False, rejected_reason=reason)
            return ExecutionResult(
                success=False,
                rejected_reason=reason,
                message="Order validation failed",
            )

        risk_result = self.risk_engine.validate_order(order)
        if not risk_result.passed:
            logger.warning("Risk check failed", symbol=decision.symbol, reason=risk_result.reason)
            self._audit_log(decision, success=False, rejected_reason=risk_result.reason)
            return ExecutionResult(
                success=False,
                rejected_reason=risk_result.reason,
                message="Risk check failed",
            )

        rate_ok, rate_reason = self.rate_limiter.check(decision.symbol)
        if not rate_ok:
            logger.warning("Rate limit exceeded", symbol=decision.symbol, reason=rate_reason)
            self._audit_log(decision, success=False, rejected_reason=rate_reason)
            return ExecutionResult(
                success=False,
                rejected_reason=rate_reason,
                message="Rate limit exceeded",
            )

        self._audit_log(decision, success=False, reason="Order submitted to Freqtrade")

        try:
            amount = 0.001
            result = await self.freqtrade_client.create_order(
                symbol=decision.symbol,
                action=decision.action,
                amount=amount,
            )

            order_id = result.get("order_id", result.get("id", ""))

            self.rate_limiter.record(decision.symbol)
            self.validator.record_order(order)

            self._audit_log(
                decision,
                success=True,
                order_id=order_id,
                reason="Order executed successfully",
            )

            logger.info(
                "Order executed",
                symbol=decision.symbol,
                action=decision.action,
                order_id=order_id,
            )

            return ExecutionResult(
                success=True,
                order_id=order_id,
                message="Order executed successfully",
            )

        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "Order execution failed",
                symbol=decision.symbol,
                error=error_msg,
            )
            self._audit_log(
                decision,
                success=False,
                rejected_reason=error_msg,
            )
            return ExecutionResult(
                success=False,
                rejected_reason=error_msg,
                message="Order execution failed",
            )

    async def _handle_approval(self, decision: Decision) -> bool:
        """Handle human-in-the-loop approval flow.

        Creates an approval request and waits for user response.
        In dry-run mode, auto-approves.

        Args:
            decision: The trading decision to approve.

        Returns:
            True if approved, False if rejected or expired.
        """
        if self.dry_run and self.approval_manager.auto_approve_dry_run:
            logger.info(
                "auto_approved_dry_run",
                symbol=decision.symbol,
                action=decision.action,
            )
            return True

        sources = list(set(s.source for s in decision.signals))
        request = await self.approval_manager.create_request(
            symbol=decision.symbol,
            action=decision.action,
            score=decision.score,
            confidence=decision.confidence,
            reasoning_summary=decision.explanation,
            sources=sources,
            metadata={
                "signal_count": len(decision.signals),
                "explanation": decision.explanation,
            },
        )

        logger.info(
            "approval_request_sent",
            request_id=request.id,
            symbol=decision.symbol,
            action=decision.action,
        )

        # Wait for approval (with timeout)
        max_wait = self.approval_timeout
        waited = 0
        check_interval = 2

        while waited < max_wait:
            req = self.approval_manager.get_request(request.id)
            if req is None:
                break

            if req.status == ApprovalStatus.APPROVED:
                logger.info(
                    "approval_granted",
                    request_id=request.id,
                    symbol=decision.symbol,
                )
                return True

            if req.status == ApprovalStatus.REJECTED:
                logger.info(
                    "approval_rejected",
                    request_id=request.id,
                    symbol=decision.symbol,
                )
                return False

            if req.status == ApprovalStatus.EXPIRED:
                logger.info(
                    "approval_expired",
                    request_id=request.id,
                    symbol=decision.symbol,
                )
                return False

            await asyncio.sleep(check_interval)
            waited += check_interval

        # Timeout
        self.approval_manager.get_request(request.id)
        logger.warning(
            "approval_timeout",
            request_id=request.id,
            symbol=decision.symbol,
        )
        return False
