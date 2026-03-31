"""Tests for the Order Validator."""

import pytest

from src.execution.validator import OrderRequest, OrderValidator


class TestOrderRequest:
    def test_create_order_request(self):
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=100.0)
        assert order.symbol == "BTC/USDT"
        assert order.action == "buy"
        assert order.size_usd == 100.0


class TestOrderValidator:
    def test_valid_order(self):
        validator = OrderValidator()
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=100.0)
        errors = validator.validate(order)
        assert len(errors) == 0

    def test_invalid_symbol_format(self):
        validator = OrderValidator()
        order = OrderRequest(symbol="INVALID", action="buy", size_usd=100.0)
        errors = validator.validate(order)
        assert len(errors) > 0

    def test_invalid_action(self):
        validator = OrderValidator()
        order = OrderRequest(symbol="BTC/USDT", action="hold", size_usd=100.0)
        errors = validator.validate(order)
        assert len(errors) > 0

    def test_size_too_small(self):
        validator = OrderValidator(min_order_size=10.0)
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=1.0)
        errors = validator.validate(order)
        assert len(errors) > 0

    def test_size_too_large(self):
        validator = OrderValidator(max_order_size=1000.0)
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=5000.0)
        errors = validator.validate(order)
        assert len(errors) > 0

    def test_duplicate_detection(self):
        validator = OrderValidator()
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=100.0)
        validator.record_order(order)
        errors = validator.validate(order)
        assert len(errors) > 0

    def test_precision_sanitization(self):
        validator = OrderValidator(precision=2)
        order = OrderRequest(symbol="BTC/USDT", action="buy", size_usd=100.12345678)
        errors = validator.validate(order)
        assert len(errors) == 0
