"""Backtest metrics computation.

Calculates standard performance metrics from trade history and
portfolio snapshots.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def compute_metrics(
    trades: list[Any],
    snapshots: list[Any],
    initial_capital: float,
    buy_and_hold_return: float = 0.0,
) -> dict[str, Any]:
    """Compute standard backtest performance metrics.

    Args:
        trades: List of TradeRecord objects from the simulator.
        snapshots: List of PortfolioSnapshot objects from the simulator.
        initial_capital: Starting capital.
        buy_and_hold_return: Buy-and-hold return fraction for comparison.

    Returns:
        Dict of metric name → value.
    """
    if not snapshots:
        return _empty_metrics(buy_and_hold_return)

    win_rate = _win_rate(trades)
    profit_factor = _profit_factor(trades)
    max_dd = _max_drawdown(snapshots)
    sharpe = _sharpe_ratio(snapshots)
    sortino = _sortino_ratio(snapshots)
    calmar = _calmar_ratio(snapshots, max_dd)
    avg_duration = _avg_trade_duration(trades)

    return {
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
        "avg_trade_duration_hours": round(avg_duration, 2),
        "total_return_vs_bnh": round(
            _total_return(snapshots, initial_capital) - buy_and_hold_return, 4
        ),
    }


def _empty_metrics(bnh: float = 0.0) -> dict[str, Any]:
    return {
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "avg_trade_duration_hours": 0.0,
        "total_return_vs_bnh": -bnh,
    }


def _win_rate(trades: list[Any]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def _profit_factor(trades: list[Any]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _max_drawdown(snapshots: list[Any]) -> float:
    peak = snapshots[0].portfolio_value
    max_dd = 0.0

    for s in snapshots:
        if s.portfolio_value > peak:
            peak = s.portfolio_value
        dd = (peak - s.portfolio_value) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return max_dd


def _returns_series(snapshots: list[Any]) -> list[float]:
    if len(snapshots) < 2:
        return []
    returns = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1].portfolio_value
        curr = snapshots[i].portfolio_value
        if prev > 0:
            returns.append((curr - prev) / prev)
    return returns


def _sharpe_ratio(snapshots: list[Any], risk_free_rate: float = 0.0) -> float:
    returns = _returns_series(snapshots)
    if not returns:
        return 0.0

    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / n
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0:
        return 0.0

    annualized_sharpe = (mean_r - risk_free_rate) / std * math.sqrt(252 * 24)
    return annualized_sharpe


def _sortino_ratio(snapshots: list[Any], risk_free_rate: float = 0.0) -> float:
    returns = _returns_series(snapshots)
    if not returns:
        return 0.0

    n = len(returns)
    mean_r = sum(returns) / n
    downside_sq = sum((r - risk_free_rate) ** 2 for r in returns if r < risk_free_rate)
    downside_std = math.sqrt(downside_sq / n) if downside_sq > 0 else 0.0

    if downside_std == 0:
        return 0.0

    annualized = (mean_r - risk_free_rate) / downside_std * math.sqrt(252 * 24)
    return annualized


def _calmar_ratio(snapshots: list[Any], max_dd: float) -> float:
    if not snapshots or max_dd == 0:
        return 0.0

    start_val = snapshots[0].portfolio_value
    end_val = snapshots[-1].portfolio_value

    start_ts = snapshots[0].timestamp
    end_ts = snapshots[-1].timestamp
    years = _years_between(start_ts, end_ts)

    if years <= 0:
        return 0.0

    cagr = (end_val / start_val) ** (1 / years) - 1 if start_val > 0 else 0.0
    return cagr / max_dd


def _avg_trade_duration(trades: list[Any]) -> float:
    if not trades:
        return 0.0

    total_hours = 0.0
    count = 0
    for t in trades:
        delta = t.exit_time - t.entry_time
        total_hours += delta.total_seconds() / 3600
        count += 1

    return total_hours / count if count > 0 else 0.0


def _total_return(snapshots: list[Any], initial_capital: float) -> float:
    if not snapshots or initial_capital == 0:
        return 0.0
    final = snapshots[-1].portfolio_value
    return (final - initial_capital) / initial_capital


def _years_between(start: datetime, end: datetime) -> float:
    delta = end - start
    return delta.total_seconds() / (365.25 * 24 * 3600)
