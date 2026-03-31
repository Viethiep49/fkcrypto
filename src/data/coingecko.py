"""CoinGecko market data source for FKCrypto."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from src.data.base import DataSource

logger = structlog.get_logger()


class CoinGeckoSource(DataSource):
    """Market data source using CoinGecko API.

    Provides market data, trending coins, and global market stats.
    """

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        cg_config = config.get("coingecko", {})
        self.api_key = cg_config.get("api_key", "")
        self.base_url = cg_config.get("base_url", self.BASE_URL)
        self._client: httpx.AsyncClient | None = None

    def _get_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["x-cg-demo-key"] = self.api_key
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=30.0,
            )
        return self._client

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("CoinGecko does not provide OHLCV data. Use CCXTSource instead.")

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("CoinGecko does not provide real-time tickers. Use get_market_data instead.")

    async def get_orderbook(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        raise NotImplementedError("CoinGecko does not provide orderbook data. Use CCXTSource instead.")

    async def get_market_data(self, coin_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetch market data for specified coins.

        Args:
            coin_ids: List of CoinGecko coin IDs (e.g. ["bitcoin", "ethereum"]).
                      If None, fetches top coins by market cap.

        Returns:
            List of dicts with market data per coin.
        """
        client = await self._get_client()

        if coin_ids:
            ids_param = ",".join(coin_ids)
            params = {
                "ids": ids_param,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            }
            response = await client.get("/coins/markets", params=params)
        else:
            params = {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 50,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            }
            response = await client.get("/coins/markets", params=params)

        response.raise_for_status()
        data = response.json()

        results = []
        for item in data:
            results.append({
                "id": item.get("id"),
                "symbol": item.get("symbol", "").upper(),
                "name": item.get("name"),
                "current_price_usd": item.get("current_price"),
                "market_cap_usd": item.get("market_cap"),
                "market_cap_rank": item.get("market_cap_rank"),
                "volume_24h_usd": item.get("total_volume"),
                "price_change_24h_pct": item.get("price_change_percentage_24h"),
                "ath_usd": item.get("ath"),
                "ath_date": item.get("ath_date"),
                "last_updated": item.get("last_updated"),
            })

        logger.info("coingecko_market_data_fetched", count=len(results))
        return results

    async def get_trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch trending coins on CoinGecko.

        Args:
            limit: Maximum number of trending coins to return.

        Returns:
            List of dicts with trending coin data.
        """
        client = await self._get_client()
        response = await client.get("/search/trending")
        response.raise_for_status()
        data = response.json()

        coins = data.get("coins", [])[:limit]
        results = []
        for item in coins:
            coin_data = item.get("item", {})
            results.append({
                "id": coin_data.get("id"),
                "symbol": coin_data.get("symbol", "").upper(),
                "name": coin_data.get("name"),
                "market_cap_rank": coin_data.get("market_cap_rank"),
                "price_btc": coin_data.get("price_btc"),
                "score": coin_data.get("score"),
            })

        logger.info("coingecko_trending_fetched", count=len(results))
        return results

    async def get_global_data(self) -> dict[str, Any]:
        """Fetch global cryptocurrency market data.

        Returns:
            Dict with global market statistics.
        """
        client = await self._get_client()
        response = await client.get("/global")
        response.raise_for_status()
        data = response.json().get("data", {})

        result = {
            "total_market_cap_usd": data.get("total_market_cap", {}).get("usd"),
            "total_volume_24h_usd": data.get("total_volume", {}).get("usd"),
            "btc_dominance_pct": data.get("market_cap_percentage", {}).get("btc"),
            "eth_dominance_pct": data.get("market_cap_percentage", {}).get("eth"),
            "active_cryptocurrencies": data.get("active_cryptocurrencies"),
            "markets": data.get("markets"),
            "market_cap_change_24h_pct": data.get("market_cap_change_percentage_24h_usd"),
            "last_updated": data.get("updated_at"),
        }

        logger.info("coingecko_global_data_fetched")
        return result

    async def is_available(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/ping")
            return response.status_code == 200
        except Exception as exc:
            logger.warning("coingecko_availability_check_failed", error=str(exc))
            return False

    async def stop(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        await super().stop()
