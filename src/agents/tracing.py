"""LLM Call Tracing — built-in tracing for LLM calls with spans and metrics.

Inspired by GoClaw's observability features. Tracks:
- LLM call latency and token usage
- Prompt cache hit/miss metrics
- Per-agent and per-call-type breakdowns
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class LLMSpan:
    """A single LLM call span with timing and usage metrics."""

    id: str
    agent: str
    model: str
    call_type: str  # sentiment, explanation, classification, etc.
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit: bool = False
    cache_read_tokens: int = 0
    success: bool = True
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def complete(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit: bool = False,
        cache_read_tokens: int = 0,
    ) -> None:
        """Mark the span as completed."""
        self.end_time = datetime.now(timezone.utc)
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.cache_hit = cache_hit
        self.cache_read_tokens = cache_read_tokens

    def fail(self, error: str) -> None:
        """Mark the span as failed."""
        self.end_time = datetime.now(timezone.utc)
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000
        self.success = False
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent,
            "model": self.model,
            "call_type": self.call_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": round(self.duration_ms, 2),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit": self.cache_hit,
            "cache_read_tokens": self.cache_read_tokens,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


class LLMTracer:
    """Traces LLM calls with spans and aggregates metrics.

    Features:
    - Per-call span tracking with timing
    - Token usage aggregation
    - Cache hit/miss metrics
    - Per-agent and per-call-type breakdowns
    """

    def __init__(self, max_history: int = 1000) -> None:
        self.max_history = max_history
        self._spans: list[LLMSpan] = []
        self._active: dict[str, LLMSpan] = {}

    def start_span(
        self,
        agent: str,
        model: str,
        call_type: str,
        span_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LLMSpan:
        """Start a new LLM call span.

        Args:
            agent: Agent making the call.
            model: LLM model being used.
            call_type: Type of call (sentiment, explanation, etc.)
            span_id: Optional custom span ID.
            metadata: Additional context.

        Returns:
            Started LLMSpan.
        """
        import uuid
        sid = span_id or str(uuid.uuid4())[:8]
        span = LLMSpan(
            id=sid,
            agent=agent,
            model=model,
            call_type=call_type,
            start_time=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._active[sid] = span
        return span

    def complete_span(
        self,
        span_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_hit: bool = False,
        cache_read_tokens: int = 0,
    ) -> Optional[LLMSpan]:
        """Complete an active span.

        Args:
            span_id: ID of the span to complete.
            prompt_tokens: Number of prompt tokens used.
            completion_tokens: Number of completion tokens used.
            cache_hit: Whether the prompt cache was hit.
            cache_read_tokens: Number of cache-read tokens.

        Returns:
            Completed span, or None if not found.
        """
        span = self._active.pop(span_id, None)
        if not span:
            return None

        span.complete(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit=cache_hit,
            cache_read_tokens=cache_read_tokens,
        )

        self._spans.append(span)
        if len(self._spans) > self.max_history:
            self._spans = self._spans[-self.max_history // 2:]

        logger.info(
            "llm_call_traced",
            span_id=span_id,
            agent=span.agent,
            model=span.model,
            call_type=span.call_type,
            duration_ms=span.duration_ms,
            tokens=span.total_tokens,
            cache_hit=cache_hit,
        )

        return span

    def fail_span(self, span_id: str, error: str) -> Optional[LLMSpan]:
        """Mark a span as failed.

        Args:
            span_id: ID of the span to fail.
            error: Error message.

        Returns:
            Failed span, or None if not found.
        """
        span = self._active.pop(span_id, None)
        if not span:
            return None

        span.fail(error)
        self._spans.append(span)

        logger.warning(
            "llm_call_failed",
            span_id=span_id,
            agent=span.agent,
            error=error,
        )

        return span

    def get_metrics(self) -> dict[str, Any]:
        """Get aggregated LLM call metrics.

        Returns:
            Dict with total calls, avg latency, token usage, cache stats.
        """
        if not self._spans:
            return {
                "total_calls": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "total_tokens": 0,
                "cache_hit_rate": 0.0,
            }

        total = len(self._spans)
        success = sum(1 for s in self._spans if s.success)
        total_tokens = sum(s.total_tokens for s in self._spans)
        cache_hits = sum(1 for s in self._spans if s.cache_hit)
        avg_latency = sum(s.duration_ms for s in self._spans) / total if total > 0 else 0

        return {
            "total_calls": total,
            "success_rate": round(success / total, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "total_tokens": total_tokens,
            "cache_hit_rate": round(cache_hits / total, 4) if total > 0 else 0.0,
        }

    def get_agent_metrics(self, agent: str) -> dict[str, Any]:
        """Get metrics for a specific agent.

        Args:
            agent: Agent name.

        Returns:
            Agent-specific metrics.
        """
        agent_spans = [s for s in self._spans if s.agent == agent]
        if not agent_spans:
            return {"total_calls": 0}

        total = len(agent_spans)
        success = sum(1 for s in agent_spans if s.success)
        total_tokens = sum(s.total_tokens for s in agent_spans)
        avg_latency = sum(s.duration_ms for s in agent_spans) / total

        return {
            "agent": agent,
            "total_calls": total,
            "success_rate": round(success / total, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "total_tokens": total_tokens,
            "models_used": list(set(s.model for s in agent_spans)),
            "call_types": list(set(s.call_type for s in agent_spans)),
        }

    def get_spans(self, limit: int = 50, agent: str = "") -> list[LLMSpan]:
        """Get recent spans.

        Args:
            limit: Max number of spans to return.
            agent: Filter by agent name.

        Returns:
            List of recent spans, newest first.
        """
        spans = self._spans
        if agent:
            spans = [s for s in spans if s.agent == agent]
        return sorted(spans, key=lambda s: s.start_time, reverse=True)[:limit]
