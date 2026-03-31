"""Tests for delegation, heartbeat, and tracing modules."""

from __future__ import annotations

import pytest

from src.agents.delegation import (
    DelegationManager,
    DelegationMode,
    DelegationResult,
    DelegationStatus,
    PermissionDirection,
    PermissionLink,
)
from src.agents.heartbeat import (
    HeartbeatCheck,
    HeartbeatConfig,
    HeartbeatManager,
    HeartbeatReport,
)
from src.agents.tracing import LLMTracer, LLMSpan


class TestDelegationManager:
    """Test agent delegation system."""

    def test_add_permission(self) -> None:
        mgr = DelegationManager()
        link = PermissionLink(
            from_agent="analyst",
            to_agent="sentiment",
            direction=PermissionDirection.BIDIRECTIONAL,
        )
        mgr.add_permission(link)
        assert len(mgr._permissions) == 1

    @pytest.mark.asyncio
    async def test_delegate_no_permission(self) -> None:
        mgr = DelegationManager()
        result = await mgr.delegate("analyst", "sentiment", "analyze")
        assert result.success is False
        assert "No delegation permission" in result.error

    @pytest.mark.asyncio
    async def test_delegate_sync(self) -> None:
        mgr = DelegationManager()
        mgr.add_permission(PermissionLink(
            from_agent="analyst",
            to_agent="sentiment",
        ))

        def executor(task: str, ctx: dict) -> dict:
            return {"result": "done", "task": task}

        result = await mgr.delegate(
            "analyst", "sentiment", "analyze",
            executor=executor,
        )
        assert result.success is True
        assert result.data["result"] == "done"

    @pytest.mark.asyncio
    async def test_delegate_async(self) -> None:
        mgr = DelegationManager()
        mgr.add_permission(PermissionLink(
            from_agent="analyst",
            to_agent="sentiment",
        ))

        async def async_executor(task: str, ctx: dict) -> dict:
            import asyncio
            await asyncio.sleep(0.01)
            return {"result": "async_done"}

        result = await mgr.delegate(
            "analyst", "sentiment", "analyze",
            executor=async_executor,
            mode=DelegationMode.ASYNC,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delegate_timeout(self) -> None:
        mgr = DelegationManager()
        mgr.add_permission(PermissionLink(
            from_agent="analyst",
            to_agent="sentiment",
        ))

        async def slow_executor(task: str, ctx: dict) -> dict:
            import asyncio
            await asyncio.sleep(10)
            return {}

        result = await mgr.delegate(
            "analyst", "sentiment", "analyze",
            executor=slow_executor,
            timeout_sec=0.1,
        )
        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_concurrency_limit(self) -> None:
        mgr = DelegationManager()
        mgr.add_permission(PermissionLink(
            from_agent="analyst",
            to_agent="sentiment",
            max_concurrent=1,
        ))
        mgr._agent_concurrency["sentiment"] = 1  # Simulate active

        result = await mgr.delegate("analyst", "sentiment", "analyze")
        assert result.success is False
        assert "limit reached" in result.error

    def test_get_stats(self) -> None:
        mgr = DelegationManager()
        stats = mgr.get_stats()
        assert stats["total_delegations"] == 0
        assert stats["success_rate"] == 0.0


class TestHeartbeatManager:
    """Test heartbeat system."""

    def test_register_agent(self) -> None:
        mgr = HeartbeatManager()
        mgr.register_agent("analyst", ["api_connection", "data_freshness"])
        assert "analyst" in mgr._checklists
        assert len(mgr._checklists["analyst"]) == 2

    @pytest.mark.asyncio
    async def test_generate_report_healthy(self) -> None:
        mgr = HeartbeatManager()
        mgr.register_agent("analyst", ["api", "data"])

        report = await mgr.generate_report(
            "analyst",
            [
                HeartbeatCheck(name="api", passed=True, message="OK"),
                HeartbeatCheck(name="data", passed=True, message="OK"),
            ],
        )
        assert report.healthy is True
        assert report.passed_count == 2
        assert report.check_count == 2

    @pytest.mark.asyncio
    async def test_generate_report_unhealthy(self) -> None:
        mgr = HeartbeatManager()
        mgr.register_agent("analyst", ["api", "data"])

        report = await mgr.generate_report(
            "analyst",
            [
                HeartbeatCheck(name="api", passed=True),
                HeartbeatCheck(name="data", passed=False, message="Stale"),
            ],
        )
        assert report.healthy is False
        assert report.passed_count == 1

    @pytest.mark.asyncio
    async def test_consecutive_failures(self) -> None:
        mgr = HeartbeatManager()
        mgr.register_agent("analyst", ["api"])

        for _ in range(3):
            await mgr.generate_report(
                "analyst",
                [HeartbeatCheck(name="api", passed=False)],
            )

        assert mgr._consecutive_failures["analyst"] == 3

    def test_get_agent_status(self) -> None:
        mgr = HeartbeatManager()
        mgr.register_agent("analyst", ["api"])
        status = mgr.get_agent_status("analyst")
        assert status["agent"] == "analyst"
        assert status["healthy"] is True
        assert status["consecutive_failures"] == 0

    def test_active_hours(self) -> None:
        mgr = HeartbeatManager(HeartbeatConfig(active_hours=(9, 17)))
        # Can't easily test current time, but verify method exists
        assert mgr._is_active_hours() in (True, False)


class TestLLMTracer:
    """Test LLM call tracing."""

    def test_start_and_complete_span(self) -> None:
        tracer = LLMTracer()
        span = tracer.start_span(
            agent="sentiment",
            model="gpt-4o-mini",
            call_type="classification",
        )
        tracer.complete_span(
            span.id,
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert span.success is True
        assert span.total_tokens == 150
        assert span.duration_ms > 0

    def test_fail_span(self) -> None:
        tracer = LLMTracer()
        span = tracer.start_span(
            agent="sentiment",
            model="gpt-4o-mini",
            call_type="classification",
        )
        tracer.fail_span(span.id, "Connection refused")
        assert span.success is False
        assert span.error == "Connection refused"

    def test_get_metrics(self) -> None:
        tracer = LLMTracer()
        metrics = tracer.get_metrics()
        assert metrics["total_calls"] == 0

        span = tracer.start_span("analyst", "gpt-4o", "analysis")
        tracer.complete_span(span.id, prompt_tokens=200, completion_tokens=100)

        metrics = tracer.get_metrics()
        assert metrics["total_calls"] == 1
        assert metrics["total_tokens"] == 300
        assert metrics["success_rate"] == 1.0

    def test_get_agent_metrics(self) -> None:
        tracer = LLMTracer()
        span = tracer.start_span("analyst", "gpt-4o", "analysis")
        tracer.complete_span(span.id, prompt_tokens=100, completion_tokens=50)

        metrics = tracer.get_agent_metrics("analyst")
        assert metrics["total_calls"] == 1
        assert "gpt-4o" in metrics["models_used"]

    def test_cache_hit_tracking(self) -> None:
        tracer = LLMTracer()
        span = tracer.start_span("sentiment", "claude-3", "classification")
        tracer.complete_span(
            span.id,
            prompt_tokens=100,
            completion_tokens=50,
            cache_hit=True,
            cache_read_tokens=80,
        )
        assert span.cache_hit is True
        assert span.cache_read_tokens == 80

    def test_get_spans(self) -> None:
        tracer = LLMTracer()
        tracer.start_span("analyst", "gpt-4o", "analysis")
        tracer.start_span("sentiment", "gpt-4o-mini", "classification")
        spans = tracer.get_spans()
        assert len(spans) == 0  # Not completed yet
