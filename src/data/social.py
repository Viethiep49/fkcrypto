"""Social sentiment data source for FKCrypto — LunarCrush integration."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


class SocialSource:
    """Social media sentiment and volume data source.

    Fetches social metrics from LunarCrush API including
    social volume, sentiment scores, and engagement metrics.
    """

    BASE_URL = "https://api.lunarcrush.com/v4"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        lc_config = config.get("lunarcrush", {})
        self.api_key = lc_config.get("api_key", "")
        self.base_url = lc_config.get("base_url", self.BASE_URL)
        self._client: httpx.AsyncClient | None = None

    def _get_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=30.0,
            )
        return self._client

    async def get_social_volume(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> dict[str, Any]:
        """Fetch social media volume metrics for a symbol.

        Args:
            symbol: Cryptocurrency symbol (e.g. "BTC", "ETH").
            interval: Time interval for aggregation.

        Returns:
            Dict with social volume metrics.
        """
        if not self.api_key:
            logger.warning("lunarcrush_api_key_not_configured")
            return {
                "symbol": symbol,
                "social_volume": 0,
                "social_dominance": 0.0,
                "social_score": 0.0,
                "mentions": 0,
                "followers": 0,
                "interval": interval,
            }

        client = await self._get_client()
        try:
            response = await client.get(
                "/data/posts",
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "type": "posts",
                },
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("lunarcrush_volume_fetch_failed", symbol=symbol, error=str(exc))
            return {
                "symbol": symbol,
                "social_volume": 0,
                "social_dominance": 0.0,
                "social_score": 0.0,
                "mentions": 0,
                "followers": 0,
                "interval": interval,
            }

        post_data = data.get("data", [])
        if not post_data:
            return {
                "symbol": symbol,
                "social_volume": 0,
                "social_dominance": 0.0,
                "social_score": 0.0,
                "mentions": 0,
                "followers": 0,
                "interval": interval,
            }

        latest = post_data[0]
        result = {
            "symbol": symbol,
            "social_volume": latest.get("posts", 0),
            "social_dominance": latest.get("social_dominance", 0.0),
            "social_score": latest.get("social_score", 0.0),
            "mentions": latest.get("mentions", 0),
            "followers": latest.get("followers", 0),
            "interval": interval,
            "timestamp": latest.get("time", 0),
        }

        logger.info("lunarcrush_volume_fetched", symbol=symbol, volume=result["social_volume"])
        return result

    async def get_sentiment(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> dict[str, Any]:
        """Fetch social sentiment metrics for a symbol.

        Args:
            symbol: Cryptocurrency symbol (e.g. "BTC", "ETH").
            interval: Time interval for aggregation.

        Returns:
            Dict with sentiment metrics including bullish/bearish ratios.
        """
        if not self.api_key:
            logger.warning("lunarcrush_api_key_not_configured")
            return {
                "symbol": symbol,
                "sentiment": 0.0,
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "neutral_pct": 0.0,
                "interval": interval,
            }

        client = await self._get_client()
        try:
            response = await client.get(
                "/data/posts",
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "type": "sentiment",
                },
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("lunarcrush_sentiment_fetch_failed", symbol=symbol, error=str(exc))
            return {
                "symbol": symbol,
                "sentiment": 0.0,
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "neutral_pct": 0.0,
                "interval": interval,
            }

        post_data = data.get("data", [])
        if not post_data:
            return {
                "symbol": symbol,
                "sentiment": 0.0,
                "bullish_pct": 50.0,
                "bearish_pct": 50.0,
                "neutral_pct": 0.0,
                "interval": interval,
            }

        latest = post_data[0]
        bullish = latest.get("bullish", 0)
        bearish = latest.get("bearish", 0)
        total = bullish + bearish

        if total > 0:
            bullish_pct = (bullish / total) * 100
            bearish_pct = (bearish / total) * 100
            sentiment = (bullish - bearish) / total
        else:
            bullish_pct = 50.0
            bearish_pct = 50.0
            sentiment = 0.0

        result = {
            "symbol": symbol,
            "sentiment": round(sentiment, 4),
            "bullish_pct": round(bullish_pct, 2),
            "bearish_pct": round(bearish_pct, 2),
            "neutral_pct": round(max(0, 100 - bullish_pct - bearish_pct), 2),
            "social_score": latest.get("social_score", 0.0),
            "interval": interval,
            "timestamp": latest.get("time", 0),
        }

        logger.info(
            "lunarcrush_sentiment_fetched",
            symbol=symbol,
            sentiment=result["sentiment"],
        )
        return result

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
