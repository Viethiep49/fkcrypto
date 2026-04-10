"""Tests for flash crash and kill switch simulation."""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock

from src.agents.risk_guardian import RiskGuardianAgent


@pytest.fixture
def risk_config():
    return {
        "risk_guardian": {
            "check_interval_sec": 1,  # Fast check for testing
            "limits": {
                "max_drawdown_pct": 0.15,
                "max_daily_loss_pct": 0.05,
            },
            "volatility": {
                "atr_spike_multiplier": 3.0,
            },
            "kill_switch": {
                "enabled": True,
            },
        },
        "pairs": ["BTC/USDT"],
        "data_source": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_flash_crash_triggers_kill_switch(risk_config):
    """Test that a 20% price drop triggers the kill switch via drawdown."""
    guardian = RiskGuardianAgent(config=risk_config)
    
    # 1. Normal market state (Peak portfolio value)
    initial_portfolio_value = 10000.0
    
    # Update portfolio peak tracking
    guardian.set_portfolio_value(initial_portfolio_value)
    assert guardian._portfolio_peak_value == 10000.0
    
    # 2. Flash Crash Simulation (Drop by 20% to 8000)
    crashed_portfolio_value = 8000.0
    
    # Run the checks during the crash
    signals = await guardian.run(portfolio_value=crashed_portfolio_value, positions=[])
    
    # 3. Verify Kill Switch is triggered
    assert guardian.is_kill_switch_active is True
    assert guardian.kill_switch_reason is not None
    assert "drawdown_exceeded" in guardian.kill_switch_reason
    
    # 4. Verify Emergency Signal is emitted
    assert len(signals) == 1
    emergency_signal = signals[0]
    assert emergency_signal.action == "sell"
    assert emergency_signal.metadata["emergency"] is True
    assert emergency_signal.metadata["event"] == "kill_switch"


@pytest.mark.asyncio
async def test_extreme_volatility_triggers_kill_switch(risk_config):
    """Test that extreme ATR spike triggers the kill switch."""
    # Setup mock data source to return normal candles then a massive spike
    mock_ds = AsyncMock()
    
    # Generate 50 candles. The first 49 have a normal range of 10.
    # The last candle has a massive range of 2005.
    candles = []
    for i in range(49):
        candles.append({
            "timestamp": i * 3600000,
            "open": 10000,
            "high": 10010,
            "low": 10000,
            "close": 10005,
            "volume": 100
        })
    # Flash crash candle
    candles.append({
        "timestamp": 49 * 3600000,
        "open": 10005,
        "high": 10005,
        "low": 8000,  # Huge drop
        "close": 8100,
        "volume": 50000
    })
    
    mock_ds.get_ohlcv.return_value = candles
    risk_config["data_source"] = mock_ds
    
    guardian = RiskGuardianAgent(config=risk_config)
    
    signals = await guardian.run(portfolio_value=10000.0, positions=[])
    
    assert guardian.is_kill_switch_active is True
    assert "extreme_volatility" in guardian.kill_switch_reason
    assert len(signals) == 2
    assert signals[1].metadata["emergency"] is True
