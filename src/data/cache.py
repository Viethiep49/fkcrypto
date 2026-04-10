"""Redis caching layer for market data."""

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()


class MarketDataCache:
    """Redis-based cache for market data (OHLCV, ticker)."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self.redis_url = redis_url
        self._redis: aioredis.Redis | None = None
        self._connected = False

    async def connect(self) -> None:
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
                await self._redis.ping()
                self._connected = True
                logger.info("market_data_cache_connected", url=self.redis_url)
            except Exception as exc:
                self._connected = False
                logger.warning("market_data_cache_connection_failed", error=str(exc))

    async def get(self, key: str) -> Any | None:
        if not self._connected or self._redis is None:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception as exc:
            logger.debug("market_data_cache_get_error", key=key, error=str(exc))
        return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        """Set a value in the cache with a TTL (Time To Live) in seconds."""
        if not self._connected or self._redis is None:
            return
        try:
            await self._redis.setex(key, ttl, json.dumps(value))
        except Exception as exc:
            logger.debug("market_data_cache_set_error", key=key, error=str(exc))

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
            self._connected = False
            logger.info("market_data_cache_closed")
