"""Tests for the Risk Engine."""

import pytest
from unittest.mock import MagicMock

from src.execution.validator import OrderRequest
from src.risk.engine import RiskEngine, ValidationResult


def make_risk_engine(**overrides):
    config = {
        "risk": {
            "max_positions": 5,
            "risk_per_trade": 0.02,
            "max_exposure": 0.5,
            "stop_loss": 0.05,
            "max_daily_loss": 0.05,
            "max_drawdown": 0.15,
        },
    }
    config["risk"].update(overrides)
    mock_repo = MagicMock()
    mock_repo.is_kill_switch_active.return_value = False
    mock_repo.get_orders.return_value = []
    mock_repo.get_latest_snapshot.return_value = None
    return RiskEngine(config=config, repository=mock_repo)


class TestRiskEngineValidation:
    def test_valid_order_passes(self):
        engine = make_risk_engine()
        order = OrderRequest(
            symbol="BTC/USDT",
            action="buy",
            size_usd=100.0,
            stop_loss=0.02,
        )
        result = engine.validate_order(order, total_balance=10000.0, current_positions=0)
        assert result.passed

    def test_kill_switch_rejects(self):
        config = {
            "risk": {
                "max_positions": 5,
                "risk_per_trade": 0.02,
                "max_exposure": 0.5,
                "stop_loss": 0.05,
                "max_daily_loss": 0.05,
                "max_drawdown": 0.15,
            },
        }
        mock_repo = MagicMock()
        mock_repo.is_kill_switch_active.return_value = True
        engine = RiskEngine(config=config, repository=mock_repo)
        order = OrderRequest(
            symbol="BTC/USDT",
            action="buy",
            size_usd=100.0,
            stop_loss=0.02,
        )
        result = engine.validate_order(order, total_balance=10000.0, current_positions=0)
        assert not result.passed
        assert "kill switch" in result.reason.lower()

    def test_missing_stop_loss_rejects(self):
        engine = make_risk_engine()
        order = OrderRequest(
            symbol="BTC/USDT",
            action="buy",
            size_usd=100.0,
        )
        result = engine.validate_order(order, total_balance=10000.0, current_positions=0)
        assert not result.passed
        assert "stop loss" in result.reason.lower()

    def test_negative_order_size_rejects(self):
        engine = make_risk_engine()
        order = OrderRequest(
            symbol="BTC/USDT",
            action="buy",
            size_usd=-50.0,
            stop_loss=0.02,
        )
        result = engine.validate_order(order, total_balance=10000.0, current_positions=0)
        assert not result.passed
        assert "positive" in result.reason.lower()

    def test_max_positions_rejects(self):
        engine = make_risk_engine(max_positions=2)
        order = OrderRequest(
            symbol="BTC/USDT",
            action="buy",
            size_usd=100.0,
            stop_loss=0.02,
        )
        result = engine.validate_order(order, total_balance=10000.0, current_positions=2)
        assert not result.passed
        assert "max positions" in result.reason.lower()


class TestPositionSizing:
    def test_calculate_position_size(self):
        engine = make_risk_engine()
        size = engine.calculate_position_size(balance=10000.0)
        # risk_per_trade=0.02, stop_loss=0.05
        # risk_amount = 10000 * 0.02 = 200
        # position_size = 200 / 0.05 = 4000
        assert size == pytest.approx(4000.0)

    def test_calculate_position_size_custom_params(self):
        engine = make_risk_engine()
        size = engine.calculate_position_size(
            balance=10000.0,
            risk_per_trade=0.01,
            stop_loss_pct=0.02,
        )
        # risk_amount = 10000 * 0.01 = 100
        # position_size = 100 / 0.02 = 5000
        assert size == pytest.approx(5000.0)


class TestExposureCheck:
    def test_exposure_within_limits(self):
        engine = make_risk_engine(max_exposure=0.5)
        positions = [{"size_usd": 1000.0}]
        passed, reason = engine._check_exposure(positions, 500.0, 10000.0)
        assert passed

    def test_exposure_exceeds_limit(self):
        engine = make_risk_engine(max_exposure=0.1)
        positions = [{"size_usd": 5000.0}]
        passed, reason = engine._check_exposure(positions, 5000.0, 10000.0)
        assert not passed
        assert "exceeded" in reason.lower()

    def test_zero_balance_rejects(self):
        engine = make_risk_engine()
        positions = [{"size_usd": 100.0}]
        passed, reason = engine._check_exposure(positions, 100.0, 0.0)
        assert not passed
