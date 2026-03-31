"""Position sizing utilities for risk management."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.agents.signal import Signal


@dataclass
class PositionSize:
    """Result of position size calculation."""

    size_usd: float
    size_units: float
    risk_usd: float
    convergence_factor: float = 1.0
    base_risk_pct: float = 0.0


def calculate_position_size(
    account_balance: float,
    risk_per_trade: float,
    stop_loss_pct: float,
) -> float:
    """Calculate position size based on risk parameters.

    Args:
        account_balance: Total account balance in USD.
        risk_per_trade: Fraction of account to risk per trade (e.g. 0.02 = 2%).
        stop_loss_pct: Stop loss as a fraction (e.g. 0.05 = 5%).

    Returns:
        Position size in USD.
    """
    if account_balance <= 0:
        return 0.0
    if risk_per_trade <= 0:
        return 0.0
    if stop_loss_pct <= 0:
        return 0.0

    risk_amount = account_balance * risk_per_trade
    position_size = risk_amount / stop_loss_pct
    return position_size


def calculate_convergence_factor(signals: list[Signal]) -> float:
    """Calculate signal convergence factor based on agent agreement.

    The convergence factor measures how much the agents agree on
    direction and confidence. Higher agreement = higher factor.

    Formula:
        convergence = 1.0 + (agreement_score * confidence_bonus)

    Where:
        - agreement_score: How many agents agree on direction (-1 to 1)
        - confidence_bonus: Bonus from low variance in confidence

    Examples:
        - All agents buy with high confidence → factor ≈ 1.5
        - Mixed signals (buy/sell conflict) → factor ≈ 0.2
        - Single agent signal → factor ≈ 1.0

    Args:
        signals: List of Signal objects from all agents.

    Returns:
        Convergence factor (typically 0.0 to 2.0).
    """
    if not signals:
        return 0.0

    non_hold = [s for s in signals if s.action != "hold"]
    if not non_hold:
        return 0.0

    # Direction agreement: buy=1, sell=-1
    directions = [1.0 if s.action == "buy" else -1.0 for s in non_hold]
    avg_direction = sum(directions) / len(directions)
    agreement_score = abs(avg_direction)

    # Confidence statistics
    confidences = [s.confidence for s in non_hold]
    avg_confidence = sum(confidences) / len(confidences)

    # Low variance = high agreement → bonus
    if len(confidences) > 1:
        variance = sum((c - avg_confidence) ** 2 for c in confidences) / len(confidences)
        std_dev = math.sqrt(variance)
        # Low std_dev = agents agree on confidence level
        confidence_bonus = max(0.0, 1.0 - std_dev * 2)
    else:
        confidence_bonus = 0.5

    # Alpha signals get automatic boost
    has_alpha = any(s.source == "alpha" for s in non_hold)
    alpha_priority = 0.0
    if has_alpha:
        for s in non_hold:
            if s.source == "alpha":
                priority = s.metadata.get("priority", "")
                if priority == "immediate":
                    alpha_priority = 0.5
                elif priority == "high":
                    alpha_priority = 0.25
                break

    # Final convergence factor
    base = agreement_score * avg_confidence * (1.0 + confidence_bonus)
    factor = 1.0 + base + alpha_priority

    # Clamp to reasonable range
    return max(0.1, min(factor, 2.5))


def calculate_dynamic_size(
    account_balance: float,
    base_risk_pct: float,
    signals: list[Signal],
    stop_loss_pct: float = 0.05,
    max_size_pct: float = 0.10,
    min_size_pct: float = 0.005,
) -> PositionSize:
    """Calculate position size based on signal convergence.

    Dynamic Risk = Base Risk × Convergence Factor

    Args:
        account_balance: Total account balance in USD.
        base_risk_pct: Base risk per trade (e.g. 0.02 = 2%).
        signals: List of Signal objects from all agents.
        stop_loss_pct: Stop loss as fraction (e.g. 0.05 = 5%).
        max_size_pct: Maximum position size as % of balance.
        min_size_pct: Minimum position size as % of balance.

    Returns:
        PositionSize with calculated size and metadata.
    """
    if account_balance <= 0 or base_risk_pct <= 0:
        return PositionSize(size_usd=0.0, size_units=0.0, risk_usd=0.0)

    convergence = calculate_convergence_factor(signals)

    # Dynamic risk = base risk * convergence
    dynamic_risk_pct = base_risk_pct * convergence

    # Clamp to min/max
    dynamic_risk_pct = max(min_size_pct, min(dynamic_risk_pct, max_size_pct))

    # Position size = risk / stop_loss
    risk_usd = account_balance * dynamic_risk_pct
    size_usd = risk_usd / stop_loss_pct if stop_loss_pct > 0 else risk_usd * 10

    return PositionSize(
        size_usd=round(size_usd, 2),
        size_units=0.0,  # Calculated at execution time with price
        risk_usd=round(risk_usd, 2),
        convergence_factor=round(convergence, 4),
        base_risk_pct=base_risk_pct,
    )


def calculate_stop_loss(price: float, atr: float, multiplier: float = 2.0) -> float:
    """Calculate stop loss price using ATR-based method.

    Args:
        price: Current price or entry price.
        atr: Average True Range value.
        multiplier: ATR multiplier (default 2.0).

    Returns:
        Stop loss price.
    """
    if price <= 0 or atr < 0:
        return price
    return price - (atr * multiplier)


def calculate_take_profit(
    entry: float,
    risk_reward_ratio: float,
    stop_distance: float,
) -> float:
    """Calculate take profit price based on risk-reward ratio.

    Args:
        entry: Entry price.
        risk_reward_ratio: Desired risk/reward ratio (e.g. 2.0 means 2:1).
        stop_distance: Distance from entry to stop loss (absolute price difference).

    Returns:
        Take profit price.
    """
    if entry <= 0 or stop_distance < 0:
        return entry
    return entry + (stop_distance * risk_reward_ratio)


def apply_trailing_stop(
    current_price: float,
    entry_price: float,
    trail_pct: float,
    activation_pct: float,
    highest_price: float,
) -> tuple[float, bool]:
    """Apply trailing stop logic.

    Args:
        current_price: Current market price.
        entry_price: Original entry price.
        trail_pct: Trailing stop percentage (e.g. 0.02 = 2%).
        activation_pct: Percentage gain to activate trailing stop (e.g. 0.03 = 3%).
        highest_price: Highest price reached since entry.

    Returns:
        Tuple of (trailing_stop_price, is_activated).
    """
    if entry_price <= 0 or current_price <= 0:
        return current_price, False

    gain_pct = (highest_price - entry_price) / entry_price
    is_activated = gain_pct >= activation_pct

    if not is_activated:
        return entry_price - (entry_price * trail_pct), False

    trailing_stop = highest_price * (1.0 - trail_pct)
    return trailing_stop, True


def check_exposure(
    positions: list[dict[str, Any]],
    max_exposure_pct: float,
    total_balance: float,
) -> tuple[bool, float, float]:
    """Check if current exposure is within limits.

    Args:
        positions: List of position dicts with 'size_usd' key.
        max_exposure_pct: Maximum exposure as fraction of total balance.
        total_balance: Total account balance.

    Returns:
        Tuple of (is_within_limits, current_exposure_usd, current_exposure_pct).
    """
    if total_balance <= 0:
        return False, 0.0, 0.0

    current_exposure = sum(p.get("size_usd", 0.0) for p in positions)
    exposure_pct = current_exposure / total_balance
    is_within_limits = exposure_pct <= max_exposure_pct

    return is_within_limits, current_exposure, exposure_pct
