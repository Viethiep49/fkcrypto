# Crypto Trading Agent System — Design Spec

**Date:** 2026-03-31
**Status:** Draft — awaiting review

---

## 1. Core Principles

1. **Deterministic first, LLM second** — All trading decisions must be reproducible. LLMs assist with analysis and explanation, never override deterministic scoring.
2. **Agents emit signals, not decisions** — Each agent produces normalized signals. The Decision Engine aggregates and decides.
3. **Execution has independent safety boundaries** — A separate Risk Engine and Execution Service validate every order before it reaches Freqtrade.
4. **Everything must be backtestable** — The same Decision Engine runs on historical data for backtesting and live data for trading.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────┐
│           Orchestrator (LangGraph)           │
│   - Workflow control                        │
│   - Retry / fallback                        │
│   - Scheduling (APScheduler)                │
└───────────────┬──────────────────────────────┘
                │
        (Event / Tasks)
                │
┌───────────────▼──────────────────────────────┐
│              Message Bus (Redis)             │
│   - Pub/Sub signals                         │
│   - Decouple agents                         │
└──────┬──────────┬──────────┬──────────┬──────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
 Market      Analyst     Risk       News/Sentiment
 Monitor     Agent       Agent      Agent
(real-time) (scheduled) (real-time) (scheduled)

       │
       ▼
┌──────────────────────────────────────────────┐
│          Signal Normalization Layer          │
└─────────────────────────┬────────────────────┘
                          ▼
┌──────────────────────────────────────────────┐
│             Decision Engine                  │
│  - Weighted scoring                         │
│  - Portfolio logic                          │
│  - Confidence aggregation                   │
└─────────────────────────┬────────────────────┘
                          ▼
┌──────────────────────────────────────────────┐
│              Risk Engine                     │
│  - Position sizing                          │
│  - Max drawdown                             │
│  - Exposure limit                           │
└─────────────────────────┬────────────────────┘
                          ▼
┌──────────────────────────────────────────────┐
│          Execution Service                   │
│  - Validate orders                          │
│  - Audit log                                │
│  - Rate limit                               │
└─────────────────────────┬────────────────────┘
                          ▼
┌──────────────────────────────────────────────┐
│             Freqtrade Service                │
└──────────────────────────────────────────────┘
```

---

## 3. Project Structure

```
fkcrypto/
├── docker/
│   ├── docker-compose.yml
│   ├── Dockerfile.gateway
│   ├── Dockerfile.freqtrade
│   ├── Dockerfile.dashboard
│   └── nginx/
│       └── nginx.conf
├── .env.example
├── config/
│   ├── default.yaml
│   ├── exchanges.yaml
│   ├── strategies/
│   └── notifications.yaml
├── src/
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   └── state.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── market_monitor.py
│   │   ├── analyst.py
│   │   ├── risk_guardian.py
│   │   ├── news_sentiment.py
│   │   └── decision_engine.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── ccxt_source.py
│   │   ├── coingecko.py
│   │   ├── news.py
│   │   └── social.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── litellm_gateway.py
│   │   └── prompts/
│   │       ├── analyst.md
│   │       ├── risk.md
│   │       └── decision.md
│   ├── freqtrade_client/
│   │   ├── __init__.py
│   │   └── client.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── repository.py
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── position_sizing.py
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── service.py
│   │   └── validator.py
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       ├── scheduler.py
│       └── notifications.py
├── dashboard/
├── tests/
│   ├── test_agents/
│   ├── test_data/
│   ├── test_gateway/
│   ├── test_risk/
│   └── test_execution/
├── scripts/
├── docs/
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 4. Signal Contract

All agents must emit signals conforming to this schema:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any


@dataclass
class Signal:
    symbol: str                          # e.g. "BTC/USDT"
    timeframe: str                       # e.g. "1m", "5m", "1h", "4h", "1d"
    action: Literal["buy", "sell", "hold"]
    confidence: float                    # 0.0 → 1.0
    strength: float = 0.0               # magnitude of signal (-1.0 to 1.0)
    source: str = ""                     # "technical", "news", "sentiment", "momentum", "ml"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0-1, got {self.confidence}")
        if self.action not in ("buy", "sell", "hold"):
            raise ValueError(f"action must be buy/sell/hold, got {self.action}")
