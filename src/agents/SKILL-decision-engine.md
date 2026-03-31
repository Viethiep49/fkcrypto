---
name: decision-engine
description: "Central decision engine — aggregates signals from all agents, applies weighted scoring, and produces final trade decisions"
version: "1.0"
type: engine
---

# Decision Engine

The central brain of the trading system. Aggregates signals from all agents, applies weighted scoring, and produces final trade decisions. **Deterministic and reproducible.**

## Role

You are the **Decision Engine** — the judge of the trading system. You weigh evidence from all agents and make the final call. Your decisions must be explainable and reproducible.

## Core Principles

1. **Deterministic** — Same inputs always produce same outputs
2. **Weighted** — Different signal sources have different weights
3. **Transparent** — Every decision is logged with full reasoning
4. **LLM-restricted** — LLM only explains decisions, never makes them

## Signal Aggregation Pipeline

```
┌──────────────┐
│ Raw Signals  │  ← From all agents via Redis
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Normalize    │  ← Clamp confidence, validate schema
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Deduplicate  │  ← Merge duplicate signals per symbol
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Weight       │  ← Apply source weights
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Score        │  ← Calculate weighted score
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Decide       │  ← Apply thresholds → buy/sell/hold
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Explain      │  ← LLM generates explanation (optional)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ To Execution │  ← Forward to Execution Service
└──────────────┘
```

## Signal Normalization

```python
def normalize_signal(signal: Signal) -> Signal:
    """Clamp and validate signal values."""
    signal.confidence = max(0.0, min(1.0, signal.confidence))
    signal.strength = max(-1.0, min(1.0, signal.strength))
    return signal
```

## Weighted Scoring

```python
# Default weights (configurable)
SOURCE_WEIGHTS = {
    "technical": 0.40,
    "sentiment": 0.25,
    "momentum": 0.20,
    "risk": 0.15,
}

def calculate_score(signals: list[Signal], weights: dict = None) -> float:
    """
    Calculate weighted score from signals.

    Returns:
        float: -1.0 (strong sell) to +1.0 (strong buy)
    """
    weights = weights or SOURCE_WEIGHTS

    if not signals:
        return 0.0

    # Group by source
    by_source: dict[str, list[Signal]] = {}
    for s in signals:
        by_source.setdefault(s.source, []).append(s)

    weighted_sum = 0.0
    total_weight = 0.0

    for source, source_signals in by_source.items():
        w = weights.get(source, 0.1)
        # Average signal direction for this source
        directions = []
        for s in source_signals:
            direction = 1.0 if s.action == "buy" else (-1.0 if s.action == "sell" else 0.0)
            directions.append(direction * s.confidence)
        source_score = sum(directions) / len(directions) if directions else 0.0

        weighted_sum += w * source_score
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

## Decision Rule

```python
BUY_THRESHOLD = 0.7
SELL_THRESHOLD = -0.7

def make_decision(score: float) -> str:
    """Convert score to action."""
    if score > BUY_THRESHOLD:
        return "buy"
    elif score < SELL_THRESHOLD:
        return "sell"
    return "hold"
```

## Confidence Calculation

```python
def calculate_confidence(signals: list[Signal]) -> float:
    """Calculate aggregate confidence."""
    if not signals:
        return 0.0

    # Weighted average of confidence
    total_confidence = sum(s.confidence for s in signals)
    base_confidence = total_confidence / len(signals)

    # Boost if signals agree
    actions = [s.action for s in signals]
    if len(set(actions)) == 1 and actions[0] != "hold":
        # All signals agree
        return min(base_confidence + 0.15, 0.95)

    return base_confidence
```

## Decision Output

```python
@dataclass
class Decision:
    symbol: str
    action: str              # "buy", "sell", "hold"
    score: float             # -1.0 to 1.0
    confidence: float        # 0.0 to 1.0
    signals: list[Signal]    # Input signals
    explanation: str = ""    # LLM-generated explanation
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
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
```

## LLM Explanation (Optional)

LLM generates human-readable explanation **after** decision is made:

```python
EXPLANATION_PROMPT = """
Explain this trading decision in 2-3 sentences for a dashboard display.

Decision: {action} {symbol}
Score: {score}
Confidence: {confidence}
Signals: {signal_summary}

Be concise. Focus on the key reasons.
"""
```

## Configuration

```yaml
decision_engine:
  weights:
    technical: 0.40
    sentiment: 0.25
    momentum: 0.20
    risk: 0.15
  thresholds:
    buy: 0.7
    sell: -0.7
  confidence_boost:
    agreement_bonus: 0.15
    max_confidence: 0.95
  explanation:
    enabled: true
    model: "gpt-4o-mini"
    max_tokens: 200
```

## Error Handling

- **No signals received**: Emit hold decision with confidence 0.0
- **Invalid signal**: Log and skip, don't crash
- **LLM explanation failure**: Decision still valid, explanation = "N/A"

## Output

- Decisions to Redis pub/sub channel: `fkcrypto:decisions`
- Decisions to database for audit trail
- Metrics to Prometheus: `decisions_total`, `decision_score_distribution`, `decision_latency_ms`
