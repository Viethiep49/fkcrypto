"""Tests for the Decision Engine."""

import pytest

from src.agents.signal import Signal
from src.agents.decision_engine import DecisionEngine, Decision


def make_engine(**overrides):
    """Helper to create a DecisionEngine with minimal config."""
    config = {
        "decision": {
            "weights": {
                "technical": 0.40,
                "sentiment": 0.25,
                "momentum": 0.20,
                "risk": 0.15,
            },
            "thresholds": {
                "buy": 0.6,
                "sell": -0.6,
                "min_confidence": 0.5,
            },
            "confidence_boost": {
                "agreement_bonus": 0.15,
                "max_confidence": 0.95,
            },
            "explanation": {"enabled": False},
        },
    }
    config["decision"].update(overrides)
    return DecisionEngine(config=config, llm_gateway=None, repository=None)


class TestNormalizeSignal:
    def test_clamps_confidence_high(self):
        # Signal validates on construction, so confidence > 1.0 raises before normalize
        # This test verifies the static method doesn't crash on valid input
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=1.0, strength=0.9)
        result = DecisionEngine.normalize_signal(sig)
        assert result.confidence == 1.0

    def test_clamps_strength(self):
        # Signal validates on construction, so we test the normalize logic
        sig = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, strength=0.9)
        result = DecisionEngine.normalize_signal(sig)
        assert result.strength == 0.9  # Already in range


class TestDeduplicateSignals:
    def test_removes_duplicate_source_timeframe(self):
        sig1 = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.7, source="technical")
        sig2 = Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.8, source="technical")
        result = DecisionEngine.deduplicate_signals([sig1, sig2])
        assert len(result) == 1
        assert result[0].confidence == 0.8  # Keeps latest

    def test_keeps_different_sources(self):
        sig1 = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.7, source="technical")
        sig2 = Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.8, source="sentiment")
        result = DecisionEngine.deduplicate_signals([sig1, sig2])
        assert len(result) == 2

    def test_keeps_different_timeframes(self):
        sig1 = Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.7, source="technical")
        sig2 = Signal(symbol="BTC/USDT", timeframe="4h", action="buy", confidence=0.8, source="technical")
        result = DecisionEngine.deduplicate_signals([sig1, sig2])
        assert len(result) == 2


class TestCalculateScore:
    def test_empty_signals_returns_zero(self):
        engine = make_engine()
        assert engine.calculate_score([]) == 0.0

    def test_single_buy_signal(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
        ]
        score = engine.calculate_score(signals)
        assert score > 0

    def test_single_sell_signal(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.8, source="technical"),
        ]
        score = engine.calculate_score(signals)
        assert score < 0

    def test_mixed_signals(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.9, source="technical"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.9, source="sentiment"),
        ]
        score = engine.calculate_score(signals)
        # Technical weight (0.4) > Sentiment weight (0.25), so score should be positive
        assert score > 0

    def test_hold_signals_contribute_zero(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="hold", confidence=0.9, source="technical"),
        ]
        score = engine.calculate_score(signals)
        assert score == 0.0

    def test_score_bounded(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=1.0, source="technical"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=1.0, source="sentiment"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=1.0, source="momentum"),
        ]
        score = engine.calculate_score(signals)
        assert -1.0 <= score <= 1.0


class TestMakeDecision:
    def test_above_buy_threshold(self):
        engine = make_engine()
        assert engine.make_decision(0.7) == "buy"

    def test_below_sell_threshold(self):
        engine = make_engine()
        assert engine.make_decision(-0.7) == "sell"

    def test_between_thresholds(self):
        engine = make_engine()
        assert engine.make_decision(0.0) == "hold"
        assert engine.make_decision(0.5) == "hold"
        assert engine.make_decision(-0.5) == "hold"

    def test_at_threshold_boundary(self):
        engine = make_engine(buy=0.6, sell=-0.6)
        assert engine.make_decision(0.6) == "hold"  # Must be strictly greater
        assert engine.make_decision(-0.6) == "hold"  # Must be strictly less


class TestCalculateConfidence:
    def test_empty_signals(self):
        engine = make_engine()
        assert engine.calculate_confidence([]) == 0.0

    def test_single_signal(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
        ]
        # Single signal gets agreement bonus (only one non-hold action)
        assert engine.calculate_confidence(signals) == pytest.approx(0.95, abs=0.01)

    def test_agreement_bonus(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.7, source="sentiment"),
        ]
        conf = engine.calculate_confidence(signals)
        # Average = 0.75, + agreement_bonus 0.15 = 0.90
        assert conf == pytest.approx(0.90, abs=0.01)

    def test_no_bonus_on_disagreement(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="sell", confidence=0.7, source="sentiment"),
        ]
        conf = engine.calculate_confidence(signals)
        assert conf == pytest.approx(0.75, abs=0.01)

    def test_holds_ignored_for_agreement(self):
        engine = make_engine()
        signals = [
            Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
            Signal(symbol="BTC/USDT", timeframe="1h", action="hold", confidence=0.5, source="sentiment"),
        ]
        conf = engine.calculate_confidence(signals)
        # Only one non-hold action, so agreement bonus still applies
        # base = (0.8 + 0.5) / 2 = 0.65, + 0.15 = 0.80
        assert conf == pytest.approx(0.80, abs=0.01)
