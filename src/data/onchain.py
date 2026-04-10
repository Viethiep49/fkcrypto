"""On-chain data source for FKCrypto AlphaSeeker."""

import random
from typing import Any
import structlog

logger = structlog.get_logger()


class OnChainDataSource:
    """Mock on-chain data provider.

    Simulates fetching on-chain metrics like exchange net flow,
    large transactions, active addresses, etc. In production,
    this would connect to APIs like Glassnode, CryptoQuant, or Dune.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    async def get_exchange_netflow(self, token: str) -> dict[str, Any]:
        """Fetch exchange netflow (deposits minus withdrawals).

        Positive netflow indicates more tokens entering exchanges (Bearish).
        Negative netflow indicates tokens leaving exchanges (Bullish).
        """
        # For simulation, return a random netflow
        # Values outside +/- 10M are considered significant signals
        netflow_usd = random.uniform(-50000000, 50000000)
        
        signal = "neutral"
        if netflow_usd < -20000000:
            signal = "strong_bullish"
        elif netflow_usd < -10000000:
            signal = "bullish"
        elif netflow_usd > 20000000:
            signal = "strong_bearish"
        elif netflow_usd > 10000000:
            signal = "bearish"

        logger.debug(
            "onchain_netflow_fetched", 
            token=token, 
            netflow_usd=netflow_usd,
            signal=signal
        )

        return {
            "token": token,
            "netflow_usd": netflow_usd,
            "signal": signal,
        }
