"""Freqtrade REST API client — async HTTP client for Freqtrade bot interaction."""

from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


class FreqtradeClient:
    """Async HTTP client for the Freqtrade REST API.

    Handles authentication, retries, and error recovery.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "FreqtradeClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: API path (e.g. "/api/v1/ping").
            json: Optional JSON body.

        Returns:
            Parsed JSON response as dict.

        Raises:
            FreqtradeAPIError: On unrecoverable API errors.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(
                    method=method,
                    url=path,
                    json=json,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(
                        "Rate limited, retrying",
                        path=path,
                        attempt=attempt + 1,
                        retry_after=retry_after,
                    )
                    await httpx.AsyncClient().sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Request timed out",
                    path=path,
                    attempt=attempt + 1,
                )
                if attempt < self.max_retries - 1:
                    await httpx.AsyncClient().sleep(2 ** attempt)
                continue

            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.error(
                    "HTTP error",
                    path=path,
                    status=exc.response.status_code,
                    attempt=attempt + 1,
                )
                if exc.response.status_code >= 500 and attempt < self.max_retries - 1:
                    await httpx.AsyncClient().sleep(2 ** attempt)
                    continue
                raise FreqtradeAPIError(
                    f"HTTP {exc.response.status_code}: {exc.response.text}"
                ) from exc

            except httpx.RequestError as exc:
                last_error = exc
                logger.warning(
                    "Request error",
                    path=path,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self.max_retries - 1:
                    await httpx.AsyncClient().sleep(2 ** attempt)
                continue

        raise FreqtradeAPIError(
            f"Request failed after {self.max_retries} retries: {last_error}"
        ) from last_error

    async def ping(self) -> bool:
        """Health check — verify Freqtrade API is reachable.

        Returns:
            True if API is healthy.
        """
        try:
            result = await self._request("GET", "/api/v1/ping")
            return result.get("status") == "pong" or "pong" in str(result).lower()
        except Exception as exc:
            logger.error("Ping failed", error=str(exc))
            return False

    async def create_order(
        self,
        symbol: str,
        action: str,
        amount: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Place an order via Freqtrade.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            action: "buy" or "sell".
            amount: Order amount in base currency.
            price: Optional limit price.

        Returns:
            Order response dict with order_id and status.
        """
        payload: dict[str, Any] = {
            "pair": symbol,
            "ordertype": "limit" if price else "market",
            "stake_amount": "all",
        }

        if price:
            payload["price"] = price

        if action == "sell":
            payload["ordertype"] = "limit"
            payload["price"] = price if price else 0

        result = await self._request("POST", "/api/v1/open_trades", json=payload)
        logger.info("Order created", symbol=symbol, action=action, result=result)
        return result

    async def get_open_orders(self) -> list[dict[str, Any]]:
        """Get all open orders.

        Returns:
            List of open order dicts.
        """
        result = await self._request("GET", "/api/v1/open_trades")
        return result.get("trades", result if isinstance(result, list) else [])

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order.

        Args:
            order_id: ID of the order to cancel.

        Returns:
            Cancellation response dict.
        """
        result = await self._request("DELETE", f"/api/v1/trades/{order_id}")
        logger.info("Order cancelled", order_id=order_id)
        return result

    async def get_balance(self) -> dict[str, Any]:
        """Get account balance.

        Returns:
            Balance dict with currencies and totals.
        """
        result = await self._request("GET", "/api/v1/balance")
        return result

    async def get_performance(self) -> dict[str, Any]:
        """Get trading performance stats.

        Returns:
            Performance dict with profit, trades, etc.
        """
        result = await self._request("GET", "/api/v1/performance")
        return result

    async def force_entry(
        self,
        pair: str,
        price: Optional[float] = None,
        stake_amount: Optional[float] = None,
    ) -> dict[str, Any]:
        """Force a buy entry via Freqtrade.

        Args:
            pair: Trading pair (e.g. "BTC/USDT").
            price: Optional entry price.
            stake_amount: Optional stake amount in quote currency.

        Returns:
            Trade response dict.
        """
        payload: dict[str, Any] = {"pair": pair}

        if price is not None:
            payload["price"] = price
        if stake_amount is not None:
            payload["stake_amount"] = stake_amount

        result = await self._request("POST", "/api/v1/forceentry", json=payload)
        logger.info("Force entry executed", pair=pair, result=result)
        return result

    async def force_exit(self, trade_id: str) -> dict[str, Any]:
        """Force exit a trade via Freqtrade.

        Args:
            trade_id: ID of the trade to close.

        Returns:
            Exit response dict.
        """
        payload = {"tradeid": trade_id}
        result = await self._request("POST", "/api/v1/forceexit", json=payload)
        logger.info("Force exit executed", trade_id=trade_id, result=result)
        return result


class FreqtradeAPIError(Exception):
    """Raised when a Freqtrade API request fails after retries."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
