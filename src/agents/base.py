"""Base agent class for FKCrypto trading agents."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import structlog

from src.agents.signal import Signal

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base class for all trading agents.

    Provides common functionality:
    - Structured logging
    - Error handling wrapper
    - Signal emission helpers
    - Lifecycle management
    """

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self._running = False
        self._logger = logger.bind(agent=name)

    @abstractmethod
    async def run(self) -> list[Signal]:
        """Execute the agent's main logic and return emitted signals.

        Returns:
            List of Signal objects generated during this run cycle.
        """

    async def emit_signals(self, signals: list[Signal]) -> list[Signal]:
        """Default signal emission implementation.

        Validates and logs each signal before returning.
        Subclasses can override to add pub/sub, database writes, etc.

        Args:
            signals: List of Signal objects to emit.

        Returns:
            The validated list of signals.
        """
        validated: list[Signal] = []
        for signal in signals:
            try:
                # Signal validation happens in __post_init__
                self._logger.info(
                    "signal_emitted",
                    symbol=signal.symbol,
                    action=signal.action,
                    confidence=signal.confidence,
                    strength=signal.strength,
                    source=signal.source,
                )
                validated.append(signal)
            except (ValueError, TypeError) as exc:
                self._logger.warning(
                    "signal_validation_failed",
                    error=str(exc),
                    signal_data=str(signal),
                )
        return validated

    async def safe_run(self) -> list[Signal]:
        """Run the agent with error handling wrapper.

        Catches all exceptions to prevent crashing the system.
        Returns an empty list on failure.

        Returns:
            List of Signal objects, or empty list on error.
        """
        if not self._running:
            self._running = True
            self._logger.info("agent_started")

        try:
            signals = await self.run()
            return await self.emit_signals(signals)
        except asyncio.CancelledError:
            self._logger.info("agent_cancelled")
            self._running = False
            raise
        except Exception as exc:
            self._logger.error(
                "agent_run_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        self._running = False
        self._logger.info("agent_stopped")

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running."""
        return self._running
