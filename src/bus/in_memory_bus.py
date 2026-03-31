"""In-memory pub/sub message bus — fallback when Redis is unavailable."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import structlog

from src.bus.message import Message

logger = structlog.get_logger(__name__)


class InMemoryBus:
    """Async message bus backed by in-memory queues.

    Drop-in replacement for RedisMessageBus when no Redis instance
    is available. Uses one asyncio.Queue per topic.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Message]] = {}
        self._running = False

    async def connect(self) -> None:
        """Initialise the bus (no-op for in-memory implementation)."""
        self._running = True
        logger.info("in_memory_bus_connected")

    async def publish(self, message: Message) -> None:
        """Put a message onto the queue for its topic."""
        queue = self._queues.get(message.topic)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[message.topic] = queue
        await queue.put(message)
        logger.debug(
            "message_published",
            topic=message.topic,
            source=message.source,
            correlation_id=message.correlation_id,
        )

    async def subscribe(self, topic: str) -> None:
        """Ensure a queue exists for the topic."""
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        logger.info("subscribed_to_topic", topic=topic)

    async def listen(self, topic: str) -> AsyncGenerator[Message, None]:
        """Yield incoming messages for the given topic.

        Runs until the bus is closed or the generator is cancelled.
        """
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        queue = self._queues[topic]

        while self._running:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                logger.debug(
                    "message_received",
                    topic=topic,
                    source=msg.source,
                    correlation_id=msg.correlation_id,
                )
                yield msg
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("error_processing_message", topic=topic)
                await asyncio.sleep(0.5)

    async def close(self) -> None:
        """Stop the bus and drain all queues."""
        self._running = False
        for topic, queue in self._queues.items():
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self._queues.clear()
        logger.info("in_memory_bus_closed")
