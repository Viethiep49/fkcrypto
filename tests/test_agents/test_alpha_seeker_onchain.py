"""Tests for AlphaSeeker on-chain data integration."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from src.agents.alpha_seeker import AlphaSeekerAgent
from src.data.onchain import OnChainDataSource


@pytest.fixture
def alpha_config():
    return {
        "alpha_seeker": {
            "check_interval_sec": 1,
            "sources": {
                "exchange_news": {"enabled": False},
                "whale_alert": {"enabled": False},
                "influencer": {"enabled": False},
                "onchain": {"enabled": True},
            },
        },
        "pairs": ["BTC/USDT", "ETH/USDT"],
        "news_source": AsyncMock(),
        "onchain_source": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_alpha_seeker_onchain_bullish(alpha_config):
    """Test that a negative netflow generates a bullish signal."""
    # Mock the onchain source to return strong negative netflow (withdrawn = bullish)
    mock_onchain = AsyncMock()
    mock_onchain.get_exchange_netflow.side_effect = lambda token: {
        "token": token,
        "netflow_usd": -30000000,
        "signal": "strong_bullish",
    }
    alpha_config["onchain_source"] = mock_onchain

    agent = AlphaSeekerAgent(config=alpha_config)
    signals = await agent.run()

    # Should be 2 signals (BTC, ETH)
    assert len(signals) == 2
    
    btc_signal = next(s for s in signals if s.symbol == "BTC/USDT")
    assert btc_signal.action == "buy"
    assert btc_signal.metadata["event_type"] == "onchain_netflow"
    
    # Check reasoning
    factors = btc_signal.reasoning.factors
    onchain_factor = next(f for f in factors if f.type == "onchain")
    assert onchain_factor.impact > 0
    assert onchain_factor.metadata["netflow_usd"] == -30000000


@pytest.mark.asyncio
async def test_alpha_seeker_onchain_bearish(alpha_config):
    """Test that a positive netflow generates a bearish signal."""
    # Mock the onchain source to return strong positive netflow (deposited = bearish)
    mock_onchain = AsyncMock()
    mock_onchain.get_exchange_netflow.side_effect = lambda token: {
        "token": token,
        "netflow_usd": 40000000,
        "signal": "strong_bearish",
    }
    alpha_config["onchain_source"] = mock_onchain

    agent = AlphaSeekerAgent(config=alpha_config)
    signals = await agent.run()

    assert len(signals) == 2
    
    eth_signal = next(s for s in signals if s.symbol == "ETH/USDT")
    assert eth_signal.action == "sell"
    assert eth_signal.metadata["event_type"] == "onchain_netflow"
    
    # Check reasoning
    factors = eth_signal.reasoning.factors
    onchain_factor = next(f for f in factors if f.type == "onchain")
    assert onchain_factor.impact < 0
    assert onchain_factor.metadata["netflow_usd"] == 40000000
