"""Abstract base class for all data sources in FKCrypto."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger()


class DataSource(ABC):
    """Abstract interface for market data sources.

    All concrete data sources must implement these methods.
    Supports both REST and WebSocket data retrieval.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._running = False

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candle data.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")
            timeframe: Candle interval (e.g. "1m", "5m", "1h", "4h", "1d")
            limit: Number of candles to return

        Returns:
            List of dicts with keys: timestamp, open, high, low, close, volume
        """

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch current ticker data for a symbol.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")

        Returns:
            Dict with keys: symbol, bid, ask, last, volume, high, low, timestamp
        """

    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        """Fetch order book snapshot.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")
            limit: Depth of order book

        Returns:
            Dict with keys: symbol, bids (list of [price, qty]), asks (list of [price, qty]), timestamp
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the data source is reachable and operational.

        Returns:
            True if the source is available, False otherwise.
        """

    async def start(self) -> None:
        """Initialize the data source connection."""
        self._running = True
        logger.info("data_source_started", source=self.__class__.__name__)

    async def stop(self) -> None:
        """Shutdown the data source connection."""
        self._running = False
        logger.info("data_source_stopped", source=self.__class__.__name__)
