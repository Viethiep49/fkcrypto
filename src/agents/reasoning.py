"""Reasoning dataclass — structured explanation of why an agent emitted a signal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningFactor:
    """A single factor contributing to a signal's reasoning.

    Examples:
        - type="indicator", description="RSI oversold at 22", impact=0.15
        - type="news", description="3 positive articles in last hour", impact=0.10
        - type="risk", description="Low exposure allows 2% position", impact=0.05
    """

    type: str                        # category: indicator, news, social, risk, pattern, event
    description: str                 # human-readable explanation
    impact: float = 0.0              # -1.0 to 1.0, how much this factor pushed the signal
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "description": self.description,
            "impact": round(self.impact, 4),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReasoningFactor:
        return cls(
            type=data["type"],
            description=data["description"],
            impact=data.get("impact", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Reasoning:
    """Complete reasoning behind a signal or decision.

    Contains structured factors and a natural language summary.
    """

    agent: str                       # which agent produced this reasoning
    factors: list[ReasoningFactor] = field(default_factory=list)
    summary: str = ""                # natural language summary (LLM-generated or template)
    confidence: float = 0.0          # agent's confidence in this reasoning

    def add_factor(self, factor: ReasoningFactor) -> None:
        """Add a reasoning factor."""
        self.factors.append(factor)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "factors": [f.to_dict() for f in self.factors],
            "summary": self.summary,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reasoning:
        return cls(
            agent=data["agent"],
            factors=[ReasoningFactor.from_dict(f) for f in data.get("factors", [])],
            summary=data.get("summary", ""),
            confidence=data.get("confidence", 0.0),
        )
