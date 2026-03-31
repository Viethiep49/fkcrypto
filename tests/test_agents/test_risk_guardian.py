"""Tests for the Risk Guardian Agent."""

import pytest

from src.agents.risk_guardian import RiskGuardianAgent


def make_risk_guardian(**overrides):
    config = {
        "risk_guardian": {
            "check_interval_sec": 30,
            "limits": {
                "max_drawdown_pct": 0.20,
                "max_daily_loss_pct": 0.05,
                "max_positions": 5,
                "max_exposure_pct": 0.30,
                "max_loss_per_position": 0.10,
            },
            "kill_switch": {
                "enabled": True,
                "auto_close_positions": True,
                "manual_reset_required": True,
            },
            "volatility": {
                "atr_spike_multiplier": 3.0,
            },
            "api_health": {
                "max_consecutive_errors": 10,
            },
        },
        "pairs": ["BTC/USDT"],
        "data_source": None,
    }
    config["risk_guardian"].update(overrides)
    return RiskGuardianAgent(config=config)


class TestDrawdownCheck:
    def test_drawdown_within_limits(self):
        guardian = make_risk_guardian()
        breached, dd = guardian.check_drawdown(9000.0, 10000.0)
        assert not breached
        assert dd == pytest.approx(0.10)

    def test_drawdown_exceeds_limits(self):
        guardian = make_risk_guardian(limits={"max_drawdown_pct": 0.15})
        breached, dd = guardian.check_drawdown(8000.0, 10000.0)
        assert breached
        assert dd == pytest.approx(0.20)

    def test_zero_peak_value(self):
        guardian = make_risk_guardian()
        breached, dd = guardian.check_drawdown(5000.0, 0.0)
        assert not breached
        assert dd == 0.0


class TestDailyLossCheck:
    def test_daily_loss_within_limits(self):
        guardian = make_risk_guardian()
        breached, loss = guardian.check_daily_loss(9800.0, 10000.0)
        assert not breached
        assert loss == pytest.approx(0.02)

    def test_daily_loss_exceeds_limits(self):
        guardian = make_risk_guardian(limits={"max_daily_loss_pct": 0.03})
        breached, loss = guardian.check_daily_loss(9500.0, 10000.0)
        assert breached
        assert loss == pytest.approx(0.05)

    def test_zero_starting_balance(self):
        guardian = make_risk_guardian()
        breached, loss = guardian.check_daily_loss(5000.0, 0.0)
        assert not breached
        assert loss == 0.0


class TestPositionLimits:
    def test_within_position_limit(self):
        guardian = make_risk_guardian(limits={"max_positions": 3, "max_exposure_pct": 1.5})
        positions = [{"symbol": "BTC/USDT", "value_usd": 1000.0, "unrealized_pnl_pct": 0.05}]
        violations = guardian.check_position_limits(positions)
        assert len(violations) == 0

    def test_too_many_positions(self):
        guardian = make_risk_guardian(limits={"max_positions": 2})
        positions = [
            {"symbol": "BTC/USDT", "value_usd": 1000.0, "unrealized_pnl_pct": 0.05},
            {"symbol": "ETH/USDT", "value_usd": 1000.0, "unrealized_pnl_pct": 0.03},
            {"symbol": "SOL/USDT", "value_usd": 1000.0, "unrealized_pnl_pct": -0.02},
        ]
        violations = guardian.check_position_limits(positions)
        assert len(violations) > 0
        assert "Too many positions" in violations[0]

    def test_position_loss_exceeds_limit(self):
        guardian = make_risk_guardian(limits={"max_loss_per_position": 0.05})
        positions = [{"symbol": "BTC/USDT", "value_usd": 1000.0, "unrealized_pnl_pct": -0.10}]
        violations = guardian.check_position_limits(positions)
        assert any("BTC/USDT" in v and "loss exceeds limit" in v for v in violations)


class TestKillSwitch:
    def test_trigger_kill_switch(self):
        guardian = make_risk_guardian()
        signal = guardian._trigger_kill_switch("test_reason")
        assert guardian.is_kill_switch_active
        assert guardian.kill_switch_reason == "test_reason"
        assert signal.action == "sell"
        assert signal.confidence == 1.0
        assert signal.metadata["emergency"] is True

    def test_reset_kill_switch(self):
        guardian = make_risk_guardian()
        guardian._trigger_kill_switch("test_reason")
        guardian.reset_kill_switch()
        assert not guardian.is_kill_switch_active
        assert guardian.kill_switch_reason is None

    def test_reset_when_not_active(self):
        guardian = make_risk_guardian()
        guardian.reset_kill_switch()  # Should not raise
        assert not guardian.is_kill_switch_active
