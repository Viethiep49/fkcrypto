"""Tests for the Technical Analyst indicators."""

import pytest

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


class TestEMA:
    def test_ema_basic(self):
        analyst = make_analyst()
        values = list(range(1, 101))  # 1..100
        ema = analyst._compute_ema(values, 10)
        assert len(ema) == 91  # 100 - 10 + 1
        assert ema[-1] > ema[0]  # Uptrend

    def test_ema_insufficient_data(self):
        analyst = make_analyst()
        values = [1.0, 2.0, 3.0]
        ema = analyst._compute_ema(values, 10)
        assert len(ema) == 0


class TestRSI:
    def test_rsi_uptrend(self):
        analyst = make_analyst()
        # Strong uptrend
        values = list(range(1, 101))
        rsi = analyst._compute_rsi(values, 14)
        assert len(rsi) > 0
        assert 0 <= rsi[-1] <= 100

    def test_rsi_downtrend(self):
        analyst = make_analyst()
        # Strong downtrend
        values = list(range(100, 0, -1))
        rsi = analyst._compute_rsi(values, 14)
        assert len(rsi) > 0
        assert 0 <= rsi[-1] <= 100

    def test_rsi_insufficient_data(self):
        analyst = make_analyst()
        values = [1.0, 2.0, 3.0]
        rsi = analyst._compute_rsi(values, 14)
        assert len(rsi) == 0


class TestMACD:
    def test_macd_basic(self):
        analyst = make_analyst()
        values = list(range(1, 101))
        macd_line, signal_line, histogram = analyst._compute_macd(values, 12, 26, 9)
        assert len(macd_line) > 0
        assert len(histogram) > 0

    def test_macd_insufficient_data(self):
        analyst = make_analyst()
        values = [1.0] * 10
        macd_line, signal_line, histogram = analyst._compute_macd(values, 12, 26, 9)
        assert len(macd_line) == 0


class TestBollingerBands:
    def test_bb_basic(self):
        analyst = make_analyst()
        values = list(range(1, 101))
        upper, middle, lower = analyst._compute_bollinger_bands(values, 20, 2.0)
        assert len(upper) > 0
        assert len(middle) > 0
        assert len(lower) > 0
        assert upper[-1] > middle[-1] > lower[-1]

    def test_bb_insufficient_data(self):
        analyst = make_analyst()
        values = [1.0] * 10
        upper, middle, lower = analyst._compute_bollinger_bands(values, 20, 2.0)
        assert len(upper) == 0


class TestATR:
    def test_atr_basic(self):
        analyst = make_analyst()
        candles = [
            {"high": 100 + i, "low": 95 + i, "close": 98 + i, "volume": 1000}
            for i in range(50)
        ]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        atr = analyst._compute_atr(highs, lows, closes, 14)
        assert len(atr) > 0
        assert all(a >= 0 for a in atr)

    def test_atr_insufficient_data(self):
        analyst = make_analyst()
        highs = [100.0] * 5
        lows = [95.0] * 5
        closes = [98.0] * 5
        atr = analyst._compute_atr(highs, lows, closes, 14)
        assert len(atr) == 0


class TestStochastic:
    def test_stochastic_basic(self):
        analyst = make_analyst()
        candles = [
            {"high": 100 + i, "low": 90 + i, "close": 95 + i, "volume": 1000}
            for i in range(50)
        ]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        k, d = analyst._compute_stochastic(highs, lows, closes, 14, 3)
        assert len(k) > 0
        assert all(0 <= v <= 100 for v in k)


class TestADX:
    def test_adx_basic(self):
        analyst = make_analyst()
        candles = [
            {"high": 100 + i * 2, "low": 95 + i * 2, "close": 98 + i * 2, "volume": 1000}
            for i in range(100)
        ]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        adx = analyst._compute_adx(highs, lows, closes, 14)
        assert len(adx) > 0
        assert all(v >= 0 for v in adx)


class TestDonchian:
    def test_donchian_basic(self):
        analyst = make_analyst()
        highs = [100, 105, 110, 108, 112, 115, 113, 118, 120, 122]
        lows = [90, 92, 88, 95, 93, 91, 96, 94, 97, 99]
        upper, middle, lower = analyst._compute_donchian(highs, lows, 5)
        assert len(upper) > 0
        assert upper[-1] >= middle[-1] >= lower[-1]


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
