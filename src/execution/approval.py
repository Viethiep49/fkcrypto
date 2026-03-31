"""Approval Request — Human-in-the-loop order approval system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A request for human approval of a trading decision.

    Sent to the user via Telegram or Dashboard before execution.
    """

    id: str
    symbol: str
    action: str
    score: float
    confidence: float
    size_usd: float
    reasoning_summary: str = ""
    sources: list[str] = field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    responded_at: datetime | None = None
    responder: str = ""
    timeout_sec: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if the request has timed out."""
        elapsed = (datetime.now(UTC) - self.created_at).total_seconds()
        return elapsed > self.timeout_sec

    @property
    def is_active(self) -> bool:
        """Check if the request is still pending and not expired."""
        return self.status == ApprovalStatus.PENDING and not self.is_expired

    def approve(self, responder: str = "user") -> None:
        """Mark the request as approved."""
        self.status = ApprovalStatus.APPROVED
        self.responded_at = datetime.now(UTC)
        self.responder = responder
        logger.info(
            "approval_granted",
            request_id=self.id,
            symbol=self.symbol,
            action=self.action,
            responder=responder,
        )

    def reject(self, responder: str = "user", reason: str = "") -> None:
        """Mark the request as rejected."""
        self.status = ApprovalStatus.REJECTED
        self.responded_at = datetime.now(UTC)
        self.responder = responder
        self.metadata["rejection_reason"] = reason
        logger.info(
            "approval_rejected",
            request_id=self.id,
            symbol=self.symbol,
            responder=responder,
            reason=reason,
        )

    def expire(self) -> None:
        """Mark the request as expired due to timeout."""
        self.status = ApprovalStatus.EXPIRED
        self.responded_at = datetime.now(UTC)
        logger.info(
            "approval_expired",
            request_id=self.id,
            symbol=self.symbol,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "action": self.action,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "size_usd": round(self.size_usd, 2),
            "reasoning_summary": self.reasoning_summary,
            "sources": self.sources,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
            "responder": self.responder,
            "timeout_sec": self.timeout_sec,
            "is_expired": self.is_expired,
            "metadata": self.metadata,
        }


class ApprovalManager:
    """Manages the lifecycle of approval requests.

    When human-in-the-loop mode is enabled, decisions are converted to
    ApprovalRequests and held until the user approves or rejects them.
    """

    def __init__(
        self,
        enabled: bool = True,
        timeout_sec: int = 300,
        auto_approve_dry_run: bool = True,
    ) -> None:
        self.enabled = enabled
        self.timeout_sec = timeout_sec
        self.auto_approve_dry_run = auto_approve_dry_run

        self._pending: dict[str, ApprovalRequest] = {}
        self._history: list[ApprovalRequest] = []

    async def create_request(
        self,
        symbol: str,
        action: str,
        score: float,
        confidence: float,
        size_usd: float = 0.0,
        reasoning_summary: str = "",
        sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            action: Trade action ("buy" or "sell").
            score: Decision score (-1.0 to 1.0).
            confidence: Decision confidence (0.0 to 1.0).
            size_usd: Proposed position size in USD.
            reasoning_summary: Human-readable reasoning summary.
            sources: List of signal sources that contributed.
            metadata: Additional context data.

        Returns:
            ApprovalRequest object.
        """
        import uuid

        request = ApprovalRequest(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            action=action,
            score=score,
            confidence=confidence,
            size_usd=size_usd,
            reasoning_summary=reasoning_summary,
            sources=sources or [],
            timeout_sec=self.timeout_sec,
            metadata=metadata or {},
        )

        self._pending[request.id] = request
        self._history.append(request)

        logger.info(
            "approval_request_created",
            request_id=request.id,
            symbol=symbol,
            action=action,
        )

        return request

    async def approve(self, request_id: str, responder: str = "user") -> ApprovalRequest | None:
        """Approve a pending request.

        Args:
            request_id: ID of the approval request.
            responder: Who approved it.

        Returns:
            The approved request, or None if not found.
        """
        request = self._pending.get(request_id)
        if not request:
            logger.warning("approval_request_not_found", request_id=request_id)
            return None

        if not request.is_active:
            logger.warning(
                "approval_request_not_active",
                request_id=request_id,
                status=request.status.value,
            )
            return None

        request.approve(responder)
        del self._pending[request_id]
        return request

    async def reject(
        self,
        request_id: str,
        responder: str = "user",
        reason: str = "",
    ) -> ApprovalRequest | None:
        """Reject a pending request.

        Args:
            request_id: ID of the approval request.
            responder: Who rejected it.
            reason: Optional rejection reason.

        Returns:
            The rejected request, or None if not found.
        """
        request = self._pending.get(request_id)
        if not request:
            logger.warning("approval_request_not_found", request_id=request_id)
            return None

        if not request.is_active:
            logger.warning(
                "approval_request_not_active",
                request_id=request_id,
                status=request.status.value,
            )
            return None

        request.reject(responder, reason)
        del self._pending[request_id]
        return request

    async def check_expired(self) -> list[ApprovalRequest]:
        """Check and expire any timed-out requests.

        Returns:
            List of newly expired requests.
        """
        expired: list[ApprovalRequest] = []
        to_remove: list[str] = []

        for request_id, request in self._pending.items():
            if request.is_expired:
                request.expire()
                expired.append(request)
                to_remove.append(request_id)

        for request_id in to_remove:
            del self._pending[request_id]

        return expired

    def get_pending(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        return list(self._pending.values())

    def get_history(self, limit: int = 50) -> list[ApprovalRequest]:
        """Get recent approval request history."""
        return sorted(self._history, key=lambda r: r.created_at, reverse=True)[:limit]

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get a specific request by ID."""
        return self._pending.get(request_id) or next(
            (r for r in self._history if r.id == request_id), None
        )
