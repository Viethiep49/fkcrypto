"""Prometheus metrics registry for FKCrypto trading system."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import structlog
from prometheus_client import Counter, Gauge, Histogram

logger = structlog.get_logger(__name__)


class MetricsRegistry:
    """Central registry for all Prometheus metrics.

    Creates and holds metric objects, providing convenience methods
    for recording trading system events.
    """

    def __init__(self) -> None:
        self.signals_total = Counter(
            "signals_total",
            "Total signals emitted per agent",
            ["agent_name", "source"],
        )
        self.decisions_total = Counter(
            "decisions_total",
            "Total decisions made",
            ["action", "symbol"],
        )
        self.orders_executed = Counter(
            "orders_executed",
            "Total orders sent to Freqtrade",
            ["symbol"],
        )
        self.orders_rejected = Counter(
            "orders_rejected",
            "Total orders rejected by Risk Engine",
            ["symbol", "reason"],
        )
        self.portfolio_value = Gauge(
            "portfolio_value",
            "Current portfolio value in USD",
        )
        self.drawdown_pct = Gauge(
            "drawdown_pct",
            "Current drawdown percentage",
        )
        self.agent_latency_ms = Histogram(
            "agent_latency_ms",
            "Agent execution time in milliseconds",
            ["agent_name"],
            buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
        )
        self.llm_calls_total = Counter(
            "llm_calls_total",
            "Total LLM API calls",
        )
        self.llm_errors_total = Counter(
            "llm_errors_total",
            "Total LLM API errors",
        )

    def record_signal(self, agent_name: str, source: str) -> None:
        """Record a signal emitted by an agent.

        Args:
            agent_name: Name of the agent that emitted the signal.
            source: Source of the signal (e.g. 'technical', 'sentiment').
        """
        self.signals_total.labels(agent_name=agent_name, source=source).inc()
        logger.debug("signal_recorded", agent_name=agent_name, source=source)

    def record_decision(self, action: str, symbol: str) -> None:
        """Record a trading decision.

        Args:
            action: Decision action (buy/sell/hold).
            symbol: Trading pair symbol.
        """
        self.decisions_total.labels(action=action, symbol=symbol).inc()
        logger.debug("decision_recorded", action=action, symbol=symbol)

    def record_order_executed(self, symbol: str) -> None:
        """Record an order sent to Freqtrade.

        Args:
            symbol: Trading pair symbol.
        """
        self.orders_executed.labels(symbol=symbol).inc()
        logger.debug("order_executed", symbol=symbol)

    def record_order_rejected(self, symbol: str, reason: str) -> None:
        """Record an order rejected by the Risk Engine.

        Args:
            symbol: Trading pair symbol.
            reason: Reason for rejection.
        """
        self.orders_rejected.labels(symbol=symbol, reason=reason).inc()
        logger.debug("order_rejected", symbol=symbol, reason=reason)

    def set_portfolio_value(self, value: float) -> None:
        """Set the current portfolio value.

        Args:
            value: Portfolio value in USD.
        """
        self.portfolio_value.set(value)

    def set_drawdown(self, pct: float) -> None:
        """Set the current drawdown percentage.

        Args:
            pct: Drawdown as a percentage (e.g. 5.0 for 5%).
        """
        self.drawdown_pct.set(pct)

    def observe_agent_latency(self, agent_name: str, duration_ms: float) -> None:
        """Record agent execution latency.

        Args:
            agent_name: Name of the agent.
            duration_ms: Execution duration in milliseconds.
        """
        self.agent_latency_ms.labels(agent_name=agent_name).observe(duration_ms)

    def record_llm_call(self) -> None:
        """Record an LLM API call."""
        self.llm_calls_total.inc()

    def record_llm_error(self) -> None:
        """Record an LLM API error."""
        self.llm_errors_total.inc()
        logger.warning("llm_error_recorded")

    @contextmanager
    def agent_timer(self, agent_name: str) -> Iterator[None]:
        """Context manager that automatically records agent execution latency.

        Usage:
            with registry.agent_timer("analyst"):
                await agent.run()

        Args:
            agent_name: Name of the agent being timed.
        """
        start = time.monotonic()
        try:
            yield
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            self.observe_agent_latency(agent_name, duration_ms)
