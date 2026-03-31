# FKCrypto Architecture

**Crypto Trading Agent System** — Hybrid multi-agent architecture combining deterministic technical analysis with LLM-assisted sentiment analysis, integrated with Freqtrade for order execution.

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Core Design Principles](#2-core-design-principles)
- [3. System Architecture](#3-system-architecture)
  - [3.1 Layered Architecture](#31-layered-architecture)
  - [3.2 LangGraph Workflow](#32-langgraph-workflow)
- [4. Agent Layer](#4-agent-layer)
  - [4.1 MarketMonitor Agent](#41-marketmonitor-agent)
  - [4.2 Technical Analyst Agent](#42-technical-analyst-agent)
  - [4.3 NewsSentiment Agent](#43-newssentiment-agent)
  - [4.4 RiskGuardian Agent](#44-riskguardian-agent)
  - [4.5 Decision Engine](#45-decision-engine)
- [5. Service Layer](#5-service-layer)
  - [5.1 Execution Service](#51-execution-service)
  - [5.2 Risk Engine](#52-risk-engine)
  - [5.3 Position Sizing](#53-position-sizing)
- [6. Data Layer](#6-data-layer)
  - [6.1 Data Sources](#61-data-sources)
  - [6.2 LLM Gateway](#62-llm-gateway)
  - [6.3 Message Bus](#63-message-bus)
- [7. Persistence Layer](#7-persistence-layer)
  - [7.1 Database Models](#71-database-models)
  - [7.2 Repository Pattern](#72-repository-pattern)
  - [7.3 Freqtrade Client](#73-freqtrade-client)
- [8. Contracts & Protocols](#8-contracts--protocols)
  - [8.1 Signal Contract](#81-signal-contract)
  - [8.2 Decision Thresholds](#82-decision-thresholds)
- [9. Architecture Patterns](#9-architecture-patterns)
- [10. Key Data Flows](#10-key-data-flows)
- [11. Observability](#11-observability)
  - [11.1 Prometheus Metrics](#111-prometheus-metrics)
- [12. Backtesting Architecture](#12-backtesting-architecture)
- [13. Security & Safety](#13-security--safety)
  - [13.1 Prompt Injection Protection](#131-prompt-injection-protection)
  - [13.2 Security Middleware](#132-security-middleware)
- [14. Deployment Topology](#14-deployment-topology)

---

## 1. Overview

FKCrypto is an autonomous crypto trading system built on a **hybrid multi-agent architecture**. It combines deterministic technical analysis with LLM-assisted sentiment analysis to produce trading signals, which are then validated by a risk engine and executed through Freqtrade.

The system is designed so that the **same Decision Engine runs identically** in both backtesting (historical data) and live trading modes, ensuring full reproducibility and auditability.

---

## 2. Core Design Principles

| # | Principle | Description |
|---|-----------|-------------|
| 1 | **Deterministic first, LLM second** | All trading decisions are reproducible. LLMs assist with analysis and explanation only — they never override deterministic scoring. |
| 2 | **Agents emit signals, not decisions** | Each agent produces normalized `Signal` objects. A central `DecisionEngine` aggregates and decides. |
| 3 | **Independent safety boundaries** | A separate `RiskEngine` and `ExecutionService` validate every order before it reaches Freqtrade. |
| 4 | **Everything must be backtestable** | The same Decision Engine runs on historical data for backtesting and live data for trading. |
| 5 | **Explainability by default** | Every signal carries structured reasoning (`Reasoning` dataclass) — no black box decisions. |
| 6 | **Human-in-the-loop ready** | Approval requests can gate execution — the bot proposes, the human decides. |
| 7 | **Security-first external content** | All external content (news, tweets, web) is scanned for prompt injection before LLM processing. |

---

## 3. System Architecture

### 3.1 Layered Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Gateway Layer                             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  LangGraph StateGraph (orchestrator)                     │    │
│  │  State: AgentState (TypedDict)                           │    │
│  │  Nodes: market_monitor, analyst, sentiment, risk,        │    │
│  │        decision, execution                                │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Layer                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ MarketMonitor│ │ Technical    │ │ NewsSentiment│           │
│  │ Agent        │ │ Analyst      │ │ Agent        │           │
│  │              │ │ Agent        │ │              │           │
│  │ - Price spike│ │ - 12+        │ │ - Crypto-    │           │
│  │ - Volume     │ │   indicators │ │   Panic      │           │
│  │   anomaly    │ │ - YAML       │ │ - SerpAPI    │           │
│  │ - Flash crash│ │   strategies │ │ - LunarCrush │           │
│  │ - Order book │ │ - Multi-TF   │ │ - LLM        │           │
│  │   imbalance  │ │   confirm    │ │   sentiment  │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
│  ┌──────────────┐ ┌──────────────┐                             │
│  │ RiskGuardian │ │ Decision     │                             │
│  │ Agent        │ │ Engine       │                             │
│  │              │ │              │                             │
│  │ - Drawdown   │ │ - Weighted   │                             │
│  │ - Daily loss │ │   scoring    │                             │
│  │ - Kill switch│ │ - LLM        │                             │
│  │ - ATR spikes │ │   explanation│                             │
│  │ - API health │ │ - Persist    │                             │
│  └──────────────┘ └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Service Layer                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ Execution    │ │ Risk Engine  │ │ Position     │           │
│  │ Service      │ │              │ │ Sizing       │           │
│  │              │ │ - Kill switch│ │              │           │
│  │ - Order      │ │   check      │ │ - ATR-based  │           │
│  │   routing    │ │ - Stop-loss  │ │   stops      │           │
│  │ - Audit log  │ │   mandatory  │ │ - Trailing   │           │
│  │ - Rate limit │ │ - Size limits│ │   stops      │           │
│  │ - Freqtrade  │ │ - Max pos    │ │ - Take profit│           │
│  │   forward    │ │ - Daily loss │ │              │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ CCXTSource   │ │ CoinGecko    │ │ NewsSource   │           │
│  │ (primary)    │ │ Source       │ │              │           │
│  │              │ │              │ │ - CryptoPanic│           │
│  │ - OHLCV      │ │ - Market cap │ │ - SerpAPI    │           │
│  │ - Ticker     │ │ - Trending   │ │              │           │
│  │ - Orderbook  │ │ - Global     │ │              │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ SocialSource │ │ LLM Gateway  │ │ Message Bus  │           │
│  │              │ │              │ │              │           │
│  │ - LunarCrush │ │ - LiteLLM    │ │ - Redis      │           │
│  │ - Social     │ │ - Fallback   │ │ - In-memory  │           │
│  │   sentiment  │ │ - Retry      │ │   fallback   │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                    Persistence Layer                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐           │
│  │ PostgreSQL/  │ │ Repository   │ │ Freqtrade    │           │
│  │ TimescaleDB  │ │ Pattern      │ │ Client       │           │
│  │              │ │              │ │              │           │
│  │ - signals    │ │ - CRUD for   │ │ - Async REST │           │
│  │ - decisions  │ │   all models │ │   API        │           │
│  │ - orders     │ │              │ │ - Retry      │           │
│  │ - portfolio  │ │              │ │   logic      │           │
│  │ - kill switch│ │              │ │              │           │
│  └──────────────┘ └──────────────┘ └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 LangGraph Workflow

```
                    (parallel)
market_monitor ────────┐
analyst      ──────────┼──→ decision ──→ execution ──→ END
sentiment    ──────────┤
risk         ──────────┘
```

| Phase | Nodes | Description |
|-------|-------|-------------|
| **Entry** | `market_monitor` | Continuous monitoring loop; detects anomalies and triggers analysis |
| **Parallel** | `market_monitor`, `analyst`, `sentiment`, `risk` | All agents run independently and append signals to shared state |
| **Convergence** | `decision` | Aggregates all signals, computes weighted score, produces decision |
| **Sequential** | `execution` | Validates through RiskEngine, routes order to Freqtrade |

**State (`AgentState` TypedDict):**

```python
class AgentState(TypedDict):
    symbol: str
    signals: list[Signal]
    score: float
    decision: str          # "buy" | "sell" | "hold"
    confidence: float
    kill_switch: bool
    portfolio: dict
    errors: list[str]
    retry_count: int
    execution_result: dict
    metadata: dict
```

---

## 4. Agent Layer

Each agent is an independent, specialized component that consumes data from the Data Layer and emits `Signal` objects. Agents have **no knowledge of each other** — they only communicate through the shared state.

### 4.1 MarketMonitor Agent

Continuous monitoring agent that watches for market anomalies in real-time.

**Responsibilities:**
- Detect price spikes and flash crashes
- Monitor volume anomalies
- Track order book imbalances
- Trigger kill switch on critical anomalies

**Data consumed:** OHLCV, ticker, orderbook from `CCXTSource`

### 4.2 Technical Analyst Agent

Deterministic technical analysis engine.

**Responsibilities:**
- Compute 12+ technical indicators (RSI, MACD, Bollinger Bands, ATR, etc.)
- Load and execute YAML-defined trading strategies
- Multi-timeframe confirmation (e.g., 1h + 4h + 1d alignment)
- Produce deterministic signals with confidence scores

**Strategy loading (Strategy Pattern):**

```yaml
# strategies/rsi_reversal.yaml
name: "RSI Reversal"
indicators:
  - name: rsi
    period: 14
  - name: ema
    period: 50
conditions:
  buy:
    - rsi < 30
    - close > ema_50
  sell:
    - rsi > 70
weight: 0.15
```

### 4.3 NewsSentiment Agent

LLM-assisted sentiment analysis from crypto news and social data.

**Responsibilities:**
- Aggregate news from CryptoPanic and SerpAPI
- Fetch social sentiment from LunarCrush
- Use LLM to classify sentiment (bullish/bearish/neutral)
- Produce sentiment signals with confidence

**Data sources:** CryptoPanic API, SerpAPI, LunarCrush, LLM Gateway

### 4.4 RiskGuardian Agent

Continuous risk monitoring and circuit breaker.

**Responsibilities:**
- Monitor portfolio drawdown
- Track daily P&L loss limits
- Detect ATR-based volatility spikes
- Verify API health and connectivity
- Trigger kill switch when thresholds breached

### 4.5 Decision Engine

The central brain that aggregates all agent signals into a single trading decision.

**Process:**

```
Signals → Normalize → Deduplicate → Weighted Scoring → Decision → LLM Explanation → Persist
```

**Weighted scoring configuration:**

| Source | Weight |
|--------|--------|
| Technical | 30% |
| Sentiment | 20% |
| Momentum | 20% |
| Risk | 15% |
| ML | 10% |
| On-chain | 5% |

**Decision logic:**

```python
def compute_decision(signals: list[Signal], weights: dict[str, float]) -> Decision:
    normalized = normalize_signals(signals)
    deduped = deduplicate(normalized)
    score = weighted_score(deduped, weights)
    confidence = compute_confidence(deduped)

    if score >= BUY_THRESHOLD and confidence >= MIN_CONFIDENCE:
        action = "buy"
    elif score <= SELL_THRESHOLD and confidence >= MIN_CONFIDENCE:
        action = "sell"
    else:
        action = "hold"

    explanation = llm_explain(score, signals, action)  # LLM for explanation only
    return Decision(action=action, score=score, confidence=confidence, explanation=explanation)
```

---

## 5. Service Layer

### 5.1 Execution Service

Routes validated decisions to Freqtrade and manages the order lifecycle.

**Responsibilities:**
- Order routing (market, limit, stop)
- Audit logging of all orders
- Rate limiting and backoff
- Freqtrade API forwarding with retry logic
- Order status tracking

### 5.2 Risk Engine

Independent validation layer that sits between Decision Engine and Execution Service.

**Validations (all must pass):**
- Kill switch not active
- Stop-loss is mandatory on every order
- Position size within configured limits
- Maximum concurrent positions not exceeded
- Daily loss limit not breached

### 5.3 Position Sizing

Dynamic position sizing based on market conditions.

**Methods:**
- **ATR-based stops:** Stop distance derived from Average True Range
- **Trailing stops:** Dynamic stop-loss that follows price
- **Take profit:** Configurable profit targets
- **Risk-per-trade:** Fixed percentage of portfolio per position

---

## 6. Data Layer

### 6.1 Data Sources

All data sources implement the `DataSource` abstract base class (Plugin Architecture):

```python
class DataSource(ABC):
    @abstractmethod
    async def fetch(self, symbol: str, timeframe: str, **kwargs) -> DataFrame: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

| Source | Type | Data |
|--------|------|------|
| `CCXTSource` | Primary | OHLCV, ticker, orderbook |
| `CoinGeckoSource` | Market data | Market cap, trending coins, global metrics |
| `NewsSource` | News | CryptoPanic, SerpAPI |
| `SocialSource` | Social | LunarCrush social sentiment |

### 6.2 LLM Gateway

Unified interface for LLM providers with resilience features.

**Features:**
- **LiteLLM** integration for provider abstraction
- **Fallback chain:** Primary → Secondary → Local model
- **Retry logic** with exponential backoff
- **Circuit breaker** on repeated failures
- **Token usage tracking** for cost monitoring

### 6.3 Message Bus

Pub/Sub system for inter-component communication.

**Implementation:**
- **Primary:** Redis Streams
- **Fallback:** In-memory pub/sub (for development / Redis unavailable)

**Channels:**
- `signals.{symbol}` — Agent signal broadcasts
- `decisions.{symbol}` — Decision broadcasts
- `alerts` — Kill switch and anomaly alerts
- `orders` — Order lifecycle events

---

## 7. Persistence Layer

### 7.1 Database Models

PostgreSQL with TimescaleDB for time-series optimization.

#### SignalRecord (`signals`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `symbol` | VARCHAR | Trading pair (e.g., BTC/USDT) |
| `timeframe` | VARCHAR | Candle timeframe |
| `action` | VARCHAR | buy / sell / hold |
| `confidence` | FLOAT | 0.0 – 1.0 |
| `strength` | FLOAT | -1.0 – 1.0 |
| `source` | VARCHAR | Emitting agent name |
| `timestamp` | TIMESTAMPTZ | Signal emission time |
| `metadata_json` | JSONB | Agent-specific context |

#### DecisionRecord (`decisions`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `symbol` | VARCHAR | Trading pair |
| `action` | VARCHAR | buy / sell / hold |
| `score` | FLOAT | Weighted composite score |
| `confidence` | FLOAT | Decision confidence |
| `signal_count` | INT | Number of signals aggregated |
| `sources` | JSONB | List of contributing sources |
| `explanation` | TEXT | LLM-generated explanation |
| `timestamp` | TIMESTAMPTZ | Decision time |

#### OrderRecord (`orders`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `decision_id` | UUID (FK) | Reference to DecisionRecord |
| `symbol` | VARCHAR | Trading pair |
| `action` | VARCHAR | buy / sell |
| `size_usd` | DECIMAL | Order size in USD |
| `price` | DECIMAL | Execution price |
| `status` | VARCHAR | pending / filled / rejected / cancelled |
| `freqtrade_order_id` | VARCHAR | Freqtrade order reference |
| `reason` | TEXT | Execution reason |
| `rejected_reason` | TEXT | Rejection reason (if rejected) |
| `timestamp` | TIMESTAMPTZ | Order creation time |
| `filled_at` | TIMESTAMPTZ | Order fill time |

#### PortfolioSnapshot (`portfolio_snapshots`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `total_value_usd` | DECIMAL | Total portfolio value |
| `cash_usd` | DECIMAL | Available cash |
| `positions_json` | JSONB | Open positions snapshot |
| `daily_pnl` | DECIMAL | Daily profit/loss |
| `drawdown_pct` | FLOAT | Current drawdown percentage |
| `timestamp` | TIMESTAMPTZ | Snapshot time |

#### KillSwitchEvent (`kill_switch_events`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `reason` | VARCHAR | Trigger reason |
| `detail` | TEXT | Detailed context |
| `triggered_at` | TIMESTAMPTZ | Activation time |
| `reset_at` | TIMESTAMPTZ | Deactivation time |
| `reset_by` | VARCHAR | Who/what reset it |
| `active` | BOOLEAN | Current status |

### 7.2 Repository Pattern

All database access is abstracted through repository interfaces:

```python
class SignalRepository(Protocol):
    async def save(self, signal: Signal) -> UUID: ...
    async def find_by_symbol(self, symbol: str, since: datetime) -> list[SignalRecord]: ...
    async def count_by_source(self, source: str, window: timedelta) -> int: ...

class DecisionRepository(Protocol):
    async def save(self, decision: Decision) -> UUID: ...
    async def find_latest(self, symbol: str) -> DecisionRecord | None: ...

class OrderRepository(Protocol):
    async def save(self, order: Order) -> UUID: ...
    async def update_status(self, order_id: UUID, status: str) -> None: ...
```

This enables:
- Swappable database backends
- Easy mocking for tests
- Clear separation between domain and persistence

### 7.3 Freqtrade Client

Async REST client for Freqtrade API integration.

**Features:**
- Async HTTP calls with `aiohttp`
- Automatic retry with exponential backoff
- Rate limit awareness
- Order status polling
- Health check endpoint

---

## 8. Contracts & Protocols

### 8.1 Signal Contract

All agents communicate through a strict `Signal` dataclass. This is the **single communication contract** across the entire system.

```python
@dataclass
class Signal:
    symbol: str
    timeframe: str
    action: Literal["buy", "sell", "hold"]
    confidence: float       # 0.0 – 1.0
    strength: float         # -1.0 – 1.0
    source: str
    timestamp: datetime
    metadata: dict

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0-1, got {self.confidence}")
        if not -1.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be -1 to 1, got {self.strength}")
        if self.action not in ("buy", "sell", "hold"):
            raise ValueError(f"invalid action: {self.action}")
```

**Validation rules enforced at construction:**
- `confidence` must be in [0.0, 1.0]
- `strength` must be in [-1.0, 1.0]
- `action` must be one of `"buy"`, `"sell"`, `"hold"`

### 8.2 Decision Thresholds

| Parameter | Value | Description |
|-----------|-------|-------------|
| `BUY_THRESHOLD` | `>= 0.6` | Minimum score to trigger a buy |
| `SELL_THRESHOLD` | `<= -0.6` | Maximum score to trigger a sell |
| `MIN_CONFIDENCE` | `>= 0.5` | Minimum confidence for any non-hold decision |
| Scores between | `-0.6` and `0.6` | Result in `"hold"` |

---

## 9. Architecture Patterns

| # | Pattern | Application |
|---|---------|-------------|
| 1 | **Multi-Agent** | Independent specialized agents (MarketMonitor, Analyst, Sentiment, RiskGuardian) |
| 2 | **Signal-Based Communication** | Strict `Signal` dataclass contract between all components |
| 3 | **LangGraph State Machine** | `StateGraph` with parallel nodes for agent orchestration |
| 4 | **Separation of Concerns** | Decision, execution, and risk are fully separated |
| 5 | **Repository Pattern** | Database access abstracted behind protocol interfaces |
| 6 | **Strategy Pattern** | YAML strategy files loaded dynamically at runtime |
| 7 | **Plugin Architecture** | All data sources implement `DataSource` ABC |
| 8 | **Circuit Breaker / Kill Switch** | RiskGuardian can halt all trading instantly |
| 9 | **Deterministic + LLM Hybrid** | LLMs used for sentiment analysis and explanation only |
| 10 | **Pub/Sub Message Bus** | Redis-based with in-memory fallback for decoupled communication |
| 11 | **Dependency Injection** | Sources and repositories injected at construction for testability |

---

## 10. Key Data Flows

### 10.1 Signal Generation Flow

```
┌──────────────┐     ┌────────┐     ┌──────────┐     ┌──────────────┐     ┌──────────┐
│ Data Sources │ ──→ │ Agents │ ──→ │ Signal   │ ──→ │ Message Bus  │ ──→ │ Database │
│              │     │        │     │ objects  │     │ (Redis)      │     │          │
└──────────────┘     └────────┘     └──────────┘     └──────────────┘     └──────────┘
```

1. Data sources fetch market, news, and social data
2. Agents process data and emit `Signal` objects
3. Signals are published to the message bus
4. Signals are persisted to PostgreSQL

### 10.2 Decision Flow

```
┌─────────┐     ┌──────────────────────────────┐     ┌────────────┐     ┌──────────────────┐     ┌───────────┐
│ Signals │ ──→ │ DecisionEngine               │ ──→ │ RiskEngine │ ──→ │ ExecutionService │ ──→ │ Freqtrade │
│         │     │ (weighted scoring)           │     │            │     │                  │     │           │
└─────────┘     └──────────────────────────────┘     └────────────┘     └──────────────────┘     └───────────┘
```

1. DecisionEngine aggregates and scores all signals
2. RiskEngine validates the decision against safety rules
3. ExecutionService creates and routes the order
4. Order is sent to Freqtrade for exchange execution

### 10.3 Monitoring Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌───────────────┐
│ MarketMonitor   │ ──→ │ Anomaly          │ ──→ │ Kill Switch │ ──→ │ Notifications │
│ (continuous)    │     │ Detection        │     │ (if needed) │     │               │
└─────────────────┘     └──────────────────┘     └─────────────┘     └───────────────┘
```

### 10.4 Backtest Flow

```
┌──────────────────┐     ┌──────────────────┐     ┌────────┐     ┌──────────────────┐     ┌───────────────────┐     ┌─────────┐
│ Historical Data  │ ──→ │ DataReplayEngine │ ──→ │ Agents │ ──→ │ DecisionEngine   │ ──→ │ TradingSimulator  │ ──→ │ Metrics │
│                  │     │                  │     │        │     │ (same as live)   │     │                   │     │         │
└──────────────────┘     └──────────────────┘     └────────┘     └──────────────────┘     └───────────────────┘     └─────────┘
```

**Critical:** The same `DecisionEngine` and agent logic runs in both backtest and live modes. Only the data source and execution layer differ.

---

## 11. Observability

### 11.1 Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `signals_total` | Counter | Total signals emitted by all agents |
| `decisions_total` | Counter | Total decisions made (by action) |
| `orders_executed` | Counter | Total orders sent to Freqtrade |
| `orders_rejected` | Counter | Total orders rejected by RiskEngine |
| `portfolio_value` | Gauge | Current total portfolio value in USD |
| `drawdown_pct` | Gauge | Current portfolio drawdown percentage |
| `agent_latency_ms` | Histogram | Processing latency per agent |
| `llm_calls_total` | Counter | Total LLM API calls made |
| `llm_errors_total` | Counter | Total LLM API call failures |

**Labels:** All metrics support `symbol`, `agent`, and `source` labels for granular filtering.

---

## 12. Backtesting Architecture

The backtesting system replays historical data through the **exact same pipeline** used in live trading:

```
Historical OHLCV ──→ DataReplayEngine ──→ Agents ──→ DecisionEngine ──→ TradingSimulator
```

**Key properties:**
- **Deterministic replay:** Given the same historical data and configuration, results are 100% reproducible
- **No look-ahead bias:** Agents only see data available at the simulated timestamp
- **Slippage simulation:** Configurable slippage and fee models
- **Same DecisionEngine:** The weighted scoring, thresholds, and deduplication logic is identical to live mode
- **Metrics output:** Sharpe ratio, max drawdown, win rate, profit factor, and per-trade breakdown

---

## 13. Security & Safety

### Kill Switch

The kill switch is the ultimate safety mechanism. When triggered:
1. All new orders are blocked immediately
2. Existing positions are evaluated for emergency exit
3. All agents are notified via the message bus
4. A `KillSwitchEvent` is persisted to the database

**Trigger conditions:**
- Portfolio drawdown exceeds configured threshold
- Daily loss limit breached
- Critical API failure (exchange or data source)
- Manual trigger by operator

### Order Validation Pipeline

Every order passes through these gates before reaching the exchange:

```
Order → Kill Switch Check → Stop-Loss Present? → Size Within Limits? → Max Positions OK? → Daily Loss OK? → Freqtrade
```

Any gate failure results in order rejection with a recorded reason.

---

## 14. Deployment Topology

```
                    ┌─────────────────────────────┐
                    │        Load Balancer         │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │       FKCrypto Core          │
                    │  ┌───────────────────────┐  │
                    │  │   LangGraph Orchestr.  │  │
                    │  │   Agent Layer          │  │
                    │  │   Service Layer        │  │
                    │  └───────────────────────┘  │
                    └──────┬──────────┬───────────┘
                           │          │
              ┌────────────▼──┐   ┌───▼────────────┐
              │   PostgreSQL   │   │     Redis       │
              │  + TimescaleDB │   │  (Message Bus)  │
              └───────────────┘   └────────────────┘
                           │
              ┌────────────▼────────────┐
              │      Freqtrade          │
              │   (Order Execution)     │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │      Exchange API        │
              │   (Binance, etc.)        │
              └─────────────────────────┘
```

**Components:**
- **FKCrypto Core:** Python application running LangGraph orchestrator, agents, and services
- **PostgreSQL + TimescaleDB:** Persistent storage with time-series optimization
- **Redis:** Message bus for pub/sub and inter-agent communication
- **Freqtrade:** Order execution engine (can run as separate process)
- **Exchange:** External crypto exchange via CCXT

---

*Document version: 1.0 | Last updated: 2026-04-01*