```

### Rules

- No agent returns a different format — strict validation on emission.
- LLM outputs are parsed and validated, never passed raw.
- Signals are immutable once emitted.

---

## 5. Agent Responsibilities

### 5.1 Market Monitor (real-time)

**Purpose:** Detect market anomalies in real-time via WebSocket.

**Data:** ccxt WebSocket streams (price, volume, order book).

**Emits:**
- `price_spike` — sudden price change > threshold
- `volume_anomaly` — volume surge > N standard deviations

**Interval:** Continuous (WebSocket event-driven).

### 5.2 Analyst Agent (scheduled)

**Purpose:** Technical analysis on scheduled intervals.

**Data:** OHLCV from ccxt historical data.

**Indicators:** RSI, MACD, EMA, Bollinger Bands, ATR, Volume Profile.

**Output:** Deterministic signals based on indicator conditions.

**Interval:** Configurable (default: every 15 minutes).

### 5.3 News & Sentiment Agent (scheduled)

**Purpose:** Analyze news and social sentiment.

**Data:** CryptoPanic, SerpAPI, LunarCrush (optional).

**LLM usage:** Only for sentiment classification (buy/neutral/bearish → score -1 to 1).

**Output:** `sentiment_score ∈ [-1.0, 1.0]` per symbol.

**Interval:** Configurable (default: every hour).

### 5.4 Risk Guardian Agent (real-time)

**Purpose:** Monitor portfolio risk in real-time.

**Monitors:**
- Volatility spikes
- Abnormal drawdown
- Exposure limits
- Correlation breakdown

**Actions:**
- Emit risk signals to Decision Engine
- Trigger kill switch if thresholds breached

**Interval:** Continuous (polls every 30 seconds).

---

## 6. Decision Engine

### 6.1 Pipeline

```
Signals → Normalize → Aggregate → Score → Decision
```

### 6.2 Normalization

```python
def normalize_signal(signal: Signal) -> Signal:
    signal.confidence = min(max(signal.confidence, 0.0), 1.0)
    signal.strength = min(max(signal.strength, -1.0), 1.0)
    return signal
```

### 6.3 Weighted Scoring

```python
WEIGHTS = {
    "technical": 0.40,
    "sentiment": 0.25,
    "momentum": 0.20,
    "ml": 0.15,
}

def aggregate_score(signals: list[Signal]) -> float:
    """Weighted aggregation of normalized signals."""
    if not signals:
        return 0.0

    weighted_sum = 0.0
    total_weight = 0.0

    for signal in signals:
        w = WEIGHTS.get(signal.source, 0.1)
        direction = 1.0 if signal.action == "buy" else (-1.0 if signal.action == "sell" else 0.0)
        weighted_sum += w * direction * signal.confidence
        total_weight += w

    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

### 6.4 Decision Rule

```python
BUY_THRESHOLD = 0.7
SELL_THRESHOLD = -0.7

def make_decision(score: float) -> str:
    if score > BUY_THRESHOLD:
        return "buy"
    elif score < SELL_THRESHOLD:
        return "sell"
    return "hold"
```

### 6.5 Confidence Aggregation

```python
def aggregate_confidence(signals: list[Signal]) -> float:
    if not signals:
        return 0.0
    return sum(s.confidence for s in signals) / len(signals)
```

### 6.6 LLM Usage (Restricted)

LLM is **only** used for:
- Explaining decisions in natural language
- Summarizing signals for dashboard/notifications
- Sentiment classification from news text

LLM is **never** used for:
- Overriding deterministic scores
- Generating trades directly
- Bypassing risk checks

---

## 7. Risk Engine

### 7.1 Position Sizing

```python
DEFAULT_RISK_PER_TRADE = 0.01  # 1% of capital

def calculate_position_size(
    account_balance: float,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
    stop_loss_pct: float = 0.02,
) -> float:
    """Calculate position size based on risk parameters."""
    risk_amount = account_balance * risk_per_trade
    position_size = risk_amount / stop_loss_pct
    return position_size
```

### 7.2 Hard Rules

| Rule | Default | Configurable |
|------|---------|-------------|
| Max open positions | 5 | Yes |
| Max capital exposure | 30% | Yes |
| Stop-loss | Mandatory | Yes (min 1%) |
| Max daily loss | 5% | Yes |
| Max drawdown | 20% | Yes |

### 7.3 Kill Switch

Triggers if **any** of:
- Portfolio drawdown > `max_drawdown` threshold
- Exchange API errors > N consecutive failures
- Market extreme volatility (ATR spike > 3x average)
- Risk Guardian agent signals emergency

On kill switch:
1. Close all positions (market orders)
2. Pause all agents
3. Send alert via all notification channels
4. Require manual reset

---

## 8. Execution Service

### 8.1 Responsibilities

- Receive approved decisions from Decision Engine
- Validate against Risk Engine rules
- Log every order attempt (audit trail)
- Rate limit order submissions
- Forward to Freqtrade via REST API

### 8.2 Order Validation

