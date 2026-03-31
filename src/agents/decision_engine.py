"""Decision Engine — aggregates signals, applies weighted scoring,
produces final trade decisions."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.signal import Signal
from src.database.models import DecisionRecord, SignalRecord
from src.database.repository import Repository

logger = structlog.get_logger(__name__)


@dataclass
class Decision:
    """Final trade decision produced by the Decision Engine."""

    symbol: str
    action: str
    score: float
    confidence: float
    signals: list[Signal]
    explanation: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "signal_count": len(self.signals),
            "sources": list(set(s.source for s in self.signals)),
            "explanation": self.explanation,
            "timestamp": self.timestamp.isoformat(),
        }


EXPLANATION_PROMPT = """
Explain this trading decision in 2-3 sentences for a dashboard display.

Decision: {action} {symbol}
Score: {score}
Confidence: {confidence}
Signals: {signal_summary}

Be concise. Focus on the key reasons.
"""


class DecisionEngine:
    """Central decision engine that aggregates signals and produces trade decisions.

    Deterministic: same inputs always produce same outputs.
    LLM is only used for explanation, never for making decisions.
    """

    def __init__(
        self,
        config: dict[str, Any],
        llm_gateway: Any,
        repository: Repository,
    ) -> None:
        self.config = config
        self.llm_gateway = llm_gateway
        self.repository = repository

        decision_cfg = config.get("decision", {})

        self.weights: dict[str, float] = decision_cfg.get("weights", {
            "technical": 0.30,
            "sentiment": 0.20,
            "momentum": 0.20,
            "risk": 0.15,
            "ml": 0.10,
            "on-chain": 0.05,
        })

        thresholds = decision_cfg.get("thresholds", {})
        self.buy_threshold: float = thresholds.get("buy", 0.6)
        self.sell_threshold: float = thresholds.get("sell", -0.6)
        self.min_confidence: float = thresholds.get("min_confidence", 0.5)

        conf_boost = decision_cfg.get("confidence_boost", {})
        self.agreement_bonus: float = conf_boost.get("agreement_bonus", 0.15)
        self.max_confidence: float = conf_boost.get("max_confidence", 0.95)

        explanation_cfg = decision_cfg.get("explanation", {})
        self.explanation_enabled: bool = explanation_cfg.get("enabled", True)

    @staticmethod
    def normalize_signal(signal: Signal) -> Signal:
        """Clamp confidence to [0, 1] and strength to [-1, 1]."""
        signal.confidence = max(0.0, min(1.0, signal.confidence))
        signal.strength = max(-1.0, min(1.0, signal.strength))
        return signal

    @staticmethod
    def deduplicate_signals(signals: list[Signal]) -> list[Signal]:
        """Remove duplicate signals from the same source and timeframe for the same symbol.

        Keeps the latest signal when duplicates are found.
        """
        seen: dict[tuple[str, str, str], Signal] = {}
        for signal in signals:
            key = (signal.symbol, signal.source, signal.timeframe)
            if key not in seen or signal.timestamp > seen[key].timestamp:
                seen[key] = signal
        return list(seen.values())

    def calculate_score(
        self,
        signals: list[Signal],
        weights: dict[str, float] | None = None,
    ) -> float:
        """Calculate weighted score from signals.

        Alpha signals with high priority receive a score boost
        to override technical analysis when warranted.

        Returns:
            float: -1.0 (strong sell) to +1.0 (strong buy)
        """
        w = weights if weights is not None else self.weights

        if not signals:
            return 0.0

        by_source: dict[str, list[Signal]] = {}
        for s in signals:
            by_source.setdefault(s.source, []).append(s)

        weighted_sum = 0.0
        total_weight = 0.0

        for source, source_signals in by_source.items():
            source_weight = w.get(source, 0.1)
            directions = []
            for s in source_signals:
                direction = 1.0 if s.action == "buy" else (-1.0 if s.action == "sell" else 0.0)
                directions.append(direction * s.confidence)
            source_score = sum(directions) / len(directions) if directions else 0.0

            # Alpha signal priority boost
            if source == "alpha":
                for sig in source_signals:
                    priority = sig.metadata.get("priority", "")
                    if priority == "immediate":
                        source_score *= 1.5
                    elif priority == "high":
                        source_score *= 1.2

            weighted_sum += source_weight * source_score
            total_weight += source_weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def make_decision(self, score: float) -> str:
        """Convert score to action using configured thresholds."""
        if score > self.buy_threshold:
            return "buy"
        elif score < self.sell_threshold:
            return "sell"
        return "hold"

    def calculate_confidence(self, signals: list[Signal]) -> float:
        """Calculate aggregate confidence with agreement bonus."""
        if not signals:
            return 0.0

        total_confidence = sum(s.confidence for s in signals)
        base_confidence = total_confidence / len(signals)

        actions = [s.action for s in signals]
        non_hold_actions = [a for a in actions if a != "hold"]

        if len(non_hold_actions) > 0 and len(set(non_hold_actions)) == 1:
            return min(base_confidence + self.agreement_bonus, self.max_confidence)

        return base_confidence

    async def generate_explanation(self, decision: Decision) -> str:
        """Use LLM to generate a human-readable explanation (non-blocking)."""
        if not self.explanation_enabled or not self.llm_gateway:
            return "N/A"

        signal_summary = ", ".join(
            f"{s.source}:{s.action}(c={s.confidence:.2f})" for s in decision.signals
        )

        prompt = EXPLANATION_PROMPT.format(
            action=decision.action,
            symbol=decision.symbol,
            score=decision.score,
            confidence=decision.confidence,
            signal_summary=signal_summary,
        )

        try:
            result = await asyncio.wait_for(
                self.llm_gateway.generate(prompt, max_tokens=200),
                timeout=10.0,
            )
            return result.strip() if result else "N/A"
        except TimeoutError:
            logger.warning("LLM explanation timed out", symbol=decision.symbol)
            return "N/A"
        except Exception as exc:
            logger.warning("LLM explanation failed", symbol=decision.symbol, error=str(exc))
            return "N/A"

    def _save_signals(self, signals: list[Signal]) -> None:
        """Persist individual signals to database with reasoning data."""
        for signal in signals:
            try:
                reasoning_json = "{}"
                reasoning_summary = ""
                if signal.reasoning:
                    reasoning_json = json.dumps(signal.reasoning.to_dict())
                    reasoning_summary = signal.reasoning.summary
                record = SignalRecord(
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    action=signal.action,
                    confidence=signal.confidence,
                    strength=signal.strength,
                    source=signal.source,
                    timestamp=signal.timestamp,
                    metadata_json=json.dumps(signal.metadata),
                    reasoning_json=reasoning_json,
                    reasoning_summary=reasoning_summary,
                )
                self.repository.save_signal(record)
            except Exception as exc:
                logger.error(
                    "Failed to save signal",
                    symbol=signal.symbol,
                    source=signal.source,
                    error=str(exc),
                )

    def _save_decision(self, decision: Decision) -> None:
        """Persist decision to database."""
        try:
            sources = ",".join(sorted(set(s.source for s in decision.signals)))
            record = DecisionRecord(
                symbol=decision.symbol,
                action=decision.action,
                score=decision.score,
                confidence=decision.confidence,
                signal_count=len(decision.signals),
                sources=sources,
                explanation=decision.explanation,
                timestamp=decision.timestamp,
            )
            self.repository.save_decision(record)
            logger.info("Decision saved to DB", symbol=decision.symbol, action=decision.action)
        except Exception as exc:
            logger.error("Failed to save decision", symbol=decision.symbol, error=str(exc))

    async def process_signals(self, signals: list[Signal], symbol: str) -> Decision:
        """Main pipeline: normalize → deduplicate → weight → score → decide → explain.

        Args:
            signals: List of raw signals from agents.
            symbol: Symbol being evaluated (e.g. "BTC/USDT").

        Returns:
            Decision object with action, score, confidence, and explanation.
        """
        logger.info("Processing signals", symbol=symbol, count=len(signals))

        if not signals:
            decision = Decision(
                symbol=symbol,
                action="hold",
                score=0.0,
                confidence=0.0,
                signals=[],
                explanation="No signals received",
            )
            self._save_decision(decision)
            return decision

        # Save individual signals with reasoning to DB
        self._save_signals(signals)

        normalized = [self.normalize_signal(s) for s in signals]
        deduped = self.deduplicate_signals(normalized)

        score = self.calculate_score(deduped)
        action = self.make_decision(score)
        confidence = self.calculate_confidence(deduped)

        decision = Decision(
            symbol=symbol,
            action=action,
            score=round(score, 4),
            confidence=round(confidence, 4),
            signals=deduped,
        )

        explanation = await self.generate_explanation(decision)
        decision.explanation = explanation

        self._save_decision(decision)

        logger.info(
            "Decision made",
            symbol=symbol,
            action=action,
            score=score,
            confidence=confidence,
            signal_count=len(deduped),
        )

        return decision
