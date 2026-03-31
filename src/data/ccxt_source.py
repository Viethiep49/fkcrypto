"""CCXT exchange data source for FKCrypto."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import ccxt
import ccxt.async_support as ccxt_async
import structlog

from src.data.base import DataSource

logger = structlog.get_logger()


class CCXTSource(DataSource):
    """Exchange data source using CCXT library.

    Supports multiple exchanges via configuration.
    Provides OHLCV, ticker, orderbook, and recent trades data.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        ccxt_config = config.get("ccxt", {})
        self.exchange_name = ccxt_config.get("exchange", "binance")
        self.api_key = ccxt_config.get("api_key", "")
        self.secret = ccxt_config.get("secret", "")
        self.options = ccxt_config.get("options", {})
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 1.0)
        self._exchange: ccxt_async.Exchange | None = None
        self._ws_task: asyncio.Task | None = None

    def _get_exchange_config(self) -> dict[str, Any]:
        config = {
            "enableRateLimit": True,
            "options": self.options,
        }
        if self.api_key and self.secret:
            config["apiKey"] = self.api_key
            config["secret"] = self.secret
        return config

    async def _get_exchange(self) -> ccxt_async.Exchange:
        if self._exchange is None:
            exchange_class = getattr(ccxt_async, self.exchange_name, None)
            if exchange_class is None:
                raise ValueError(f"Unsupported exchange: {self.exchange_name}")
            self._exchange = exchange_class(self._get_exchange_config())
            logger.info("ccxt_exchange_initialized", exchange=self.exchange_name)
        return self._exchange

    async def _retry(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except ccxt.NetworkError as exc:
                last_error = exc
                logger.warning(
                    "ccxt_network_error",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
            except ccxt.ExchangeError as exc:
                last_error = exc
                logger.warning(
                    "ccxt_exchange_error",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
            except Exception as exc:
                logger.error("ccxt_unexpected_error", error=str(exc))
                raise
        raise RuntimeError(f"CCXT call failed after {self.max_retries} retries: {last_error}")

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        exchange = await self._get_exchange()

        async def _fetch():
            raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return [
                {
                    "timestamp": candle[0],
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                }
                for candle in raw
            ]

        result = await self._retry(_fetch)
        logger.debug("ohlcv_fetched", symbol=symbol, timeframe=timeframe, count=len(result))
        return result

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        exchange = await self._get_exchange()

        async def _fetch():
            raw = await exchange.fetch_ticker(symbol)
            return {
                "symbol": raw.get("symbol", symbol),
                "bid": float(raw["bid"]) if raw.get("bid") is not None else None,
                "ask": float(raw["ask"]) if raw.get("ask") is not None else None,
                "last": float(raw["last"]) if raw.get("last") is not None else None,
                "volume": float(raw.get("baseVolume", 0)),
                "high": float(raw["high"]) if raw.get("high") is not None else None,
                "low": float(raw["low"]) if raw.get("low") is not None else None,
                "timestamp": raw.get("timestamp", int(time.time() * 1000)),
            }

        result = await self._retry(_fetch)
        logger.debug("ticker_fetched", symbol=symbol, last=result.get("last"))
        return result

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        exchange = await self._get_exchange()

        async def _fetch():
            raw = await exchange.fetch_order_book(symbol, limit=limit)
            return {
                "symbol": symbol,
                "bids": [[float(p), float(q)] for p, q in raw.get("bids", [])],
                "asks": [[float(p), float(q)] for p, q in raw.get("asks", [])],
                "timestamp": raw.get("timestamp", int(time.time() * 1000)),
            }

        result = await self._retry(_fetch)
        logger.debug(
            "orderbook_fetched",
            symbol=symbol,
            bid_depth=len(result["bids"]),
            ask_depth=len(result["asks"]),
        )
        return result

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        exchange = await self._get_exchange()

        async def _fetch():
            raw = await exchange.fetch_trades(symbol, limit=limit)
            return [
                {
                    "id": str(t.get("id", "")),
                    "timestamp": t.get("timestamp"),
                    "price": float(t["price"]),
                    "amount": float(t.get("amount", 0)),
                    "side": t.get("side", "unknown"),
                }
                for t in raw
            ]

        result = await self._retry(_fetch)
        logger.debug("trades_fetched", symbol=symbol, count=len(result))
        return result

    async def start_ws(self) -> None:
        """Start WebSocket stream for real-time data (stub).

        Full WebSocket support requires exchange-specific implementation.
        This stub logs intent and can be extended per exchange.
        """
        if self._running:
            return
        self._running = True
        logger.info(
            "ccxt_ws_started",
            exchange=self.exchange_name,
            note="WebSocket support is a stub — use REST polling for production",
        )

    async def stop_ws(self) -> None:
        """Stop WebSocket stream."""
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        logger.info("ccxt_ws_stopped", exchange=self.exchange_name)

    async def is_available(self) -> bool:
        try:
            exchange = await self._get_exchange()
            await exchange.load_markets()
            return True
        except Exception as exc:
            logger.warning("ccxt_availability_check_failed", error=str(exc))
            return False

    async def stop(self) -> None:
        await self.stop_ws()
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:
                pass
            self._exchange = None
        await super().stop()
