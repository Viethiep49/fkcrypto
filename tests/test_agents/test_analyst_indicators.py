"""Tests for the Technical Analyst indicators."""

import pytest
import pandas as pd

from src.agents.analyst import TechnicalAnalystAgent, _IndicatorState


def make_analyst():
    config = {
        "analyst": {
            "timeframes": ["1h"],
            "indicators": {
                "rsi": {"period": 14},
                "ema": {"fast": 20, "slow": 50},
                "macd": {"fast": 12, "slow": 26, "signal": 9},
                "bollinger": {"period": 20, "std": 2.0},
                "atr": {"period": 14},
                "volume_sma": {"period": 20},
                "stochastic": {"k": 14, "d": 3},
                "adx": {"period": 14},
                "donchian": {"period": 20},
            },
            "multi_timeframe": {"enabled": False},
        },
        "pairs": ["BTC/USDT"],
        "strategy_dir": "config/strategies",
        "data_source": None,
    }
    return TechnicalAnalystAgent(config=config)


class TestComputeIndicators:
    def test_full_indicator_computation(self):
        analyst = make_analyst()
        candles = [
            {
                "timestamp": i * 3600000,
                "open": 10000 + i * 10,
                "high": 10100 + i * 10,
                "low": 9900 + i * 10,
                "close": 10050 + i * 10,
                "volume": 1000 + i * 5,
            }
            for i in range(250)
        ]
        state = analyst._compute_indicators(candles)
        assert state.current_price is not None
        assert state.current_volume is not None
        assert state.rsi is not None
        assert state.ema_fast is not None
        assert state.ema_slow is not None
        assert state.macd_line is not None
        assert state.bb_upper is not None
        assert state.atr is not None

    def test_insufficient_candles(self):
        analyst = make_analyst()
        candles = [{"close": 100.0, "high": 101.0, "low": 99.0, "volume": 1000}] * 10
        state = analyst._compute_indicators(candles)
        # Should return empty state
        assert state.rsi is None
        assert state.macd_line is None

    def test_missing_ta_fields(self):
        # Even with sufficient data, if it's completely flat, some indicators might be None or nan.
        # But we mostly want to make sure it runs without crashing.
        analyst = make_analyst()
        candles = [{"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0, "volume": 1000.0}] * 250
        state = analyst._compute_indicators(candles)
        assert state.current_price == 100.0
        # Donchian channel needs some variation or returns identical bands.
        assert state.donchian_upper == 100.0
