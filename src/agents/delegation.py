"""Agent Delegation System — sync/async task delegation between agents.

Inspired by GoClaw's agent teams architecture. Allows agents to:
- Delegate tasks to other agents (sync: wait for result, async: continue)
- Track delegation permissions and concurrency limits
- Share context and results between agents
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class DelegationMode(str, Enum):
    SYNC = "sync"      # Wait for result before continuing
    ASYNC = "async"    # Continue, result announced later


class DelegationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PermissionDirection(str, Enum):
    OUTBOUND = "outbound"        # Can delegate TO other agents
    INBOUND = "inbound"          # Can receive delegations FROM other agents
    BIDIRECTIONAL = "bidirectional"


@dataclass
class DelegationResult:
    """Result of a delegated task."""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class DelegationRequest:
    """A task delegated from one agent to another."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: str = ""
    to_agent: str = ""
    task: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    mode: DelegationMode = DelegationMode.SYNC
    status: DelegationStatus = DelegationStatus.PENDING
    result: Optional[DelegationResult] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    priority: int = 0  # Higher = more urgent

    @property
    def duration_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds() * 1000
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task": self.task,
            "context": self.context,
            "mode": self.mode.value,
            "status": self.status.value,
            "result": self.result.to_dict() if self.result else None,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "priority": self.priority,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class PermissionLink:
    """Defines delegation permissions between two agents."""

    from_agent: str
    to_agent: str
    direction: PermissionDirection = PermissionDirection.BIDIRECTIONAL
    max_concurrent: int = 3  # Max concurrent delegations on this link
    allowed_tasks: list[str] = field(default_factory=list)  # Empty = all tasks

    def can_delegate(self, task: str, current_active: int) -> bool:
        """Check if delegation is allowed."""
        if current_active >= self.max_concurrent:
            return False
        if self.allowed_tasks and task not in self.allowed_tasks:
            return False
        return True


class DelegationManager:
    """Manages inter-agent delegation with permissions and concurrency control."""

    def __init__(self) -> None:
        self._permissions: dict[str, PermissionLink] = {}
        self._active: dict[str, DelegationRequest] = {}
        self._history: list[DelegationRequest] = []
        self._agent_concurrency: dict[str, int] = {}  # agent -> current active count
        self._max_per_agent: int = 5

    def add_permission(self, link: PermissionLink) -> None:
        """Add a delegation permission link."""
        key = f"{link.from_agent}:{link.to_agent}"
        self._permissions[key] = link
        logger.info(
            "delegation_permission_added",
            from_agent=link.from_agent,
            to_agent=link.to_agent,
            direction=link.direction.value,
        )

    def remove_permission(self, from_agent: str, to_agent: str) -> None:
        """Remove a delegation permission link."""
        key = f"{from_agent}:{to_agent}"
        self._permissions.pop(key, None)

    async def delegate(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        context: dict[str, Any] | None = None,
        mode: DelegationMode = DelegationMode.SYNC,
        executor: Any = None,
        timeout_sec: float = 60.0,
        priority: int = 0,
    ) -> DelegationResult:
        """Delegate a task to another agent.

        Args:
            from_agent: Source agent name.
            to_agent: Target agent name.
            task: Task description.
            context: Additional context data.
            mode: Sync (wait) or async (fire and forget).
            executor: Callable to execute the task.
            timeout_sec: Max wait time for sync mode.
            priority: Task priority (higher = more urgent).

        Returns:
            DelegationResult with outcome.
        """
        # Check permissions
        key = f"{from_agent}:{to_agent}"
        link = self._permissions.get(key)
        if not link:
            return DelegationResult(
                success=False,
                error=f"No delegation permission from {from_agent} to {to_agent}",
            )

        active_count = self._agent_concurrency.get(to_agent, 0)
        if not link.can_delegate(task, active_count):
            return DelegationResult(
                success=False,
                error=f"Delegation limit reached for {to_agent} ({active_count}/{link.max_concurrent})",
            )

        # Create request
        request = DelegationRequest(
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            context=context or {},
            mode=mode,
            priority=priority,
        )

        self._active[request.id] = request
        self._history.append(request)
        self._agent_concurrency[to_agent] = active_count + 1
        request.status = DelegationStatus.IN_PROGRESS

        logger.info(
            "delegation_started",
            delegation_id=request.id,
            from_agent=from_agent,
            to_agent=to_agent,
            task=task,
            mode=mode.value,
        )

        # Execute
        start_time = datetime.now(timezone.utc)
        try:
            if executor:
                if inspect.iscoroutinefunction(executor):
                    result_data = await asyncio.wait_for(
                        executor(task, context),
                        timeout=timeout_sec,
                    )
                else:
                    result_data = executor(task, context)
            else:
                result_data = {"message": "No executor provided"}

            request.status = DelegationStatus.COMPLETED
            request.result = DelegationResult(
                success=True,
                data=result_data if isinstance(result_data, dict) else {"result": result_data},
                duration_ms=request.duration_ms,
            )
            request.completed_at = datetime.now(timezone.utc)

            logger.info(
                "delegation_completed",
                delegation_id=request.id,
                duration_ms=request.duration_ms,
            )

            return request.result

        except asyncio.TimeoutError:
            request.status = DelegationStatus.FAILED
            request.result = DelegationResult(
                success=False,
                error=f"Delegation timed out after {timeout_sec}s",
                duration_ms=request.duration_ms,
            )
            request.completed_at = datetime.now(timezone.utc)

            logger.warning(
                "delegation_timeout",
                delegation_id=request.id,
                timeout=timeout_sec,
            )
            return request.result

        except Exception as exc:
            request.status = DelegationStatus.FAILED
            request.result = DelegationResult(
                success=False,
                error=str(exc),
                duration_ms=request.duration_ms,
            )
            request.completed_at = datetime.now(timezone.utc)

            logger.error(
                "delegation_failed",
                delegation_id=request.id,
                error=str(exc),
            )
            return request.result

        finally:
            # Release concurrency slot
            self._active.pop(request.id, None)
            self._agent_concurrency[to_agent] = max(
                0, self._agent_concurrency.get(to_agent, 0) - 1,
            )

    def get_active_delegations(self, agent: str = "") -> list[DelegationRequest]:
        """Get currently active delegations."""
        delegations = list(self._active.values())
        if agent:
            delegations = [
                d for d in delegations
                if d.from_agent == agent or d.to_agent == agent
            ]
        return delegations

    def get_history(self, limit: int = 50) -> list[DelegationRequest]:
        """Get delegation history."""
        return sorted(self._history, key=lambda d: d.created_at, reverse=True)[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get delegation statistics."""
        completed = sum(1 for d in self._history if d.status == DelegationStatus.COMPLETED)
        failed = sum(1 for d in self._history if d.status == DelegationStatus.FAILED)
        active = len(self._active)

        return {
            "total_delegations": len(self._history),
            "completed": completed,
            "failed": failed,
            "active": active,
            "success_rate": round(completed / len(self._history), 4) if self._history else 0.0,
            "permissions": len(self._permissions),
        }