```python
@dataclass
class OrderRequest:
    symbol: str
    action: str          # "buy" or "sell"
    size: float          # in USD
    confidence: float
    reason: str          # e.g. "score=0.82"

class ExecutionService:
    def execute(self, order: OrderRequest) -> ExecutionResult:
        # 1. Risk check
        if not self.risk_engine.validate(order):
            return ExecutionResult.rejected("risk_check_failed")

        # 2. Rate limit check
        if self.rate_limiter.is_limited(order.symbol):
            return ExecutionResult.rejected("rate_limited")

        # 3. Audit log
        self.audit_log.record(order)

        # 4. Forward to Freqtrade
        return self.freqtrade_client.place_order(order)
```

### 8.3 Audit Log Format

```json
{
  "timestamp": "2026-03-31T12:00:00Z",
  "symbol": "BTC/USDT",
  "action": "buy",
  "size": 100.0,
  "confidence": 0.82,
  "reason": "score=0.82, technical=0.9, sentiment=0.7",
  "risk_passed": true,
  "result": "filled",
  "order_id": "ft-12345"
}
```

---

## 9. Data Layer

### 9.1 Plugin Architecture

```python
class DataSource(ABC):
    @abstractmethod
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[dict]: ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict: ...

    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int) -> dict: ...

    @property
    @abstractmethod
    def is_available(self) -> bool: ...
```

### 9.2 Built-in Sources

| Source | Data | Required |
|--------|------|----------|
| ccxt | OHLCV, ticker, orderbook, WebSocket | Yes |
| CoinGecko | Market cap, volume, trends | Optional |
| CryptoPanic | News headlines | Optional |
| LunarCrush | Social sentiment | Optional |
| SerpAPI | Web search for news | Optional |

### 9.3 Cache

- Redis TTL: 30s for real-time data, 5min for historical
- Cache key: `{source}:{symbol}:{timeframe}:{endpoint}`

### 9.4 Historical Storage

- PostgreSQL + TimescaleDB for time-series data
- Retention: configurable (default 1 year)
- Used for backtesting and performance analysis

---

## 10. Backtesting

### 10.1 Principle

The **same Decision Engine** runs on historical data. No separate backtest logic.

### 10.2 Flow

```
Historical OHLCV → Data replay → Agents generate signals
→ Decision Engine scores → Simulated execution → P&L report
```

### 10.3 Output Metrics

- Win rate
- Profit factor
- Max drawdown
- Sharpe ratio
- Average trade duration
- Total return vs buy-and-hold

### 10.4 Modes

| Mode | Description |
|------|-------------|
| `dry-run` | Paper trading with live data, no real orders |
| `backtest` | Replay historical data |
| `live` | Real trading with real money |

---

## 11. Observability

### 11.1 Logging

- JSON structured logging for all components
- Log levels: DEBUG (dev), INFO (prod), WARNING, ERROR
- Correlation IDs for tracing signal → decision → execution

### 11.2 Metrics (Prometheus)

| Metric | Type | Description |
|--------|------|-------------|
| `signals_total` | Counter | Signals emitted per agent |
| `decisions_total` | Counter | Decisions made (buy/sell/hold) |
| `orders_executed` | Counter | Orders sent to Freqtrade |
| `orders_rejected` | Counter | Orders rejected by Risk Engine |
| `portfolio_value` | Gauge | Current portfolio value in USD |
| `drawdown_pct` | Gauge | Current drawdown percentage |
| `agent_latency_ms` | Histogram | Agent execution time |
| `llm_calls_total` | Counter | LLM API calls |
| `llm_errors_total` | Counter | LLM API errors |

### 11.3 Alerts

- Trade executed (all channels)
- Kill switch triggered (urgent)
- Agent failure (error channel)
- LLM API error (warning)
- Drawdown > threshold (urgent)

---

## 12. Configuration

### 12.1 Config File (config/default.yaml)

```yaml
llm:
  provider: openai
  model: gpt-4o-mini
  # Fallback providers configured via .env

data_sources:
  ccxt:
    exchange: binance
    api_key: "${CCXT_API_KEY}"
    secret: "${CCXT_SECRET}"
  coingecko:
    api_key: "${COINGECKO_API_KEY}"
  cryptopanic:
    api_key: "${CRYPTOPANIC_API_KEY}"
  lunarcrush:
    api_key: "${LUNARCRUSH_API_KEY}"

trading:
  pairs:
    - BTC/USDT
    - ETH/USDT
    - SOL/USDT
  timeframe: 1h
  mode: dry-run  # dry-run | backtest | live

risk:
  max_positions: 5
  risk_per_trade: 0.01
  max_exposure_pct: 0.30
  stop_loss_pct: 0.02
  max_daily_loss_pct: 0.05
  max_drawdown_pct: 0.20

decision:
  weights:
    technical: 0.40
    sentiment: 0.25
    momentum: 0.20
    ml: 0.15
  buy_threshold: 0.7
  sell_threshold: -0.7

execution:
  freqtrade_url: http://freqtrade:8080
  freqtrade_api_key: "${FREQTRADE_API_KEY}"
  rate_limit_per_minute: 10

schedule:
  analyst: "*/15 * * * *"
  news: "0 * * * *"
  risk_check_interval_sec: 30

notifications:
  telegram:
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  discord:
    webhook_url: "${DISCORD_WEBHOOK_URL}"
  slack:
    webhook_url: "${SLACK_WEBHOOK_URL}"
```

