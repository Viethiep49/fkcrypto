"""Tests for the Signal dataclass and validation."""

import pytest
from datetime import datetime, timezone

from src.agents.signal import Signal, VALID_ACTIONS, VALID_SOURCES


class TestSignalValidation:
    """Test Signal validation in __post_init__."""

    def test_valid_signal(self):
        sig = Signal(
            symbol="BTC/USDT",
            timeframe="1h",
            action="buy",
            confidence=0.8,
            strength=0.5,
            source="technical",
        )
        assert sig.symbol == "BTC/USDT"
        assert sig.confidence == 0.8
        assert sig.strength == 0.5

    def test_valid_hold_signal(self):
        sig = Signal(
            symbol="ETH/USDT",
            timeframe="15m",
            action="hold",
            confidence=0.0,
            strength=0.0,
            source="sentiment",
        )
        assert sig.action == "hold"

    def test_invalid_action_raises(self):
        with pytest.raises(ValueError, match="action must be one of"):
            Signal(
                symbol="BTC/USDT",
                timeframe="1h",
                action="short",
                confidence=0.5,
            )

    def test_confidence_too_high_raises(self):
        with pytest.raises(ValueError, match="confidence must be"):
            Signal(
                symbol="BTC/USDT",
                timeframe="1h",
                action="buy",
                confidence=1.5,
            )

    def test_confidence_negative_raises(self):
        with pytest.raises(ValueError, match="confidence must be"):
            Signal(
                symbol="BTC/USDT",
                timeframe="1h",
                action="buy",
                confidence=-0.1,
            )

    def test_strength_out_of_range_raises(self):
        with pytest.raises(ValueError, match="strength must be"):
            Signal(
                symbol="BTC/USDT",
                timeframe="1h",
                action="buy",
                confidence=0.5,
                strength=1.5,
            )

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="source must be one of"):
            Signal(
                symbol="BTC/USDT",
                timeframe="1h",
                action="buy",
                confidence=0.5,
                source="invalid_source",
            )

    def test_empty_symbol_raises(self):
        with pytest.raises(ValueError, match="symbol must be a non-empty string"):
            Signal(
                symbol="",
                timeframe="1h",
                action="buy",
                confidence=0.5,
            )

    def test_empty_timeframe_raises(self):
        with pytest.raises(ValueError, match="timeframe must be a non-empty string"):
            Signal(
                symbol="BTC/USDT",
                timeframe="",
                action="buy",
                confidence=0.5,
            )


class TestSignalMethods:
    """Test Signal helper methods."""

    def test_direction_buy(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8)
        assert sig.direction() == 1.0

    def test_direction_sell(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.8)
        assert sig.direction() == -1.0

    def test_direction_hold(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="hold", confidence=0.8)
        assert sig.direction() == 0.0

    def test_weighted_score_buy(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.7)
        assert sig.weighted_score() == 0.7

    def test_weighted_score_sell(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.6)
        assert sig.weighted_score() == -0.6

    def test_to_dict(self):
        sig = Signal(
            symbol="BTC/USDT",
            timeframe="1h",
            action="buy",
            confidence=0.85,
            strength=0.6,
            source="technical",
            metadata={"strategy": "mean_reversion"},
        )
        d = sig.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert d["action"] == "buy"
        assert d["confidence"] == 0.85
        assert d["strength"] == 0.6
        assert d["source"] == "technical"
        assert d["metadata"]["strategy"] == "mean_reversion"
        assert isinstance(d["timestamp"], str)

    def test_from_dict(self):
        data = {
            "symbol": "ETH/USDT",
            "timeframe": "4h",
            "action": "sell",
            "confidence": 0.75,
            "strength": -0.4,
            "source": "sentiment",
            "timestamp": "2026-03-31T12:00:00+00:00",
            "metadata": {"sentiment_score": -0.6},
        }
        sig = Signal.from_dict(data)
        assert sig.symbol == "ETH/USDT"
        assert sig.action == "sell"
        assert sig.confidence == 0.75
        assert sig.strength == -0.4
        assert sig.source == "sentiment"
        assert sig.metadata["sentiment_score"] == -0.6

    def test_from_dict_without_timestamp(self):
        data = {
            "symbol": "SOL/USDT",
            "timeframe": "1h",
            "action": "buy",
            "confidence": 0.9,
        }
        sig = Signal.from_dict(data)
        assert sig.symbol == "SOL/USDT"
        assert isinstance(sig.timestamp, datetime)

    def test_roundtrip_serialization(self):
        original = Signal(
            symbol="BTC/USDT",
            timeframe="1d",
            action="buy",
            confidence=0.92,
            strength=0.8,
            source="ml",
            metadata={"model": "lstm_v2"},
        )
        restored = Signal.from_dict(original.to_dict())
        assert restored.symbol == original.symbol
        assert restored.action == original.action
        assert restored.confidence == original.confidence
        assert restored.strength == original.strength
        assert restored.source == original.source
        assert restored.metadata == original.metadata


class TestSignalDefaults:
    """Test Signal default values."""

    def test_default_strength(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.5)
        assert sig.strength == 0.0

    def test_default_source(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.5)
        assert sig.source == "technical"

    def test_default_timestamp(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.5)
        assert isinstance(sig.timestamp, datetime)
        assert sig.timestamp.tzinfo is not None

    def test_default_metadata(self):
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.5)
        assert sig.metadata == {}
        assert sig.metadata is not None  # Each instance gets its own dict
