# FKCrypto Multi-Agent System — Architecture Reference

> Production-grade autonomous cryptocurrency trading system built on a multi-agent architecture.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Signal Contract](#2-signal-contract)
3. [Agent Hierarchy](#3-agent-hierarchy)
4. [BaseAgent](#4-baseagent)
5. [TechnicalAnalystAgent](#5-technicalanalystagent)
6. [MarketMonitorAgent](#6-marketmonitoragent)
7. [NewsSentimentAgent](#7-newssentimentagent)
8. [RiskGuardianAgent](#8-riskguardianagent)
9. [DecisionEngine](#9-decisionengine)
10. [Risk Engine](#10-risk-engine)
11. [Position Sizing](#11-position-sizing)
12. [Execution Pipeline](#12-execution-pipeline)
13. [Freqtrade Client](#13-freqtrade-client)
14. [Data Flow](#14-data-flow)
15. [Configuration Reference](#15-configuration-reference)

---

## 1. System Overview

FKCrypto is a modular, multi-agent trading system where specialized agents analyze market data independently, emit standardized **Signal** objects, and feed them into a central **DecisionEngine** that produces executable trade decisions. Every decision passes through a **Risk Engine** and **Execution Service** before reaching the exchange via **Freqtrade**.

### Design Principles

| Principle | Description |
|---|---|
| **Deterministic decisions** | Same inputs always produce same outputs. LLM is never used for decision-making — only for explanation and NLP classification. |
| **Defense in depth** | Multiple independent risk layers: RiskGuardianAgent (monitoring), RiskEngine (pre-trade validation), ExecutionService (rate limiting, auditing). |
| **Fail-safe** | Kill switch authority, graceful degradation (rule-based fallback when LLM unavailable), error-wrapped agent execution. |
| **Immutable signals** | Signal objects are validated on construction and carry full provenance metadata. |
| **Audit trail** | Every order attempt — successful or rejected — is persisted to the database. |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FKCrypto System                              │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ TechnicalAnalyst │  │  MarketMonitor   │  │ NewsSentiment    │  │
│  │     Agent        │  │     Agent        │  │    Agent         │  │
│  │                  │  │                  │  │                  │  │
│  │  • 12 indicators │  │  • Price spikes  │  │  • CryptoPanic   │  │
│  │  • YAML strategy │  │  • Volume anom.  │  │  • SerpAPI       │  │
│  │  • MTF confirm   │  │  • OB imbalance  │  │  • LunarCrush    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │                     │             │
│           │  Signal             │  Signal             │  Signal     │
│           │  (technical)        │  (momentum)         │  (sentiment)│
│           ▼                     ▼                     ▼             │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Signal Bus                                  │  │
│  │              list[Signal] → DecisionEngine                     │  │
│  └───────────────────────────────┬───────────────────────────────┘  │
│                                  │                                   │
│                                  │ Decision                          │
│                                  ▼                                   │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              ExecutionService                                  │  │
│  │                                                                │  │
│  │  validate → risk check → rate limit → audit → Freqtrade       │  │
│  └───────────────────────────────┬───────────────────────────────┘  │
│                                  │                                   │
│           ┌──────────────────────┼──────────────────────┐           │
│           │                      │                      │           │
│  ┌────────▼────────┐   ┌────────▼────────┐   ┌─────────▼────────┐  │
│  │  RiskGuardian   │   │   RiskEngine    │   │  FreqtradeClient │  │
│  │    Agent        │   │                 │   │                  │  │
│  │                 │   │  • Kill switch  │   │  • Bearer auth   │  │
│  │  • Drawdown     │   │  • Stop-loss    │   │  • 3 retries     │  │
│  │  • Daily loss   │   │  • Position lim │   │  • Rate limit    │  │
│  │  • Kill switch  │   │  • Exposure     │   │  • Context mgr   │  │
│  └─────────────────┘   └─────────────────┘   └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Signal Contract

The **Signal** dataclass (`src/agents/signal.py`) is the universal contract between all agents and the Decision Engine. Every agent must emit signals conforming to this schema.

### Schema

| Field | Type | Range | Description |
|---|---|---|---|
| `symbol` | `str` | — | Trading pair, e.g. `"BTC/USDT"` |
| `timeframe` | `str` | — | Candle interval, e.g. `"1m"`, `"5m"`, `"1h"`, `"4h"`, `"1d"` |
| `action` | `Literal["buy","sell","hold"]` | — | Recommended action |
| `confidence` | `float` | `0.0` – `1.0` | How confident the agent is in this signal |
| `strength` | `float` | `-1.0` – `1.0` | Magnitude and direction of the signal |
| `source` | `str` | See below | Signal source category |
| `timestamp` | `datetime` | UTC | When the signal was created |
| `metadata` | `dict[str, Any]` | — | Arbitrary context (indicators, event type, etc.) |

### Valid Sources

```
"technical"   — TechnicalAnalystAgent
"sentiment"   — NewsSentimentAgent
"momentum"    — MarketMonitorAgent
"risk"        — RiskGuardianAgent
"ml"          — Future ML agents
"on-chain"    — Future on-chain analysis agents
```

### Validation

Signals are validated in `__post_init__`. Invalid values raise `ValueError` immediately:

```python
Signal(symbol="", ...)        # ValueError: symbol must be a non-empty string
Signal(action="long", ...)    # ValueError: action must be one of ('buy', 'sell', 'hold')
Signal(confidence=1.5, ...)   # ValueError: confidence must be 0.0-1.0, got 1.5
Signal(source="news", ...)    # ValueError: source must be one of VALID_SOURCES
```

### Helper Methods

| Method | Returns | Description |
|---|---|---|
| `direction()` | `float` | `1.0` for buy, `-1.0` for sell, `0.0` for hold |
| `weighted_score()` | `float` | `direction() * confidence` — used in scoring |
| `to_dict()` | `dict` | Serialize to dictionary (ISO timestamp) |
| `from_dict(data)` | `Signal` | Class method to reconstruct from dict |

---

## 3. Agent Hierarchy

```
BaseAgent (ABC)
├── TechnicalAnalystAgent    — Technical indicator analysis + YAML strategies
├── MarketMonitorAgent       — Real-time anomaly detection
├── NewsSentimentAgent       — News/social sentiment with LLM classification
└── RiskGuardianAgent        — Portfolio risk monitoring + kill switch

DecisionEngine (not an agent — orchestrator)
├── Normalizes signals
├── Deduplicates
├── Weighted scoring
├── Threshold-based decision
└── LLM explanation
```

All agents inherit from `BaseAgent` and implement the `run()` method returning `list[Signal]`.

---

## 4. BaseAgent

**File:** `src/agents/base.py`

Abstract base class providing shared infrastructure for all agents.

### Capabilities

| Capability | Method/Property | Description |
|---|---|---|
| Structured logging | `self._logger` | `structlog` logger bound to agent name |
| Error handling | `safe_run()` | Wraps `run()` — catches all exceptions, returns `[]` on failure |
| Signal emission | `emit_signals()` | Validates, logs, and returns signals |
| Lifecycle | `is_running`, `stop()` | Start/stop state management |

### Usage Pattern

```python
class MyAgent(BaseAgent):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="my_agent", config=config)
        # agent-specific initialization

    async def run(self) -> list[Signal]:
        # core logic — return signals
        return signals
```

### Safe Run Flow

```
safe_run()
├── Set _running = True
├── Call run()
│   └── On CancelledError: re-raise after cleanup
│   └── On Exception: log error, return []
├── Call emit_signals()
│   └── Log each signal
│   └── Skip invalid signals with warning
└── Return validated signals
```

---

## 5. TechnicalAnalystAgent

**File:** `src/agents/analyst.py`

Computes technical indicators from OHLCV data and evaluates YAML-defined strategies.

### Responsibilities

1. Compute 12+ technical indicators from raw candle data
2. Load and validate YAML strategy files from `config/strategies/`
3. Evaluate entry/exit conditions against computed indicators
4. Apply multi-timeframe confirmation boosts
5. Emit `Signal` objects with `source="technical"`

### Technical Indicators

| Indicator | Method | Default Parameters |
|---|---|---|
| **RSI** | `_compute_rsi()` | Period: 14 |
| **MACD** | `_compute_macd()` | Fast: 12, Slow: 26, Signal: 9 |
| **EMA (fast)** | `_compute_ema()` | Period: 20 |
| **EMA (slow)** | `_compute_ema()` | Period: 50 |
| **EMA (200)** | `_compute_ema()` | Period: 200 |
| **Bollinger Bands** | `_compute_bollinger_bands()` | Period: 20, StdDev: 2.0 |
| **ATR** | `_compute_atr()` | Period: 14 |
| **Volume SMA** | `_compute_ema()` | Period: 20 |
| **Stochastic %K** | `_compute_stochastic()` | K: 14, D: 3 |
| **Stochastic %D** | `_compute_stochastic()` | EMA of %K |
| **ADX** | `_compute_adx()` | Period: 14 |
| **Donchian Channel** | `_compute_donchian()` | Period: 20 |

### Strategy Loading

Strategies are loaded from YAML files in `config/strategies/`. Required fields:

```yaml
name: "mean-reversion"
enabled: true
timeframes: ["15m", "1h"]

entry:
  min_conditions: 2
  conditions:
    - indicator: "RSI"
      rule: "value < 30"
    - indicator: "BollingerBands"
      rule: "price <= lower_band"
    - indicator: "Volume"
      rule: "current > sma * 1.5"

exit:
  min_conditions: 1
  conditions:
    - indicator: "RSI"
      rule: "value > 65"
    - indicator: "BollingerBands"
      rule: "price >= middle_band"

confidence:
  base: 0.55
  max_confidence: 0.90
  boosters:
    - condition: "volume > sma * 2.0"
      bonus: 0.10
    - condition: "price > EMA200"
      bonus: 0.05
```

### Confidence Calculation

```
confidence = min(base + sum(booster bonuses), max_confidence)
strength   = min((conditions_met / total_conditions) * 1.5, 1.0)
```

### Multi-Timeframe Confirmation

When enabled (`mtf_enabled: true`), if the same action (buy/sell) is triggered across multiple timeframes for the same symbol, confidence is boosted:

```python
if multiple_buy_signals_across_timeframes:
    signal.confidence += mtf_boost  # default: 0.15
    signal.confidence = min(confidence, 0.95)
```

### Configuration

```yaml
analyst:
  timeframes: ["15m", "1h", "4h"]
  indicators:
    rsi: { period: 14 }
    ema: { fast: 20, slow: 50 }
    macd: { fast: 12, slow: 26, signal: 9 }
    bollinger: { period: 20, std: 2.0 }
    atr: { period: 14 }
    volume_sma: { period: 20 }
    stochastic: { k: 14, d: 3 }
    adx: { period: 14 }
    donchian: { period: 20 }
  multi_timeframe:
    enabled: true
    confirmation_boost: 0.15
```

---

## 6. MarketMonitorAgent

**File:** `src/agents/market_monitor.py`

Real-time market monitoring with anomaly detection. Runs continuous monitoring loops at configurable intervals.

### Responsibilities

1. Detect price spikes, volume anomalies, order book imbalances, and flash crashes
2. Maintain rolling price/volume history per symbol
3. Emit `Signal` objects with `source="momentum"` when anomalies detected
4. Support continuous monitoring mode via `start_monitoring()`

### Detectors

| Detector | Threshold | Signal Action | Confidence |
|---|---|---|---|
| **Price Spike** | >2% in 5 min window | buy/sell (direction of move) | `min(|change%| / (threshold * 2), 0.95)` |
| **Volume Anomaly** | >3 std dev above mean | buy/sell (price direction) | `min(deviation / (multiplier * 2), 0.90)` |
| **Order Book Imbalance** | bid/ask ratio >3.0 or <0.33 | buy (bid dominant) / sell (ask dominant) | `min((ratio-1) / (threshold * 2), 0.85)` |
| **Flash Crash** | >5% drop in 1 min | sell | 0.95 (fixed) |

### Rolling History

```python
_price_history: dict[str, deque]   # [(timestamp, price), ...]
_volume_history: dict[str, deque]  # [volume, ...]
_last_prices: dict[str, float]     # symbol -> latest price
```

### Configuration

```yaml
market_monitor:
  check_interval_sec: 5
  price_spike:
    threshold_pct: 2.0
    window_sec: 300
  volume_anomaly:
    std_multiplier: 3.0
    lookback_periods: 20
  order_book:
    depth: 20
    imbalance_ratio: 3.0
    wall_threshold_btc: 100
```

---

## 7. NewsSentimentAgent

**File:** `src/agents/news_sentiment.py`

Analyzes crypto news and social media sentiment using LLM classification.

### Responsibilities

1. Fetch news from CryptoPanic and SerpAPI
2. Fetch social sentiment and volume from LunarCrush
3. Use LLM to classify sentiment from news headlines
4. Calculate weighted composite sentiment score
5. Emit `Signal` objects with `source="sentiment"`

### Data Sources

| Source | Data Type | API |
|---|---|---|
| **CryptoPanic** | Crypto news headlines | `get_crypto_news(currencies, limit)` |
| **SerpAPI** | General web news | `search_news(query, limit)` |
| **LunarCrush** | Social metrics | `get_sentiment(symbol)`, `get_social_volume(symbol)` |

### LLM Sentiment Classification

The LLM is prompted to return structured JSON:

```json
{
  "sentiment_score": -0.3,
  "confidence": 0.75,
  "key_factors": ["regulatory uncertainty", "ETF inflows"],
  "summary": "Mixed signals with cautious optimism"
}
```

Sentiment scale: `-1.0` (extremely bearish) to `+1.0` (extremely bullish).

### Weighted Sentiment Score

```
score = (llm_weight * llm_score)
      + (news_ratio_weight * (news_ratio * 2 - 1))
      + (social_volume_weight * (social_volume * 2 - 1))
      + (fear_greed_weight * ((fear_greed - 50) / 50))
```

| Component | Weight | Range |
|---|---|---|
| LLM classification | 40% | -1.0 to 1.0 |
| News ratio (positive/total) | 25% | -1.0 to 1.0 (mapped from 0-1) |
| Social volume | 20% | -1.0 to 1.0 (mapped from 0-1) |
| Fear & Greed index | 15% | -1.0 to 1.0 (mapped from 0-100) |

### Fallback

When LLM is unavailable, falls back to rule-based sentiment:

```python
score = 0.6 * avg_news_sentiment + 0.4 * social_sentiment
```

### Decision Thresholds

| Condition | Action |
|---|---|
| `sentiment_score >= 0.5` | buy |
| `sentiment_score <= -0.5` | sell |
| Otherwise | hold |

### Configuration

```yaml
sentiment:
  schedule: "0 * * * *"
  news_max_age_hours: 24
  sources:
    cryptopanic: { enabled: true, api_key: "..." }
    serpapi: { enabled: true, api_key: "..." }
    lunarcrush: { enabled: true, api_key: "..." }
  llm:
    model: "gpt-4o-mini"
    max_tokens: 500
    temperature: 0.1
  thresholds:
    strong_bullish: 0.5
    strong_bearish: -0.5
    min_news_count: 3
```

---

## 8. RiskGuardianAgent

**File:** `src/agents/risk_guardian.py`

Real-time risk monitoring agent with kill switch authority. The last line of defense before the RiskEngine.

### Responsibilities

1. Monitor portfolio drawdown and daily loss limits
2. Check position limits and exposure
3. Detect ATR volatility spikes
4. Monitor API/exchange health
5. Trigger kill switch when critical thresholds breached
6. Emit `Signal` objects with `source="risk"`

### Risk Checks

| Check | Default Threshold | Action on Breach |
|---|---|---|
| **Portfolio Drawdown** | >20% from peak | Kill switch |
| **Daily Loss** | >5% from day start | Kill switch |
| **Max Positions** | >5 open positions | Warning signal |
| **Max Exposure** | >30% of portfolio | Warning signal |
| **Loss Per Position** | >10% unrealized loss | Warning signal |
| **ATR Volatility Spike** | >3x average ATR | Warning; >6x → Kill switch |
| **API Consecutive Errors** | >10 errors | Kill switch |

### Warning Zone

Checks emit warning signals at **75% of threshold** before triggering the kill switch:

```
0% ───────── 75% ──────── 100%
             ↑              ↑
         Warning        Kill Switch
```

### Kill Switch

```python
# Triggered automatically when:
# - Drawdown > max_drawdown_pct
# - Daily loss > max_daily_loss_pct
# - >= 3 position limit violations
# - ATR spike > 6x average
# - >= 10 consecutive API errors

signal = Signal(
    symbol="ALL",
    timeframe="1m",
    action="sell",
    confidence=1.0,
    strength=-1.0,
    source="risk",
    metadata={
        "event": "kill_switch",
        "reason": "...",
        "emergency": True,
        "auto_close": True,
        "manual_reset_required": True,
    },
)
```

### Kill Switch Properties

| Property | Default | Description |
|---|---|---|
| `auto_close_positions` | `True` | Automatically close all positions |
| `manual_reset_required` | `True` | Requires manual `reset_kill_switch()` call |
| `notification_channels` | `[]` | Channels to alert on activation |

### Configuration

```yaml
risk_guardian:
  check_interval_sec: 30
  limits:
    max_drawdown_pct: 0.20
    max_daily_loss_pct: 0.05
    max_positions: 5
    max_exposure_pct: 0.30
    max_loss_per_position: 0.10
  kill_switch:
    enabled: true
    auto_close_positions: true
    manual_reset_required: true
    notification_channels: []
  volatility:
    atr_spike_multiplier: 3.0
  api_health:
    max_consecutive_errors: 10
    check_interval_sec: 60
```

---

## 9. DecisionEngine

**File:** `src/agents/decision_engine.py`

Central orchestrator that aggregates signals from all agents and produces final trade decisions. **Deterministic** — same inputs always produce same outputs.

### Pipeline

```
Signals → Normalize → Deduplicate → Weighted Score → Decision → Explanation → Persist
```

### Step 1: Normalize

Clamps confidence to `[0, 1]` and strength to `[-1, 1]`:

```python
signal.confidence = max(0.0, min(1.0, signal.confidence))
signal.strength = max(-1.0, min(1.0, signal.strength))
```

### Step 2: Deduplicate

Removes duplicate signals from the same `(symbol, source, timeframe)`. Keeps the latest signal.

```python
key = (signal.symbol, signal.source, signal.timeframe)
```

### Step 3: Weighted Scoring

Signals are grouped by source. Each source contributes a weighted score:

| Source | Default Weight |
|---|---|
| `technical` | 30% |
| `sentiment` | 20% |
| `momentum` | 20% |
| `risk` | 15% |
| `ml` | 10% |
| `on-chain` | 5% |

**Scoring formula per source:**

```
source_score = avg(direction * confidence) for all signals in source
  where direction = 1.0 (buy), -1.0 (sell), 0.0 (hold)

final_score = sum(source_weight * source_score) / sum(source_weights)
```

Output range: `-1.0` (strong sell) to `+1.0` (strong buy).

### Step 4: Decision Thresholds

| Score Range | Decision |
|---|---|
| `score >= 0.6` | **buy** |
| `score <= -0.6` | **sell** |
| `-0.6 < score < 0.6` | **hold** |

### Step 5: Confidence Calculation

```
base_confidence = avg(signal.confidence for all signals)

if all non-hold signals agree on same action:
    confidence = min(base_confidence + 0.15, 0.95)
else:
    confidence = base_confidence
```

Minimum confidence threshold: `0.5`.

### Step 6: LLM Explanation (Optional)

LLM generates a 2-3 sentence human-readable explanation for dashboard display. Non-blocking with 10-second timeout. Falls back to `"N/A"` on failure.

**LLM is never used for decision-making — only for explanation.**

### Step 7: Persistence

Decisions are saved to the database as `DecisionRecord` with all metadata.

### Decision Dataclass

```python
@dataclass
class Decision:
    symbol: str
    action: str           # "buy", "sell", "hold"
    score: float          # -1.0 to 1.0
    confidence: float     # 0.0 to 1.0
    signals: list[Signal] # contributing signals
    explanation: str      # LLM-generated or "N/A"
    timestamp: datetime
```

### Configuration

```yaml
decision:
  weights:
    technical: 0.30
    sentiment: 0.20
    momentum: 0.20
    risk: 0.15
    ml: 0.10
    on-chain: 0.05
  thresholds:
    buy: 0.6
    sell: -0.6
    min_confidence: 0.5
  confidence_boost:
    agreement_bonus: 0.15
    max_confidence: 0.95
  explanation:
    enabled: true
```

---

## 10. Risk Engine

**File:** `src/risk/engine.py`

Independent risk validation layer. **Never bypassed** — every order must pass risk checks before execution.

### Validation Checks (in order)

| # | Check | Description |
|---|---|---|
| 1 | **Kill Switch** | Rejects all orders if kill switch is active |
| 2 | **Stop Loss** | Mandatory — order must have `stop_loss` set |
| 3 | **Order Size** | Must not exceed `balance * risk_per_trade / stop_loss_pct` |
| 4 | **Max Positions** | Cannot exceed configured maximum (default: 5) |
| 5 | **Daily Loss** | Cannot exceed daily loss limit (default: 5%) |
| 6 | **Drawdown** | Cannot exceed max drawdown (default: 15%) |
| 7 | **Exposure** | New exposure cannot exceed max exposure (default: 50%) |

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool
    reason: str = ""
```

### Default Configuration

```yaml
risk:
  max_positions: 5
  risk_per_trade: 0.02        # 2% of balance
  max_exposure: 0.5           # 50% of balance
  stop_loss: 0.05             # 5% stop loss
  max_daily_loss: 0.05        # 5% daily loss limit
  max_drawdown: 0.15          # 15% max drawdown
```

---

## 11. Position Sizing

**File:** `src/risk/position_sizing.py`

Risk-based position sizing utilities.

### calculate_position_size()

```
position_size = (account_balance * risk_per_trade) / stop_loss_pct
```

**Example:** $10,000 balance, 2% risk, 5% stop loss:
```
position_size = (10000 * 0.02) / 0.05 = $4,000
```

### calculate_stop_loss()

ATR-based stop loss:

```
stop_loss = price - (atr * multiplier)
```

Default multiplier: `2.0`.

### calculate_take_profit()

Risk-reward ratio based:

```
take_profit = entry + (stop_distance * risk_reward_ratio)
```

Example with 2:1 risk/reward:
```
stop_distance = entry - stop_loss
take_profit = entry + (stop_distance * 2.0)
```

### apply_trailing_stop()

Trailing stop with activation threshold:

```python
# Not activated until price gains activation_pct
gain_pct = (highest_price - entry_price) / entry_price
is_activated = gain_pct >= activation_pct

if is_activated:
    trailing_stop = highest_price * (1.0 - trail_pct)
```

### check_exposure()

```python
is_within_limits, exposure_usd, exposure_pct = check_exposure(
    positions=positions,
    max_exposure_pct=0.5,
    total_balance=10000.0,
)
```

---

## 12. Execution Pipeline

**File:** `src/execution/service.py`

Orchestrates order execution with multiple safety layers.

### Execution Flow

```
Decision
  │
  ├─ 1. Skip holds (return success immediately)
  │
  ├─ 2. OrderValidator
  │     ├─ Symbol format (BASE/QUOTE)
  │     ├─ Action validation (buy/sell)
  │     ├─ Size limits ($1 - $100,000)
  │     ├─ Duplicate detection
  │     └─ Precision sanitization
  │
  ├─ 3. RiskEngine.validate_order()
  │     ├─ Kill switch check
  │     ├─ Stop loss mandatory
  │     ├─ Size limits
  │     ├─ Max positions
  │     ├─ Daily loss
  │     ├─ Drawdown
  │     └─ Exposure
  │
  ├─ 4. RateLimiter
  │     └─ Max orders per symbol per minute (default: 10)
  │
  ├─ 5. Audit Log (database)
  │
  └─ 6. FreqtradeClient.create_order()
        └─ Forward to Freqtrade REST API
```

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    success: bool
    order_id: str = ""
    message: str = ""
    rejected_reason: str = ""
```

### RateLimiter

Tracks order submissions per symbol per rolling 60-second window:

```python
rate_limiter = RateLimiter(max_orders_per_minute=10)
allowed, reason = rate_limiter.check("BTC/USDT")
rate_limiter.record("BTC/USDT")
```

### OrderValidator

**File:** `src/execution/validator.py`

| Check | Rule |
|---|---|
| Symbol format | Must match `^[A-Z0-9]+/[A-Z0-9]+$` |
| Action | Must be `"buy"` or `"sell"` |
| Size | Must be positive, between `$1` and `$100,000` |
| Duplicate | No recent identical `(symbol:action:size)` |
| Precision | Rounds to 8 decimal places |

### OrderRequest

```python
@dataclass
class OrderRequest:
    symbol: str
    action: str
    size_usd: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    decision_id: Optional[int] = None
```

---

## 13. Freqtrade Client

**File:** `src/freqtrade_client/client.py`

Async HTTP client for the Freqtrade REST API.

### Features

| Feature | Implementation |
|---|---|
| **Authentication** | Bearer token via `Authorization` header |
| **Retries** | 3 retries with exponential backoff (`2^attempt` seconds) |
| **Rate Limit Handling** | Respects `Retry-After` header on 429 responses |
| **Server Errors** | Retries on 5xx with exponential backoff |
| **Context Manager** | Supports `async with FreqtradeClient(...) as client:` |
| **Timeout** | Configurable (default: 30s) |

### API Methods

| Method | HTTP | Endpoint | Description |
|---|---|---|---|
| `ping()` | GET | `/api/v1/ping` | Health check |
| `create_order()` | POST | `/api/v1/open_trades` | Place order |
| `get_open_orders()` | GET | `/api/v1/open_trades` | List open orders |
| `cancel_order(id)` | DELETE | `/api/v1/trades/{id}` | Cancel order |
| `get_balance()` | GET | `/api/v1/balance` | Account balance |
| `get_performance()` | GET | `/api/v1/performance` | Trading performance |
| `force_entry()` | POST | `/api/v1/forceentry` | Force buy entry |
| `force_exit()` | POST | `/api/v1/forceexit` | Force close trade |

### Usage

```python
async with FreqtradeClient(
    base_url="http://localhost:8080",
    api_key="your-api-key",
    timeout=30.0,
    max_retries=3,
) as client:
    if await client.ping():
        result = await client.create_order(
            symbol="BTC/USDT",
            action="buy",
            amount=0.001,
        )
```

### Error Handling

```python
class FreqtradeAPIError(Exception):
    """Raised when a Freqtrade API request fails after retries."""
    status_code: Optional[int]
```

---

## 14. Data Flow

### End-to-End Signal-to-Trade Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  SCHEDULED CYCLE (e.g., every 15 minutes)                                   │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │ Technical   │    │  Market     │    │   News      │                     │
│  │ Analyst     │    │  Monitor    │    │  Sentiment  │                     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                     │
│         │                  │                  │                              │
│    [Signal]           [Signal]           [Signal]                           │
│    source=            source=            source=                            │
│    "technical"        "momentum"         "sentiment"                        │
│         │                  │                  │                              │
│         └──────────────────┼──────────────────┘                              │
│                            │                                                 │
│                     ┌──────▼──────┐                                          │
│                     │  Decision   │                                          │
│                     │   Engine    │                                          │
│                     └──────┬──────┘                                          │
│                            │                                                 │
│                      [Decision]                                              │
│                  action=buy/sell/hold                                        │
│                  score=0.72                                                  │
│                  confidence=0.85                                             │
│                            │                                                 │
│                     ┌──────▼──────┐                                          │
│                     │ Execution   │──if hold──→ Done                        │
│                     │  Service    │                                          │
│                     └──────┬──────┘                                          │
│                            │                                                 │
│                     ┌──────▼──────┐                                          │
│                     │   Risk      │──if fail──→ Audit log (rejected)        │
│                     │   Engine    │                                          │
│                     └──────┬──────┘                                          │
│                            │                                                 │
│                     ┌──────▼──────┐                                          │
│                     │  Freqtrade  │──if fail──→ Audit log (rejected)        │
│                     │   Client    │                                          │
│                     └──────┬──────┘                                          │
│                            │                                                 │
│                     ┌──────▼──────┐                                          │
│                     │  Audit Log  │ (all attempts persisted)                │
│                     └─────────────┘                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  CONTINUOUS MONITORING (parallel to scheduled cycle)                        │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐                                        │
│  │  Market     │    │   Risk      │                                        │
│  │  Monitor    │    │  Guardian   │                                        │
│  │  (5s loop)  │    │  (30s loop) │                                        │
│  └─────────────┘    └──────┬──────┘                                        │
│                            │                                                │
│                     [Kill Switch] ──→ Halts all trading                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Signal Flow by Source

```
TechnicalAnalystAgent
  ├── Fetch OHLCV (250 candles) per symbol/timeframe
  ├── Compute 12+ indicators
  ├── Evaluate YAML strategies
  ├── Apply MTF confirmation
  └── Emit Signal(source="technical")

MarketMonitorAgent
  ├── Fetch ticker (price, volume)
  ├── Fetch order book
  ├── Detect anomalies (spike, volume, OB, flash crash)
  └── Emit Signal(source="momentum")

NewsSentimentAgent
  ├── Fetch news (CryptoPanic + SerpAPI)
  ├── Fetch social data (LunarCrush)
  ├── LLM sentiment classification
  ├── Compute weighted score
  └── Emit Signal(source="sentiment")

RiskGuardianAgent
  ├── Check drawdown, daily loss, positions
  ├── Check ATR volatility
  ├── Check API health
  └── Emit Signal(source="risk") or Kill Switch
```

---

## 15. Configuration Reference

### Complete System Configuration

```yaml
# Pairs to trade
pairs:
  - "BTC/USDT"
  - "ETH/USDT"
  - "SOL/USDT"

# Technical Analyst
analyst:
  timeframes: ["15m", "1h", "4h"]
  indicators:
    rsi: { period: 14 }
    ema: { fast: 20, slow: 50 }
    macd: { fast: 12, slow: 26, signal: 9 }
    bollinger: { period: 20, std: 2.0 }
    atr: { period: 14 }
    volume_sma: { period: 20 }
    stochastic: { k: 14, d: 3 }
    adx: { period: 14 }
    donchian: { period: 20 }
  multi_timeframe:
    enabled: true
    confirmation_boost: 0.15

# Market Monitor
market_monitor:
  check_interval_sec: 5
  price_spike:
    threshold_pct: 2.0
    window_sec: 300
  volume_anomaly:
    std_multiplier: 3.0
    lookback_periods: 20
  order_book:
    depth: 20
    imbalance_ratio: 3.0

# Sentiment
sentiment:
  schedule: "0 * * * *"
  news_max_age_hours: 24
  sources:
    cryptopanic: { enabled: true }
    serpapi: { enabled: true }
    lunarcrush: { enabled: true }
  llm:
    model: "gpt-4o-mini"
    max_tokens: 500
    temperature: 0.1
  thresholds:
    strong_bullish: 0.5
    strong_bearish: -0.5
    min_news_count: 3

# Decision Engine
decision:
  weights:
    technical: 0.30
    sentiment: 0.20
    momentum: 0.20
    risk: 0.15
    ml: 0.10
    on-chain: 0.05
  thresholds:
    buy: 0.6
    sell: -0.6
    min_confidence: 0.5
  confidence_boost:
    agreement_bonus: 0.15
    max_confidence: 0.95
  explanation:
    enabled: true

# Risk
risk:
  max_positions: 5
  risk_per_trade: 0.02
  max_exposure: 0.5
  stop_loss: 0.05
  max_daily_loss: 0.05
  max_drawdown: 0.15

# Risk Guardian
risk_guardian:
  check_interval_sec: 30
  limits:
    max_drawdown_pct: 0.20
    max_daily_loss_pct: 0.05
    max_positions: 5
    max_exposure_pct: 0.30
    max_loss_per_position: 0.10
  kill_switch:
    enabled: true
    auto_close_positions: true
    manual_reset_required: true
  volatility:
    atr_spike_multiplier: 3.0
  api_health:
    max_consecutive_errors: 10

# Execution
execution:
  dry_run: true
  rate_limit: 10

# Freqtrade
freqtrade:
  base_url: "http://localhost:8080"
  api_key: "${FREQTRADE_API_KEY}"
  timeout: 30.0
  max_retries: 3
```

### Strategy Files

Located in `config/strategies/`. Each YAML file defines a trading strategy:

| File | Strategy Type |
|---|---|
| `bull-trend.yaml` | Trend-following with EMA confirmation |
| `mean-reversion.yaml` | RSI + Bollinger Bands mean reversion |
| `momentum-breakout.yaml` | Donchian channel breakout |
| `scalping-ema.yaml` | Fast EMA crossover scalping |
| `whale-watcher.yaml` | Volume anomaly + price action |
| `news-sentiment.yaml` | Sentiment-driven entries |
| `portfolio-rebalancer.yaml` | Portfolio rebalancing logic |

---

## Appendix A: File Map

```
src/
├── agents/
│   ├── __init__.py
│   ├── base.py              # BaseAgent (ABC)
│   ├── signal.py            # Signal dataclass + validation
│   ├── analyst.py           # TechnicalAnalystAgent
│   ├── market_monitor.py    # MarketMonitorAgent
│   ├── news_sentiment.py    # NewsSentimentAgent
│   ├── risk_guardian.py     # RiskGuardianAgent
│   └── decision_engine.py   # DecisionEngine + Decision
├── risk/
│   ├── __init__.py
│   ├── engine.py            # RiskEngine + ValidationResult
│   └── position_sizing.py   # Position sizing utilities
├── execution/
│   ├── __init__.py
│   ├── service.py           # ExecutionService + RateLimiter
│   └── validator.py         # OrderValidator + OrderRequest
└── freqtrade_client/
    ├── __init__.py
    └── client.py            # FreqtradeClient + FreqtradeAPIError

config/
└── strategies/              # YAML strategy definitions
    ├── bull-trend.yaml
    ├── mean-reversion.yaml
    ├── momentum-breakout.yaml
    ├── scalping-ema.yaml
    ├── whale-watcher.yaml
    ├── news-sentiment.yaml
    └── portfolio-rebalancer.yaml
```

## Appendix B: Agent Summary Table

| Agent | File | Source | Schedule | Output |
|---|---|---|---|---|
| **TechnicalAnalystAgent** | `src/agents/analyst.py` | `technical` | Scheduled (per timeframe) | Signal (buy/sell/hold) |
| **MarketMonitorAgent** | `src/agents/market_monitor.py` | `momentum` | Continuous (5s loop) | Signal on anomaly |
| **NewsSentimentAgent** | `src/agents/news_sentiment.py` | `sentiment` | Cron (hourly default) | Signal (buy/sell/hold) |
| **RiskGuardianAgent** | `src/agents/risk_guardian.py` | `risk` | Continuous (30s loop) | Signal / Kill Switch |
| **DecisionEngine** | `src/agents/decision_engine.py` | — | Per cycle | Decision |
| **RiskEngine** | `src/risk/engine.py` | — | Per order | ValidationResult |
| **ExecutionService** | `src/execution/service.py` | — | Per decision | ExecutionResult |
