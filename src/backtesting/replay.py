"""Backtest Replay — stores market context snapshots for visual replay.

Captures the state of indicators, news, and signals at the moment
each decision was made, enabling visual replay on the Dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class MarketSnapshot:
    """Market context at the moment a decision was made.

    Contains all data needed to visually replay a decision:
    - OHLCV candles around the decision time
    - Indicator values at that moment
    - Signals received from each agent
    - News/sentiment data that was available
    """

    decision_id: str
    symbol: str
    timestamp: datetime
    price: float
    candles: list[dict[str, Any]] = field(default_factory=list)
    indicators: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    news_items: list[dict[str, Any]] = field(default_factory=list)
    reasoning: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "candles": self.candles,
            "indicators": self.indicators,
            "signals": self.signals,
            "news_items": self.news_items,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketSnapshot:
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        return cls(
            decision_id=data.get("decision_id", ""),
            symbol=data.get("symbol", ""),
            timestamp=ts or datetime.now(UTC),
            price=data.get("price", 0.0),
            candles=data.get("candles", []),
            indicators=data.get("indicators", {}),
            signals=data.get("signals", []),
            news_items=data.get("news_items", []),
            reasoning=data.get("reasoning", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ReplayContext:
    """Full context for replaying a specific decision.

    Combines the market snapshot with the decision outcome
    (PnL, duration, exit reason) for post-trade analysis.
    """

    snapshot: MarketSnapshot
    decision_action: str
    decision_score: float
    decision_confidence: float
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    duration_minutes: float = 0.0
    exit_reason: str = ""

    @property
    def is_profitable(self) -> bool:
        return self.pnl_pct > 0

    @property
    def outcome_label(self) -> str:
        if self.pnl_pct > 1.0:
            return "WIN"
        elif self.pnl_pct < -1.0:
            return "LOSS"
        return "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        result = self.snapshot.to_dict()
        result.update({
            "decision_action": self.decision_action,
            "decision_score": self.decision_score,
            "decision_confidence": self.decision_confidence,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": round(self.pnl_pct, 4),
            "duration_minutes": round(self.duration_minutes, 1),
            "exit_reason": self.exit_reason,
            "outcome": self.outcome_label,
        })
        return result


def create_snapshot_from_signals(
    decision_id: str,
    symbol: str,
    timestamp: datetime,
    price: float,
    signals: list[Any],
    candles: list[dict[str, Any]] | None = None,
    indicators: dict[str, Any] | None = None,
    news_items: list[dict[str, Any]] | None = None,
) -> MarketSnapshot:
    """Create a MarketSnapshot from decision-time data.

    Args:
        decision_id: Unique identifier for the decision.
        symbol: Trading pair.
        timestamp: Decision timestamp.
        price: Current price at decision time.
        signals: List of Signal objects received.
        candles: OHLCV candles available at decision time.
        indicators: Computed indicator values.
        news_items: News items available at decision time.

    Returns:
        MarketSnapshot ready for storage and replay.
    """
    signal_dicts = []
    reasoning_by_agent = {}

    for sig in signals:
        sd = sig.to_dict() if hasattr(sig, "to_dict") else sig
        signal_dicts.append(sd)

        if hasattr(sig, "reasoning") and sig.reasoning:
            agent = sig.reasoning.agent if hasattr(sig.reasoning, "agent") else sig.source
            if hasattr(sig.reasoning, "to_dict"):
                reasoning_by_agent[agent] = sig.reasoning.to_dict()

    return MarketSnapshot(
        decision_id=decision_id,
        symbol=symbol,
        timestamp=timestamp,
        price=price,
        candles=candles or [],
        indicators=indicators or {},
        signals=signal_dicts,
        news_items=news_items or [],
        reasoning=reasoning_by_agent,
        metadata={
            "signal_count": len(signal_dicts),
            "agent_count": len(reasoning_by_agent),
        },
    )


def build_replay_chart_data(
    snapshot: MarketSnapshot,
    lookback: int = 50,
    show_bb: bool = True,
    show_volume: bool = True,
) -> dict[str, Any]:
    """Build chart data for visual replay on Dashboard.

    Args:
        snapshot: Market snapshot to replay.
        lookback: Number of candles to show before decision point.
        show_bb: Include Bollinger Bands in chart data.
        show_volume: Include volume in chart data.

    Returns:
        Dict with Plotly-compatible chart data.
    """
    candles = snapshot.candles[-lookback:] if snapshot.candles else []

    if not candles:
        return {
            "timestamps": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "volume": [],
            "decision_marker": None,
            "indicators": {},
        }

    chart = {
        "timestamps": [c.get("timestamp", "") for c in candles],
        "open": [c.get("open", 0) for c in candles],
        "high": [c.get("high", 0) for c in candles],
        "low": [c.get("low", 0) for c in candles],
        "close": [c.get("close", 0) for c in candles],
        "volume": [c.get("volume", 0) for c in candles] if show_volume else [],
        "decision_marker": {
            "timestamp": snapshot.timestamp.isoformat(),
            "price": snapshot.price,
            "action": snapshot.reasoning.get("action", ""),
        },
        "indicators": snapshot.indicators,
    }

    if show_bb and "bb_upper" in snapshot.indicators:
        chart["bb_upper"] = snapshot.indicators.get("bb_upper", [])
        chart["bb_middle"] = snapshot.indicators.get("bb_middle", [])
        chart["bb_lower"] = snapshot.indicators.get("bb_lower", [])

    return chart
