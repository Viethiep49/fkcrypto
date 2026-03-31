"""Tests for lane-based scheduler."""

from __future__ import annotations

import asyncio

import pytest

from src.agents.scheduler import LaneScheduler, LaneType, TaskStatus


class TestLaneScheduler:
    """Test lane-based task scheduling."""

    @pytest.mark.asyncio
    async def test_submit_and_process_task(self) -> None:
        scheduler = LaneScheduler()
        await scheduler.start()

        def simple_task(x: int) -> int:
            return x * 2

        task = scheduler.submit(
            LaneType.MAIN,
            "double",
            simple_task,
            args=(5,),
            priority=1,
        )

        # Wait for processing
        await asyncio.sleep(0.3)
        await scheduler.stop()

        assert task.status == TaskStatus.COMPLETED
        assert task.result == 10

    @pytest.mark.asyncio
    async def test_async_task(self) -> None:
        scheduler = LaneScheduler()
        await scheduler.start()

        async def async_task() -> str:
            await asyncio.sleep(0.05)
            return "async_done"

        task = scheduler.submit(
            LaneType.SUBAGENT,
            "async_work",
            async_task,
        )

        await asyncio.sleep(0.3)
        await scheduler.stop()

        assert task.status == TaskStatus.COMPLETED
        assert task.result == "async_done"

    @pytest.mark.asyncio
    async def test_failed_task(self) -> None:
        scheduler = LaneScheduler()
        await scheduler.start()

        def failing_task() -> None:
            raise ValueError("intentional failure")

        task = scheduler.submit(
            LaneType.MAIN,
            "fail",
            failing_task,
        )

        await asyncio.sleep(0.3)
        await scheduler.stop()

        assert task.status == TaskStatus.FAILED
        assert "intentional failure" in task.error

    @pytest.mark.asyncio
    async def test_priority_ordering(self) -> None:
        scheduler = LaneScheduler({LaneType.MAIN: 1})
        await scheduler.start()

        results: list[int] = []

        def make_task(val: int):
            def task() -> None:
                results.append(val)
            return task

        # Submit in reverse priority order
        scheduler.submit(LaneType.MAIN, "low", make_task(1), priority=1)
        scheduler.submit(LaneType.MAIN, "high", make_task(3), priority=3)
        scheduler.submit(LaneType.MAIN, "medium", make_task(2), priority=2)

        await asyncio.sleep(0.3)
        await scheduler.stop()

        # High priority should be processed first
        assert results[0] == 3

    def test_get_stats(self) -> None:
        scheduler = LaneScheduler()
        stats = scheduler.get_stats()
        assert "lanes" in stats
        assert "total_tasks" in stats
        assert stats["total_active"] == 0

    def test_get_task(self) -> None:
        scheduler = LaneScheduler()
        task = scheduler.submit(
            LaneType.MAIN,
            "test",
            lambda: None,
        )
        found = scheduler.get_task(task.id)
        assert found is not None
        assert found.id == task.id

    def test_get_task_not_found(self) -> None:
        scheduler = LaneScheduler()
        assert scheduler.get_task("nonexistent") is None
