import pytest
from unittest.mock import AsyncMock, patch
from src.data.ccxt_source import CCXTSource

@pytest.fixture
def ccxt_config():
    return {
        "ccxt": {
            "exchange": "binance",
        },
        "redis_url": "redis://localhost:6379/0",
    }

@pytest.mark.asyncio
async def test_ccxt_source_caching(ccxt_config):
    source = CCXTSource(config=ccxt_config)
    
    # Mock cache methods
    source._cache.get = AsyncMock(return_value=None)
    source._cache.set = AsyncMock()
    
    # Mock ccxt exchange method
    mock_exchange = AsyncMock()
    mock_exchange.fetch_ohlcv.return_value = [
        [1600000000000, 10000, 10100, 9900, 10050, 1000]
    ]
    source._get_exchange = AsyncMock(return_value=mock_exchange)
    
    # First call - cache miss
    result1 = await source.get_ohlcv("BTC/USDT", "1h", 1)
    assert len(result1) == 1
    assert result1[0]["close"] == 10050.0
    
    # Verify cache get and set were called
    source._cache.get.assert_called_once_with("ohlcv:binance:BTC/USDT:1h:1")
    source._cache.set.assert_called_once()
    
    # Simulate cache hit for second call
    source._cache.get.return_value = result1
    source._cache.get.reset_mock()
    mock_exchange.fetch_ohlcv.reset_mock()
    
    result2 = await source.get_ohlcv("BTC/USDT", "1h", 1)
    
    # Verify we got the same result
    assert result1 == result2
    # Verify cache get was called again
    source._cache.get.assert_called_once_with("ohlcv:binance:BTC/USDT:1h:1")
    # Verify fetch_ohlcv was NOT called again
    mock_exchange.fetch_ohlcv.assert_not_called()
