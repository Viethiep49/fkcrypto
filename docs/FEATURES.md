# FKCrypto New Features Documentation

**Version:** 2.0.0
**Date:** 2026-04-01
**Status:** Production Ready

This document covers 5 new features added to FKCrypto to transform it from a "black box bot" into an "intelligent, transparent trading assistant."

---

## Table of Contents

1. [Explainable AI (Reasoning Log)](#1-explainable-ai-reasoning-log)
2. [Alpha Seeker Agent](#2-alpha-seeker-agent)
3. [Dynamic Position Sizing](#3-dynamic-position-sizing)
4. [Human-in-the-loop Approval](#4-human-in-the-loop-approval)
5. [Visual Backtest Replay](#5-visual-backtest-replay)

---

## 1. Explainable AI (Reasoning Log)

### Overview

Every signal emitted by an agent now carries structured reasoning — a list of `ReasoningFactor` objects explaining **why** the agent made that decision, plus a human-readable summary.

### Architecture

```
Agent Logic
    │
    ├─ Build ReasoningFactor list
    │   ├─ type: indicator/news/social/risk/pattern/event
    │   ├─ description: human-readable explanation
    │   ├─ impact: -1.0 to 1.0 (directional influence)
    │   └─ metadata: structured data
    │
    ├─ Build Reasoning object
    │   ├─ agent: which agent produced this
    │   ├─ factors: list[ReasoningFactor]
    │   ├─ summary: natural language summary
    │   └─ confidence: 0.0 to 1.0
    │
    └─ Attach to Signal.reasoning
```

### Files

| File | Description |
|---|---|
| `src/agents/reasoning.py` | `ReasoningFactor` and `Reasoning` dataclasses |
| `src/agents/signal.py` | Added `reasoning` field to Signal |
| `src/agents/analyst.py` | `_build_reasoning()` for technical analysis |
| `src/agents/news_sentiment.py` | `_build_sentiment_reasoning()` |
| `src/agents/risk_guardian.py` | Reasoning for kill switch, warnings |
| `src/agents/decision_engine.py` | `_save_signals()` persists reasoning to DB |
| `src/database/models.py` | Added `reasoning_json`, `reasoning_summary` columns |
| `dashboard/app.py` | "Agent Reasoning Log" panel |

### Reasoning Factor Types

| Type | Agent | Example |
|---|---|---|
| `indicator` | TechnicalAnalyst | "RSI quá bán (22 < 30) trên khung 1h" |
| `news` | NewsSentiment | "3/5 tin tức tích cực trong 30 phút qua" |
| `social` | NewsSentiment | "Cộng đồng ủng hộ (65% bullish)" |
| `risk` | RiskGuardian | "Sụt giảm danh mục 15% (ngưỡng 20%)" |
| `pattern` | TechnicalAnalyst | "Chiến lược 'mean-reversion': 3/4 điều kiện đạt" |
| `event` | AlphaSeeker | "Listing mới trên Binance cho SOL" |

### Database Schema

```sql
ALTER TABLE signals ADD COLUMN reasoning_json TEXT DEFAULT '{}';
ALTER TABLE signals ADD COLUMN reasoning_summary TEXT DEFAULT '';
```

### Dashboard

The **Agent Reasoning Log** panel displays:
- Expandable entries per signal showing agent name, action, confidence
- Natural language summary
- Detailed factor breakdown with directional arrows (↑↓→)

---

## 2. Alpha Seeker Agent

### Overview

A new agent that hunts for high-impact market events (Alpha Events) that can cause sudden price movements. These events often move prices **before** technical indicators react.

### Event Sources

| Source | Description | Priority |
|---|---|---|
| **Exchange Listings** | New token listings on Binance, OKX, Coinbase | IMMEDIATE |
| **Breaking News** | Hacks, exploits, regulation, partnerships | Varies |
| **Whale Movements** | Large deposits/withdrawals from exchanges | HIGH |
| **Influencer Signals** | Tweets from key figures (Elon, Vitalik, CZ) | HIGH |

### Event Priority Levels

| Priority | Event Types | Score Multiplier |
|---|---|---|
| `immediate` | Listings, hacks, exploits | 1.5x |
| `high` | Partnerships, whale movements, influencers | 1.2x |
| `medium` | Upgrades, mainnets, regulation | 1.0x |

### Integration with Decision Engine

Alpha signals are included in the weighted scoring pipeline. High-priority alpha signals receive a score boost that can override technical analysis:

```python
# In DecisionEngine.calculate_score()
if source == "alpha":
    for sig in source_signals:
        priority = sig.metadata.get("priority", "")
        if priority == "immediate":
            source_score *= 1.5  # Override boost
        elif priority == "high":
            source_score *= 1.2
```

### Files

| File | Description |
|---|---|
| `src/agents/alpha_seeker.py` | AlphaSeekerAgent class |
| `src/agents/signal.py` | Added `"alpha"` to VALID_SOURCES |
| `src/agents/decision_engine.py` | Alpha priority boost in scoring |
| `src/gateway/graph.py` | Added `alpha` node to workflow |
| `src/gateway/nodes.py` | `make_alpha_seeker_node()` |

### Configuration

```yaml
alpha_seeker:
  check_interval_sec: 60
  sources:
    exchange_news:
      enabled: true
    whale_alert:
      enabled: false
      api_key: ""
    influencer:
      enabled: false
      bearer_token: ""
  override:
    can_override_technical: true
    min_priority: "high"
  influencers:
    - "elonmusk"
    - "VitalikButerin"
    - "cz_binance"
```

### Signal Contract

Alpha signals use `source="alpha"` and include:

```python
Signal(
    symbol="SOL/USDT",
    timeframe="1m",
    action="buy",
    confidence=0.95,
    strength=0.8,
    source="alpha",
    metadata={
        "event_type": "listing",
        "priority": "immediate",
        "title": "Binance will list SOL/USDT",
        "source": "exchange_news",
        "can_override_ta": True,
    },
    reasoning=Reasoning(...),
)
```

---

## 3. Dynamic Position Sizing

### Overview

Position sizes are now calculated based on **signal convergence** — how much the agents agree on direction and confidence. Instead of a fixed 2% risk per trade, the system dynamically adjusts.

### Algorithm

```
Dynamic Risk = Base Risk × Convergence Factor

Convergence Factor = 1.0 + (agreement_score × avg_confidence × (1 + confidence_bonus)) + alpha_priority
```

### Components

| Component | Description |
|---|---|
| `agreement_score` | How many agents agree on direction (0.0 to 1.0) |
| `avg_confidence` | Average confidence of non-hold signals |
| `confidence_bonus` | Bonus from low variance in confidence (0.0 to 1.0) |
| `alpha_priority` | Extra boost for alpha signals (0.0 to 0.5) |

### Examples

| Scenario | Agents | Convergence | Result |
|---|---|---|---|
| **High agreement** | TA buy (80%), Sentiment buy (90%), Monitor bullish | ~1.5 | 2% × 1.5 = **3.0%** |
| **Mixed signals** | TA buy (60%), Sentiment sell (70%) | ~0.2 | 2% × 0.2 = **0.4%** |
| **Alpha event** | Alpha immediate + TA buy | ~2.0 | 2% × 2.0 = **4.0%** (capped at max) |
| **Single agent** | Only TA signal | ~1.0 | 2% × 1.0 = **2.0%** |

### Files

| File | Description |
|---|---|
| `src/risk/position_sizing.py` | `calculate_convergence_factor()`, `calculate_dynamic_size()` |

### API

```python
from src.risk.position_sizing import calculate_dynamic_size, calculate_convergence_factor

# Get convergence factor
factor = calculate_convergence_factor(signals)

# Calculate position size
result = calculate_dynamic_size(
    account_balance=10000.0,
    base_risk_pct=0.02,
    signals=signals,
    stop_loss_pct=0.05,
    max_size_pct=0.10,   # Max 10% of balance
    min_size_pct=0.005,  # Min 0.5% of balance
)

print(f"Size: ${result.size_usd}")
print(f"Risk: ${result.risk_usd}")
print(f"Convergence: {result.convergence_factor}")
```

### PositionSize Dataclass

```python
@dataclass
class PositionSize:
    size_usd: float              # Total position size in USD
    size_units: float            # Number of units (calculated at execution)
    risk_usd: float              # Amount at risk
    convergence_factor: float    # The convergence multiplier used
    base_risk_pct: float         # Original base risk percentage
```

---

## 4. Human-in-the-loop Approval

### Overview

When enabled, the system creates an **Approval Request** before executing any trade. The user can approve or reject via the Dashboard or Telegram. This gives you full control during the initial testing phase.

### Architecture

```
Decision Engine
    │
    ▼
Execution Service
    │
    ├─ approval_required? ──NO──→ Execute normally
    │
   YES
    │
    ▼
Create ApprovalRequest
    │
    ├─ Send to Dashboard/Telegram
    │
    ├─ Wait for response (timeout: 300s default)
    │   │
    │   ├─ APPROVED ──→ Execute order
    │   ├─ REJECTED ──→ Log rejection, skip
    │   └─ EXPIRED  ──→ Log timeout, skip
    │
    └─ In dry-run mode: auto-approve
```

### Approval Lifecycle

```
PENDING ──approve()──→ APPROVED
   │
   ├──reject()──→ REJECTED
   │
   └──timeout──→ EXPIRED
```

### Files

| File | Description |
|---|---|
| `src/execution/approval.py` | `ApprovalRequest`, `ApprovalManager` |
| `src/execution/service.py` | `_handle_approval()` integration |
| `src/database/models.py` | `ApprovalRecord` model |
| `dashboard/app.py` | Approval panel with approve/reject buttons |

### Configuration

```yaml
execution:
  dry_run: true
  approval:
    enabled: true          # Enable human-in-the-loop
    timeout_sec: 300       # 5 minutes to respond
```

### ApprovalRequest Fields

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique request ID (8-char UUID) |
| `symbol` | `str` | Trading pair |
| `action` | `str` | "buy" or "sell" |
| `score` | `float` | Decision score |
| `confidence` | `float` | Decision confidence |
| `size_usd` | `float` | Proposed position size |
| `reasoning_summary` | `str` | Why this decision was made |
| `sources` | `list[str]` | Signal sources involved |
| `status` | `ApprovalStatus` | pending/approved/rejected/expired |
| `timeout_sec` | `int` | Response timeout |

### Dashboard Panel

The **Phê duyệt lệnh** panel shows:
- Pending requests with score, confidence, sources
- Reasoning summary from the decision engine
- **✅ Duyệt** and **❌ Bỏ qua** buttons
- Approval history with status icons

---

## 5. Visual Backtest Replay

### Overview

Replay any past decision with full market context — see the candles, indicators, signals, and reasoning that led to each trade. This helps you understand **why** the bot made a decision and whether it was correct.

### Architecture

```
Decision Time
    │
    ├─ Capture MarketSnapshot
    │   ├─ OHLCV candles (lookback window)
    │   ├─ Indicator values
    │   ├─ All signals received
    │   ├─ News items available
    │   └─ Reasoning by agent
    │
    └─ Store in database

Replay Time
    │
    ├─ Load MarketSnapshot
    ├─ Build chart data (candles + indicators)
    ├─ Display decision context
    └─ Show outcome (PnL, duration, exit reason)
```

### Files

| File | Description |
|---|---|
| `src/backtesting/replay.py` | `MarketSnapshot`, `ReplayContext`, `build_replay_chart_data()` |
| `dashboard/app.py` | "Visual Backtest Replay" panel |

### MarketSnapshot

```python
@dataclass
class MarketSnapshot:
    decision_id: str
    symbol: str
    timestamp: datetime
    price: float
    candles: list[dict]          # OHLCV data
    indicators: dict             # Indicator values at decision time
    signals: list[dict]          # All signals received
    news_items: list[dict]       # News available at decision time
    reasoning: dict              # Per-agent reasoning
    metadata: dict               # Additional context
```

### ReplayContext

Combines snapshot with trade outcome for post-analysis:

```python
@dataclass
class ReplayContext:
    snapshot: MarketSnapshot
    decision_action: str
    decision_score: float
    decision_confidence: float
    entry_price: float
    exit_price: float
    pnl_pct: float
    duration_minutes: float
    exit_reason: str

    @property
    def is_profitable(self) -> bool
    @property
    def outcome_label(self) -> str   # "WIN", "LOSS", "NEUTRAL"
```

### Dashboard Panel

The **Visual Backtest Replay** panel provides:
- Dropdown to select any past decision
- Key metrics: symbol, action, score, confidence
- Decision engine explanation
- Related signals with reasoning summaries
- Signal sources breakdown

### Usage

```python
from src.backtesting.replay import create_snapshot_from_signals, build_replay_chart_data

# At decision time
snapshot = create_snapshot_from_signals(
    decision_id="abc123",
    symbol="BTC/USDT",
    timestamp=datetime.now(timezone.utc),
    price=65000.0,
    signals=signals,
    candles=candles,
    indicators=indicator_values,
    news_items=news,
)

# For replay
chart_data = build_replay_chart_data(
    snapshot=snapshot,
    lookback=50,
    show_bb=True,
    show_volume=True,
)
```

---

## Migration Guide

### Database Migrations

New columns added to existing tables:

```sql
-- Signals table
ALTER TABLE signals ADD COLUMN reasoning_json TEXT DEFAULT '{}';
ALTER TABLE signals ADD COLUMN reasoning_summary TEXT DEFAULT '';

-- New table for approval requests
CREATE TABLE approval_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id VARCHAR(32) NOT NULL UNIQUE,
    symbol VARCHAR(32) NOT NULL,
    action VARCHAR(8) NOT NULL,
    score FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    size_usd FLOAT DEFAULT 0.0,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    reasoning_summary TEXT DEFAULT '',
    sources TEXT DEFAULT '',
    created_at DATETIME NOT NULL,
    responded_at DATETIME,
    responder VARCHAR(32),
    rejection_reason TEXT DEFAULT ''
);
```

### Configuration Changes

Add these sections to your config:

```yaml
# Alpha Seeker (optional)
alpha_seeker:
  check_interval_sec: 60
  sources:
    exchange_news: { enabled: true }
    whale_alert: { enabled: false }
    influencer: { enabled: false }

# Human-in-the-loop (optional)
execution:
  approval:
    enabled: false   # Set to true to enable
    timeout_sec: 300
```

### Backward Compatibility

All new features are **backward compatible**:
- Signals without `reasoning` still work (reasoning defaults to `None`)
- Alpha source is optional — existing agents continue to work
- Dynamic position sizing is opt-in — use `calculate_dynamic_size()` instead of `calculate_position_size()`
- Human-in-the-loop is disabled by default (`approval.enabled: false`)

---

## Testing

### Unit Tests

Run the test suite:

```bash
pytest tests/ -v
```

### Testing Reasoning

```python
from src.agents.reasoning import Reasoning, ReasoningFactor
from src.agents.signal import Signal

# Create a signal with reasoning
reasoning = Reasoning(
    agent="technical_analyst",
    confidence=0.85,
    summary="RSI oversold with MACD bullish divergence",
    factors=[
        ReasoningFactor(
            type="indicator",
            description="RSI at 22 (oversold)",
            impact=0.15,
        ),
        ReasoningFactor(
            type="indicator",
            description="MACD bullish divergence on 1H",
            impact=0.10,
        ),
    ],
)

signal = Signal(
    symbol="BTC/USDT",
    timeframe="1h",
    action="buy",
    confidence=0.85,
    strength=0.5,
    source="technical",
    reasoning=reasoning,
)

# Serialize and deserialize
data = signal.to_dict()
assert "reasoning" in data
restored = Signal.from_dict(data)
assert restored.reasoning.summary == reasoning.summary
```

### Testing Dynamic Sizing

```python
from src.risk.position_sizing import calculate_dynamic_size, calculate_convergence_factor

# High convergence scenario
signals = [
    Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.8, source="technical"),
    Signal(symbol="BTC/USDT", timeframe="1h", action="buy", confidence=0.9, source="sentiment"),
]

factor = calculate_convergence_factor(signals)
assert factor > 1.0  # Should boost position size

result = calculate_dynamic_size(
    account_balance=10000.0,
    base_risk_pct=0.02,
    signals=signals,
)
assert result.convergence_factor > 1.0
assert result.size_usd > 0
```

### Testing Approval Flow

```python
from src.execution.approval import ApprovalManager, ApprovalStatus

manager = ApprovalManager(enabled=True, timeout_sec=60)

# Create request
request = await manager.create_request(
    symbol="BTC/USDT",
    action="buy",
    score=0.7,
    confidence=0.8,
)
assert request.status == ApprovalStatus.PENDING

# Approve
approved = await manager.approve(request.id)
assert approved.status == ApprovalStatus.APPROVED

# Reject (new request)
request2 = await manager.create_request(
    symbol="ETH/USDT",
    action="sell",
    score=-0.6,
    confidence=0.7,
)
rejected = await manager.reject(request2.id, reason="Too risky")
assert rejected.status == ApprovalStatus.REJECTED
```
