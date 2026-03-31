"""Redis-backed pub/sub message bus."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
import structlog

from src.bus.message import Message

logger = structlog.get_logger(__name__)


class RedisMessageBus:
    """Async message bus backed by Redis pub/sub.

    Provides connect, publish, subscribe, and listen operations
    with automatic reconnection using exponential backoff.
    """

    _MAX_BACKOFF = 30.0
    _BASE_BACKOFF = 1.0

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._running = False

    async def connect(self) -> None:
        """Establish the Redis connection and initialise the pub/sub client."""
        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            retry_on_timeout=True,
        )
        await self._redis.ping()
        self._pubsub = self._redis.pubsub()
        self._running = True
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info("redis_bus_connected", url=self._redis_url)

    async def publish(self, message: Message) -> None:
        """Publish a message to the channel matching its topic."""
        if self._redis is None:
            raise RuntimeError("Bus not connected. Call connect() first.")
        await self._redis.publish(message.topic, message.to_json())
        logger.debug(
            "message_published",
            topic=message.topic,
            source=message.source,
            correlation_id=message.correlation_id,
        )

    async def subscribe(self, topic: str) -> None:
        """Subscribe to a topic channel."""
        if self._pubsub is None:
            raise RuntimeError("Bus not connected. Call connect() first.")
        await self._pubsub.subscribe(topic)
        logger.info("subscribed_to_topic", topic=topic)

    async def listen(self, topic: str) -> AsyncGenerator[Message, None]:
        """Yield incoming messages for the given topic.

        Runs until the bus is closed or the generator is cancelled.
        """
        if self._pubsub is None:
            raise RuntimeError("Bus not connected. Call connect() first.")

        while self._running:
            try:
                raw = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw is None:
                    continue
                if raw.get("channel") != topic:
                    continue
                msg = Message.from_json(raw["data"])
                logger.debug(
                    "message_received",
                    topic=topic,
                    source=msg.source,
                    correlation_id=msg.correlation_id,
                )
                yield msg
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("error_processing_message", topic=topic)
                await asyncio.sleep(0.5)

    async def close(self) -> None:
        """Close the Redis connection and cancel the reconnect loop."""
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("redis_bus_closed")

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect with exponential backoff on connection loss."""
        backoff = self._BASE_BACKOFF
        while self._running:
            try:
                await asyncio.sleep(backoff)
                if self._redis is None:
                    continue
                await self._redis.ping()
                backoff = self._BASE_BACKOFF
            except Exception:
                logger.warning(
                    "redis_reconnect_attempt",
                    backoff=backoff,
                )
                backoff = min(backoff * 2, self._MAX_BACKOFF)
                try:
                    self._redis = aioredis.from_url(
                        self._redis_url,
                        decode_responses=True,
                        retry_on_timeout=True,
                    )
                    self._pubsub = self._redis.pubsub()
                    await self._redis.ping()
                    logger.info("redis_reconnected")
                    backoff = self._BASE_BACKOFF
                except Exception:
                    logger.exception("redis_reconnect_failed")
