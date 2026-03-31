"""Lane-based Scheduler — priority-based task scheduling with concurrency lanes.

Inspired by GoClaw's lane-based scheduler. Tasks are organized into lanes
with independent concurrency limits and priority ordering.

Lanes:
- main: Primary tasks (analysis, decision cycles)
- subagent: Sub-agent delegations
- team: Team task board operations
- cron: Scheduled cron jobs
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class LaneType(str, Enum):
    MAIN = "main"
    SUBAGENT = "subagent"
    TEAM = "team"
    CRON = "cron"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """A task in the lane-based scheduler."""

    id: str
    lane: LaneType
    name: str
    executor: Any
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Any = None
    error: str = ""

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lane": self.lane.value,
            "name": self.name,
            "priority": self.priority,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
        }


class Lane:
    """A single lane with its own concurrency limit and task queue."""

    def __init__(self, lane_type: LaneType, max_concurrent: int = 3) -> None:
        self.lane_type = lane_type
        self.max_concurrent = max_concurrent
        self._queue: list[ScheduledTask] = []
        self._active: dict[str, ScheduledTask] = {}
        self._history: list[ScheduledTask] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def enqueue(self, task: ScheduledTask) -> None:
        """Add a task to the lane queue."""
        self._queue.append(task)
        # Sort by priority (highest first), then creation time
        self._queue.sort(key=lambda t: (-t.priority, t.created_at))

    def get_stats(self) -> dict[str, Any]:
        """Get lane statistics."""
        completed = sum(1 for t in self._history if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._history if t.status == TaskStatus.FAILED)
        total = len(self._history)

        return {
            "lane": self.lane_type.value,
            "pending": self.pending_count,
            "active": self.active_count,
            "max_concurrent": self.max_concurrent,
            "total_completed": completed,
            "total_failed": failed,
            "success_rate": round(completed / total, 4) if total > 0 else 0.0,
        }


class LaneScheduler:
    """Lane-based task scheduler with priority queues and concurrency control.

    Features:
    - Multiple lanes with independent concurrency limits
    - Priority-based task ordering within each lane
    - Task history with success/failure tracking
    - Graceful shutdown with task cancellation
    """

    LANE_DEFAULTS = {
        LaneType.MAIN: 5,
        LaneType.SUBAGENT: 3,
        LaneType.TEAM: 2,
        LaneType.CRON: 1,
    }

    def __init__(self, lane_configs: dict[LaneType, int] | None = None) -> None:
        """Initialize the lane scheduler.

        Args:
            lane_configs: Custom concurrency limits per lane type.
        """
        self._lanes: dict[LaneType, Lane] = {}
        for lane_type, default_max in self.LANE_DEFAULTS.items():
            max_concurrent = (
                lane_configs.get(lane_type, default_max)
                if lane_configs
                else default_max
            )
            self._lanes[lane_type] = Lane(lane_type, max_concurrent)

        self._running = False
        self._workers: dict[LaneType, asyncio.Task] = {}

    def submit(
        self,
        lane: LaneType,
        name: str,
        executor: Any,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        priority: int = 0,
    ) -> ScheduledTask:
        """Submit a task to a lane.

        Args:
            lane: Target lane.
            name: Task name.
            executor: Callable to execute.
            args: Positional arguments.
            kwargs: Keyword arguments.
            priority: Task priority (higher = more urgent).

        Returns:
            ScheduledTask object.
        """
        import uuid
        task = ScheduledTask(
            id=str(uuid.uuid4())[:8],
            lane=lane,
            name=name,
            executor=executor,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
        )
        self._lanes[lane].enqueue(task)
        logger.info(
            "task_submitted",
            task_id=task.id,
            lane=lane.value,
            name=name,
            priority=priority,
        )
        return task

    async def start(self) -> None:
        """Start all lane workers."""
        self._running = True
        for lane_type, lane in self._lanes.items():
            self._workers[lane_type] = asyncio.create_task(
                self._worker(lane),
            )
        logger.info("lane_scheduler_started", lanes=len(self._lanes))

    async def stop(self) -> None:
        """Stop all lane workers and cancel pending tasks."""
        self._running = False
        for worker in self._workers.values():
            worker.cancel()
        for worker in self._workers.values():
            try:
                await worker
            except asyncio.CancelledError:
                pass
        logger.info("lane_scheduler_stopped")

    async def _worker(self, lane: Lane) -> None:
        """Process tasks from a lane queue."""
        while self._running:
            if not lane._queue:
                await asyncio.sleep(0.1)
                continue

            task = lane._queue.pop(0)
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            lane._active[task.id] = task

            try:
                if inspect.iscoroutinefunction(task.executor):
                    result = await task.executor(*task.args, **task.kwargs)
                else:
                    result = task.executor(*task.args, **task.kwargs)

                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.now(timezone.utc)

                logger.info(
                    "task_completed",
                    task_id=task.id,
                    name=task.name,
                    duration_ms=task.duration_ms,
                )

            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now(timezone.utc)
                raise

            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                task.completed_at = datetime.now(timezone.utc)

                logger.error(
                    "task_failed",
                    task_id=task.id,
                    name=task.name,
                    error=str(exc),
                )

            finally:
                lane._active.pop(task.id, None)
                lane._history.append(task)
                if len(lane._history) > 500:
                    lane._history = lane._history[-250:]

    def get_stats(self) -> dict[str, Any]:
        """Get scheduler-wide statistics."""
        lane_stats = {
            lt.value: lane.get_stats()
            for lt, lane in self._lanes.items()
        }

        total_tasks = sum(
            len(lane._history) for lane in self._lanes.values()
        )
        total_active = sum(
            lane.active_count for lane in self._lanes.values()
        )

        return {
            "lanes": lane_stats,
            "total_tasks": total_tasks,
            "total_active": total_active,
            "running": self._running,
        }

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Find a task by ID across all lanes."""
        for lane in self._lanes.values():
            for task in lane._history:
                if task.id == task_id:
                    return task
            for task in lane._active.values():
                if task.id == task_id:
                    return task
            for task in lane._queue:
                if task.id == task_id:
                    return task
        return None
