"""News data sources for FKCrypto — CryptoPanic and SerpAPI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class NewsSource:
    """Aggregated news data source.

    Fetches crypto news from CryptoPanic and general financial news via SerpAPI.
    Returns normalized news items with metadata.
    """

    CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        cp_config = config.get("cryptopanic", {})
        serp_config = config.get("serpapi", {})
        self.cryptopanic_api_key = cp_config.get("api_key", "")
        self.cryptopanic_base = cp_config.get("base_url", self.CRYPTOPANIC_BASE)
        self.serpapi_api_key = serp_config.get("api_key", "")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def get_crypto_news(
        self,
        currencies: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch crypto news from CryptoPanic.

        Args:
            currencies: List of currency codes to filter (e.g. ["BTC", "ETH"]).
                        If None, fetches general crypto news.
            limit: Maximum number of articles to return.

        Returns:
            List of dicts with keys: title, url, source, published_at, sentiment, currencies
        """
        if not self.cryptopanic_api_key:
            logger.warning("cryptopanic_api_key_not_configured")
            return []

        client = await self._get_client()
        params = {
            "auth_token": self.cryptopanic_api_key,
            "public": "true",
            "limit": min(limit, 100),
        }

        if currencies:
            params["currencies"] = ",".join(c.upper() for c in currencies)

        try:
            response = await client.get(f"{self.cryptopanic_base}/posts/", params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("cryptopanic_fetch_failed", error=str(exc))
            return []

        results = []
        for post in data.get("results", []):
            sentiment_map = {
                "bullish": 0.8,
                "bearish": -0.8,
                "neutral": 0.0,
            }
            raw_sentiment = post.get("sentiment", "")
            sentiment = sentiment_map.get(raw_sentiment, 0.0)

            published = post.get("published_at")
            if published:
                try:
                    published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    published_dt = datetime.now(timezone.utc)
            else:
                published_dt = datetime.now(timezone.utc)

            results.append({
                "title": post.get("title", ""),
                "url": post.get("url", ""),
                "source": post.get("source", {}).get("title", "Unknown") if post.get("source") else "Unknown",
                "published_at": published_dt.isoformat(),
                "sentiment": sentiment,
                "currencies": [c.get("code", "") for c in post.get("currencies", [])],
            })

            if len(results) >= limit:
                break

        logger.info("cryptopanic_news_fetched", count=len(results))
        return results

    async def search_news(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search financial news via SerpAPI.

        Args:
            query: Search query (e.g. "Bitcoin price prediction 2026").
            limit: Maximum number of results to return.

        Returns:
            List of dicts with keys: title, url, source, published_at, sentiment, snippet
        """
        if not self.serpapi_api_key:
            logger.warning("serpapi_api_key_not_configured")
            return []

        client = await self._get_client()
        params = {
            "api_key": self.serpapi_api_key,
            "engine": "google_news",
            "q": query,
            "num": min(limit, 50),
            "hl": "en",
        }

        try:
            response = await client.get("https://serpapi.com/search", params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("serpapi_search_failed", error=str(exc))
            return []

        results = []
        news_items = data.get("news_results", [])
        for item in news_items:
            published = item.get("date", "")
            published_dt = datetime.now(timezone.utc)
            if published:
                try:
                    published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "source": item.get("source", "Unknown"),
                "published_at": published_dt.isoformat(),
                "sentiment": 0.0,
                "snippet": item.get("snippet", ""),
            })

            if len(results) >= limit:
                break

        logger.info("serpapi_news_fetched", query=query, count=len(results))
        return results

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
