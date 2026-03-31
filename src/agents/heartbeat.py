"""Agent Heartbeat System — periodic health checks with checklists.

Inspired by GoClaw's heartbeat system. Agents periodically check in
with health status, and can suppress notifications when everything is OK.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class HeartbeatCheck:
    """A single heartbeat check result."""

    name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HeartbeatReport:
    """Complete heartbeat report from an agent."""

    agent: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    checks: list[HeartbeatCheck] = field(default_factory=list)
    healthy: bool = True
    summary: str = ""
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Compute healthy status from checks."""
        if self.checks:
            self.healthy = all(c.passed for c in self.checks)

    def add_check(self, check: HeartbeatCheck) -> None:
        """Add a health check result."""
        self.checks.append(check)
        if not check.passed:
            self.healthy = False

    @property
    def check_count(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "timestamp": self.timestamp.isoformat(),
            "healthy": self.healthy,
            "summary": self.summary,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message}
                for c in self.checks
            ],
            "passed_count": self.passed_count,
            "check_count": self.check_count,
            "metrics": self.metrics,
        }


@dataclass
class HeartbeatConfig:
    """Configuration for the heartbeat system."""

    interval_sec: int = 60
    suppress_on_ok: bool = True  # Don't log/notify when healthy
    active_hours: tuple[int, int] = (0, 24)  # 24/7 by default
    max_consecutive_failures: int = 3
    retry_delay_sec: int = 10


class HeartbeatManager:
    """Manages agent heartbeats with health checklists.

    Features:
    - Periodic agent check-ins
    - Configurable health checklists per agent
    - Suppress-on-OK mode (only alert on failures)
    - Active hours (only check during certain times)
    - Consecutive failure tracking
    """

    def __init__(self, config: HeartbeatConfig | None = None) -> None:
        self.config = config or HeartbeatConfig()
        self._checklists: dict[str, list[str]] = {}
        self._history: list[HeartbeatReport] = []
        self._consecutive_failures: dict[str, int] = {}
        self._last_heartbeat: dict[str, datetime] = {}
        self._task: Optional[asyncio.Task] = None
        self._callbacks: list[Any] = []  # Async callbacks for alerts

    def register_agent(self, agent: str, checks: list[str]) -> None:
        """Register an agent with its health checklist.

        Args:
            agent: Agent name.
            checks: List of check names (e.g., ["api_connection", "data_freshness"]).
        """
        self._checklists[agent] = checks
        self._consecutive_failures[agent] = 0
        logger.info(
            "agent_registered_heartbeat",
            agent=agent,
            checks=checks,
        )

    def add_alert_callback(self, callback: Any) -> None:
        """Add a callback for heartbeat failure alerts."""
        self._callbacks.append(callback)

    def _is_active_hours(self) -> bool:
        """Check if current time is within active hours."""
        start, end = self.config.active_hours
        current_hour = datetime.now(timezone.utc).hour
        if start <= end:
            return start <= current_hour < end
        # Overnight range (e.g., 22:00 to 06:00)
        return current_hour >= start or current_hour < end

    async def run_check(
        self,
        agent: str,
        check_name: str,
        check_fn: Any,
    ) -> HeartbeatCheck:
        """Run a single health check.

        Args:
            agent: Agent name.
            check_name: Check identifier.
            check_fn: Async callable that returns (passed, message, details).

        Returns:
            HeartbeatCheck result.
        """
        try:
            if inspect.iscoroutinefunction(check_fn):
                passed, message, details = await check_fn()
            else:
                passed, message, details = check_fn()

            return HeartbeatCheck(
                name=check_name,
                passed=bool(passed),
                message=str(message),
                details=details if isinstance(details, dict) else {},
            )
        except Exception as exc:
            return HeartbeatCheck(
                name=check_name,
                passed=False,
                message=f"Check failed: {exc}",
            )

    async def generate_report(
        self,
        agent: str,
        check_results: list[HeartbeatCheck],
        metrics: dict[str, float] | None = None,
    ) -> HeartbeatReport:
        """Generate a heartbeat report from check results.

        Args:
            agent: Agent name.
            check_results: List of completed health checks.
            metrics: Optional performance metrics.

        Returns:
            HeartbeatReport with aggregated status.
        """
        report = HeartbeatReport(
            agent=agent,
            checks=check_results,
            metrics=metrics or {},
        )

        passed = report.passed_count
        total = report.check_count

        if report.healthy:
            report.summary = f"All {total} checks passed"
            self._consecutive_failures[agent] = 0
        else:
            failed = total - passed
            report.summary = f"{failed}/{total} checks failed"
            self._consecutive_failures[agent] = self._consecutive_failures.get(agent, 0) + 1

        self._history.append(report)
        self._last_heartbeat[agent] = report.timestamp

        # Keep history bounded
        if len(self._history) > 1000:
            self._history = self._history[-500:]

        # Alert on failure
        if not report.healthy:
            consecutive = self._consecutive_failures.get(agent, 0)
            logger.warning(
                "heartbeat_failure",
                agent=agent,
                summary=report.summary,
                consecutive_failures=consecutive,
            )

            # Trigger callbacks
            for callback in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(report)
                    else:
                        callback(report)
                except Exception as exc:
                    logger.error("heartbeat_callback_failed", error=str(exc))

            # Check if max consecutive failures reached
            if consecutive >= self.config.max_consecutive_failures:
                logger.critical(
                    "heartbeat_max_failures",
                    agent=agent,
                    consecutive=consecutive,
                )
        elif not self.config.suppress_on_ok:
            logger.info(
                "heartbeat_ok",
                agent=agent,
                summary=report.summary,
            )

        return report

    def get_agent_status(self, agent: str) -> dict[str, Any]:
        """Get current status of an agent.

        Args:
            agent: Agent name.

        Returns:
            Status dict with health info.
        """
        last = self._last_heartbeat.get(agent)
        consecutive = self._consecutive_failures.get(agent, 0)

        # Check if heartbeat is stale (2x interval)
        is_stale = False
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            is_stale = elapsed > self.config.interval_sec * 2

        return {
            "agent": agent,
            "healthy": consecutive == 0,
            "last_heartbeat": last.isoformat() if last else None,
            "consecutive_failures": consecutive,
            "is_stale": is_stale,
            "checks_registered": len(self._checklists.get(agent, [])),
        }

    def get_all_status(self) -> dict[str, Any]:
        """Get status of all registered agents."""
        return {
            agent: self.get_agent_status(agent)
            for agent in self._checklists
        }

    def get_history(self, agent: str = "", limit: int = 20) -> list[HeartbeatReport]:
        """Get heartbeat history."""
        reports = self._history
        if agent:
            reports = [r for r in reports if r.agent == agent]
        return sorted(reports, key=lambda r: r.timestamp, reverse=True)[:limit]
