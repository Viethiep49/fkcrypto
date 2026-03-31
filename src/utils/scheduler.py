"""Scheduler utilities for FKCrypto trading system."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


class TaskScheduler:
    """Async task scheduler with cron-like scheduling.

    Lightweight alternative to APScheduler for asyncio environments.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def schedule_interval(
        self,
        func: Callable,
        seconds: int,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a coroutine to run at fixed intervals."""
        task = asyncio.create_task(
            self._interval_loop(func, seconds, *args, **kwargs)
        )
        self._tasks.append(task)
        logger.info(
            "task_scheduled",
            type="interval",
            interval_sec=seconds,
            func=func.__name__,
        )

    def schedule_cron(
        self,
        func: Callable,
        minute: str = "*",
        hour: str = "*",
        day: str = "*",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a coroutine with cron-like syntax.

        Supports: *, N, */N, N-M syntax.
        """
        task = asyncio.create_task(
            self._cron_loop(func, minute, hour, day, *args, **kwargs)
        )
        self._tasks.append(task)
        logger.info(
            "task_scheduled",
            type="cron",
            schedule=f"{minute} {hour} {day}",
            func=func.__name__,
        )

    async def _interval_loop(
        self,
        func: Callable,
        seconds: int,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Run func every N seconds."""
        while self._running:
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "scheduled_task_failed",
                    func=func.__name__,
                    error=str(exc),
                )

            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                break

    async def _cron_loop(
        self,
        func: Callable,
        minute: str,
        hour: str,
        day: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Run func matching cron schedule."""
        while self._running:
            now = datetime.now(timezone.utc)

            if self._match(now.minute, minute) and \
               self._match(now.hour, hour) and \
               self._match(now.day, day):

                try:
                    if asyncio.iscoroutinefunction(func):
                        await func(*args, **kwargs)
                    else:
                        func(*args, **kwargs)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error(
                        "cron_task_failed",
                        func=func.__name__,
                        error=str(exc),
                    )

            await asyncio.sleep(30)  # Check every 30 seconds

    @staticmethod
    def _match(value: int, pattern: str) -> bool:
        """Check if a value matches a cron field pattern."""
        if pattern == "*":
            return True

        if pattern.startswith("*/"):
            step = int(pattern[2:])
            return value % step == 0

        if "-" in pattern:
            start, end = pattern.split("-", 1)
            return int(start) <= value <= int(end)

        return value == int(pattern)

    async def stop(self) -> None:
        """Stop all scheduled tasks."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tasks.clear()
        logger.info("all_scheduled_tasks_stopped")

    def start(self) -> None:
        """Mark scheduler as running."""
        self._running = True
        logger.info("scheduler_started")
