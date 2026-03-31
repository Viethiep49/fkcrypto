"""Signal schema — the contract between all agents and the Decision Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from src.agents.reasoning import Reasoning

VALID_ACTIONS = ("buy", "sell", "hold")
VALID_SOURCES = ("technical", "sentiment", "momentum", "risk", "ml", "on-chain", "alpha")


@dataclass
class Signal:
    """A normalized trading signal emitted by any agent.

    All agents must emit signals conforming to this schema.
    Signals are immutable once emitted.
    """

    symbol: str                          # e.g. "BTC/USDT"
    timeframe: str                       # e.g. "1m", "5m", "1h", "4h", "1d"
    action: Literal["buy", "sell", "hold"]
    confidence: float                    # 0.0 → 1.0
    strength: float = 0.0               # -1.0 to 1.0 (magnitude + direction)
    source: str = "technical"            # signal source category
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    reasoning: Reasoning | None = None  # structured reasoning for XAI

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe:
            raise ValueError("timeframe must be a non-empty string")
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {VALID_ACTIONS}, got '{self.action}'")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")
        if not -1.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be -1.0 to 1.0, got {self.strength}")
        if self.source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {VALID_SOURCES}, got '{self.source}'")

    def direction(self) -> float:
        """Return numeric direction: 1.0=buy, -.0=sell, 0.0=hold."""
        if self.action == "buy":
            return 1.0
        if self.action == "sell":
            return -1.0
        return 0.0

    def weighted_score(self) -> float:
        """Return confidence * direction for scoring."""
        return self.direction() * self.confidence

    def to_dict(self) -> dict[str, Any]:
        result = {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "action": self.action,
            "confidence": self.confidence,
            "strength": self.strength,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
        if self.reasoning is not None:
            result["reasoning"] = self.reasoning.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        from src.agents.reasoning import Reasoning

        ts = data.get("timestamp")
        if isinstance(ts, str):
            data["timestamp"] = datetime.fromisoformat(ts)

        reasoning = None
        if "reasoning" in data and data["reasoning"]:
            reasoning = Reasoning.from_dict(data["reasoning"])

        return cls(
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            action=data["action"],
            confidence=data["confidence"],
            strength=data.get("strength", 0.0),
            source=data.get("source", "technical"),
            timestamp=data.get("timestamp", datetime.now(UTC)),
            metadata=data.get("metadata", {}),
            reasoning=reasoning,
        )