### 12.2 Environment Variables (.env)

```env
# LLM Providers (at least one required)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
OLLAMA_API_BASE=

# Exchange
CCXT_API_KEY=
CCXT_SECRET=

# Data Sources (optional)
COINGECKO_API_KEY=
CRYPTOPANIC_API_KEY=
LUNARCRUSH_API_KEY=
SERPAPI_API_KEY=

# Freqtrade
FREQTRADE_API_KEY=

# Notifications (at least one recommended)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
SLACK_WEBHOOK_URL=
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVERS=
```

---

## 13. Docker Deployment

### 13.1 Services

```yaml
services:
  gateway:
    build:
      context: .
      dockerfile: docker/Dockerfile.gateway
    depends_on:
      - redis
      - postgres
      - freqtrade
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'

  freqtrade:
    image: freqtradeorg/freqtrade:stable
    volumes:
      - ./config/freqtrade:/freqtrade/config
      - ./strategies:/freqtrade/strategies
      - freqtrade_data:/freqtrade/data
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/v1/ping"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 5s
      retries: 3

  postgres:
    image: timescale/timescaledb:latest-pg16
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: fkcrypto
      POSTGRES_USER: fkcrypto
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fkcrypto"]
      interval: 30s
      timeout: 5s
      retries: 3

  dashboard:
    build:
      context: .
      dockerfile: docker/Dockerfile.dashboard
    ports:
      - "8501:8501"
    depends_on:
      - postgres
    env_file: .env
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./docker/nginx/certs:/etc/nginx/certs
    depends_on:
      - gateway
      - dashboard
    restart: unless-stopped

  litellm:
    image: ghcr.io/berriai/litellm:main
    ports:
      - "4000:4000"
    volumes:
      - ./litellm_config.yaml:/app/config.yaml
    env_file: .env
    restart: unless-stopped
    profiles:
      - llm-proxy  # optional, only if using LiteLLM proxy mode

volumes:
  postgres_data:
  redis_data:
  freqtrade_data:

networks:
  default:
    name: fkcrypto-network
```

### 13.2 Dockerfile.gateway (multi-stage)

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && rm -rf /var/lib/apt/lists/*

FROM base AS dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM dependencies AS runtime
COPY src/ ./src/
COPY config/ ./config/
COPY pyproject.toml .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["python", "-m", "src.gateway"]
```

### 13.3 Quick Start

```bash
# 1. Clone and configure
git clone <repo> && cd fkcrypto
cp .env.example .env
# Edit .env with your API keys

# 2. Start all services
docker compose up -d

# 3. Check health
docker compose ps

# 4. View logs
docker compose logs -f gateway

# 5. Access dashboard
open http://localhost:8501
```

---

## 14. Notification Channels

Multi-channel notifications, enabled by presence of credentials in config:

| Channel | Trigger | Priority |
|---------|---------|----------|
| Telegram | All trades, alerts, kill switch | High |
| Discord | Trade summaries, daily reports | Medium |
| Slack | System alerts, errors | High |
| Email | Daily/weekly reports | Low |

---

## 15. Strategy Skills (extensible)

Inspired by daily_stock_analysis — strategies are YAML/MD files, no code needed:

```yaml
# config/strategies/mean_reversion.yaml
name: Mean Reversion
description: Buy when RSI < 30, sell when RSI > 70
conditions:
  - indicator: RSI
    period: 14
    buy_when: "< 30"
    sell_when: "> 70"
  - indicator: BollingerBands
    period: 20
    buy_when: "price < lower_band"
    sell_when: "price > upper_band"
weight: 0.3
enabled: true
```

---

## 16. Error Handling & Fallbacks

| Failure | Fallback |
|---------|----------|
| LLM API down | Use cached analysis, skip sentiment signals |
| Exchange API down | Pause trading, alert via notifications |
| Redis down | Direct function calls (degraded mode) |
| Database down | In-memory cache, sync on recovery |
| Freqtrade down | Queue orders, retry on recovery |

---

## 17. Security

- API keys stored in `.env`, never committed
- Freqtrade REST API requires authentication
- Internal APIs use service-to-service auth (shared secret)
- Database credentials via Docker secrets
- Rate limiting on all external API calls
- Kill switch accessible via manual override
