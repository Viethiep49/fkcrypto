# FKCrypto — Crypto Trading Agent System

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-green.svg)](https://www.docker.com/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A hybrid multi-agent architecture that combines **deterministic technical analysis** with **LLM-assisted sentiment analysis** to make cryptocurrency trading decisions. Integrates with [Freqtrade](https://www.freqtrade.io/) for actual order execution.

---

## Table of Contents

- [Core Design Principles](#core-design-principles)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Trading Pairs](#trading-pairs)
- [Trading Strategies](#trading-strategies)
- [Risk Management](#risk-management)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Monitoring & Dashboard](#monitoring--dashboard)
- [Project Structure](#project-structure)
- [Development](#development)
- [Testing](#testing)
- [Backtesting](#backtesting)
- [Notifications](#notifications)
- [Safety Warnings](#safety-warnings)
- [License](#license)

---

## Core Design Principles

| Principle | Description |
|-----------|-------------|
| **Deterministic first, LLM second** | All trading decisions are reproducible. LLMs assist with analysis and explanation only — they never override deterministic scoring. |
| **Agents emit signals, not decisions** | Each agent produces normalized `Signal` objects. A central `DecisionEngine` aggregates and decides. |
| **Independent safety boundaries** | A separate `RiskEngine` and `ExecutionService` validate every order before it reaches Freqtrade. |
| **Everything must be backtestable** | The same `DecisionEngine` runs on historical data for backtesting and live data for trading. |
| **Explainable by default** | Every signal carries structured reasoning — no black box decisions. |
| **Human-in-the-loop ready** | Approval requests can gate execution — the bot proposes, you decide. |
| **Security-first** | All external content is scanned for prompt injection before LLM processing. |

---

## Key Features

- **Multi-agent system** — Technical Analyst, News Sentiment, Market Monitor, Risk Guardian, and Alpha Seeker agents working in parallel
- **LangGraph-based orchestration** — Parallel agent execution with deterministic graph routing
- **12+ technical indicators** — RSI, MACD, EMA, Bollinger Bands, ATR, Stochastic, ADX, Donchian Channels, and more
- **LLM-powered sentiment analysis** — Real-time analysis of news articles and social media signals
- **Alpha Seeker** — Hunts high-impact events (listings, whale movements, KOL tweets) that move prices before indicators react
- **Explainable AI** — Every agent generates structured reasoning explaining "why" it made each signal
- **Human-in-the-loop** — Approval requests with approve/reject buttons — you keep final control
- **Dynamic position sizing** — Position sizes adjust based on signal convergence (agent agreement)
- **Real-time anomaly detection** — Price spikes, volume anomalies, and flash crash detection
- **Prompt injection protection** — 20+ pattern detectors sanitize all external content before LLM processing
- **Risk management** — Kill switch, drawdown monitoring, position limits
- **Backtesting engine** — Realistic simulation with slippage, fees, and market impact
- **Visual backtest replay** — Replay any past decision with full market context
- **Streamlit monitoring dashboard** — Real-time portfolio visualization, agent reasoning, and approval panel
- **Docker deployment** — 9-service stack: gateway, freqtrade, redis, postgres, dashboard, nginx, litellm, prometheus, grafana
- **Prometheus metrics** — Full observability with Grafana dashboards and alerting
- **Multi-channel notifications** — Telegram, Discord, and Slack integration

---

## Architecture

### Agent Execution Flow

```
                     (parallel)
market_monitor ────────┐
analyst      ──────────┼──→ decision ──→ execution ──→ END
sentiment    ──────────┤
alpha        ──────────┤
risk         ──────────┘
```

1. **Market Monitor** — Detects anomalies, regime changes, and market health signals
2. **Technical Analyst** — Computes indicators and generates technical signals
3. **Sentiment Agent** — Analyzes news/social media for market sentiment
4. **Alpha Seeker** — Hunts high-impact events (listings, whales, KOLs)
5. **Risk Guardian** — Validates risk boundaries and portfolio constraints
6. **Decision Engine** — Aggregates all signals and produces a final trading decision
7. **Execution Service** — Validates and routes orders to Freqtrade (with optional human approval)

### Signal Flow

```
Data Sources → Agents → Signal[] → DecisionEngine → Decision → RiskEngine → ExecutionService → Freqtrade
```

Every order passes through independent validation layers. No single agent can bypass the risk checks.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Language** | Python 3.11+ |
| **Agent Orchestration** | LangGraph |
| **Exchange Data** | ccxt |
| **LLM Abstraction** | LiteLLM |
| **Database** | SQLAlchemy + PostgreSQL / TimescaleDB |
| **Order Execution** | Freqtrade |
| **Message Bus** | Redis (production) / In-memory (dev) |
| **Dashboard** | Streamlit |
| **Deployment** | Docker Compose |
| **Monitoring** | Prometheus + Grafana |
| **Testing** | pytest |

---

## Trading Pairs

| Pair | Base | Quote |
|------|------|-------|
| BTC/USDT | Bitcoin | Tether |
| ETH/USDT | Ethereum | Tether |
| SOL/USDT | Solana | Tether |
| BNB/USDT | Binance Coin | Tether |
| XRP/USDT | Ripple | Tether |

---

## Trading Strategies

FKCrypto ships with five built-in strategies. Each strategy is defined in `config/strategies/` and can be enabled or disabled independently.

| Strategy | Indicators | Market Condition |
|----------|-----------|------------------|
| **Bull Trend** | EMA crossover | Strong uptrends |
| **Mean Reversion** | Bollinger Bands + RSI | Ranging / overextended markets |
| **Momentum Breakout** | Donchian Channels + Volume | Breakout from consolidation |
| **News Sentiment** | LLM-based analysis | Event-driven moves |
| **Portfolio Rebalancer** | Portfolio weights | Periodic rebalancing |

Strategies are evaluated by the `DecisionEngine`, which scores and ranks signals before producing a final decision.

---

## Risk Management

FKCrypto enforces strict risk boundaries at every layer. These limits are independent of agent signals and cannot be overridden.

| Parameter | Value | Description |
|-----------|-------|-------------|
| Max positions | 5 | Maximum concurrent open positions |
| Risk per trade | 2% | Maximum portfolio risk per single trade |
| Max exposure | 50% | Maximum total portfolio exposure |
| Stop loss | 5% | Automatic stop loss on every position |
| Max daily loss | 5% | Trading halts after 5% daily loss |
| Max drawdown | 15% | Kill switch triggers at 15% drawdown |

### Kill Switch

An independent kill switch system monitors portfolio health and immediately halts all trading when thresholds are breached. It operates outside the agent loop and cannot be bypassed by any signal.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- API keys for your exchange and LLM provider

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd fkcrypto

# Install dependencies
pip install -e .

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Running with Docker

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f gateway

# Stop all services
docker compose down
```

### Running Directly

```bash
# Start the gateway (main orchestrator)
python -m src.gateway

# Run backtesting
python -m src.backtesting --config config/backtest.yaml
```

---

## Configuration

All configuration is managed through YAML files in `config/` and environment variables via `.env`.

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `EXCHANGE_API_KEY` | Exchange API key | Yes |
| `EXCHANGE_SECRET` | Exchange API secret | Yes |
| `LLM_API_KEY` | LiteLLM provider API key | Yes |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | No |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | No |
| `SLACK_WEBHOOK_URL` | Slack webhook URL | No |

### Strategy Configuration

Strategies are defined in `config/strategies/`. Each strategy file specifies:

- Entry and exit conditions
- Indicator parameters
- Timeframes
- Risk overrides (optional)

```yaml
# config/strategies/bull_trend.yaml
name: bull_trend
enabled: true
timeframe: 1h
indicators:
  ema_fast: 9
  ema_slow: 21
  rsi_period: 14
risk:
  stop_loss_pct: 0.05
  take_profit_pct: 0.10
```

---

## Deployment

### Docker Services

| Service | Port | Description |
|---------|------|-------------|
| `gateway` | — | LangGraph orchestrator (main agent loop) |
| `freqtrade` | 8080 | Trading engine and order execution |
| `redis` | 6379 | Message bus and caching |
| `postgres` | 5432 | Persistent data storage |
| `dashboard` | 8501 | Streamlit monitoring UI |
| `nginx` | 80 | Reverse proxy |
| `litellm` | 4000 | LLM API proxy |
| `prometheus` | 9090 | Metrics collection |
| `grafana` | 3000 | Metrics visualization |

### Starting the Stack

```bash
# Start all services
docker compose up -d

# Start specific services
docker compose up -d gateway freqtrade redis postgres

# Check service health
docker compose ps

# View aggregated logs
docker compose logs -f
```

### Production Notes

- Always use environment variables for secrets — never commit `.env` files
- Run PostgreSQL with persistent volumes for data durability
- Configure nginx with TLS certificates in production
- Set up Prometheus alerting rules for critical thresholds

---

## Monitoring & Dashboard

### Streamlit Dashboard

Access the dashboard at `http://localhost:8501` to view:

- Real-time portfolio performance
- Active positions and P&L
- Agent signals and decisions
- Technical indicator charts
- Risk metrics and alerts
- Trade history and analytics

### Prometheus Metrics

Access metrics at `http://localhost:9090`. Key metrics include:

- `fkcrypto_signals_total` — Total signals generated per agent
- `fkcrypto_orders_executed` — Orders executed with status
- `fkcrypto_portfolio_value` — Current portfolio value
- `fkcrypto_drawdown_pct` — Current drawdown percentage
- `fkcrypto_anomaly_detected` — Anomaly detection events
- `fkcrypto_risk_violations` — Risk boundary violations

### Grafana Dashboards

Access Grafana at `http://localhost:3000` (default: admin/admin) for pre-built dashboards covering:

- Portfolio overview
- Agent performance
- Risk monitoring
- System health

---

## Project Structure

```
fkcrypto/
├── src/
│   ├── agents/              # Multi-agent system
│   │   ├── analyst.py       # Technical analysis agent
│   │   ├── sentiment.py     # News/social sentiment agent
│   │   ├── market_monitor.py # Anomaly detection agent
│   │   └── risk_guardian.py # Risk validation agent
│   ├── backtesting/         # Backtesting engine
│   ├── bus/                 # Message bus (Redis/in-memory)
│   ├── data/                # Data sources
│   │   ├── ccxt_source.py   # Exchange market data
│   │   ├── coingecko.py     # CoinGecko API
│   │   ├── news.py          # News data feeds
│   │   └── social.py        # Social media data
│   ├── database/            # SQLAlchemy models + repository
│   ├── execution/           # Order execution + validation
│   ├── freqtrade_client/    # Freqtrade REST API client
│   ├── gateway/             # LangGraph orchestrator (main entry point)
│   ├── llm/                 # LiteLLM gateway
│   ├── metrics/             # Prometheus metrics
│   ├── risk/                # Risk engine + position sizing
│   └── utils/               # Config, notifications, scheduler
├── config/                  # YAML configuration files
│   └── strategies/          # Trading strategy definitions
├── dashboard/               # Streamlit monitoring UI
├── docker/                  # Docker Compose + Dockerfiles
├── docs/                    # Documentation
├── scripts/                 # Setup and migration scripts
└── tests/                   # Pytest test suite
```

---

## Development

### Setup Development Environment

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Code Quality

```bash
# Format code
black src/ tests/

# Type checking
mypy src/

# Linting
ruff check src/ tests/
```

### Running Individual Components

```bash
# Run only the technical analyst
python -m src.agents.analyst --pair BTC/USDT

# Run sentiment analysis
python -m src.agents.sentiment --pair ETH/USDT

# Check risk status
python -m src.risk --status
```

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test category
pytest tests/agents/
pytest tests/risk/
pytest tests/backtesting/

# Run with verbose output
pytest -v
```

### Test Categories

| Directory | Coverage |
|-----------|----------|
| `tests/agents/` | Agent signal generation and scoring |
| `tests/risk/` | Risk engine validation and kill switch |
| `tests/backtesting/` | Backtesting engine accuracy |
| `tests/execution/` | Order validation and routing |
| `tests/data/` | Data source connectors |
| `tests/integration/` | End-to-end agent pipeline |

---

## Backtesting

The backtesting engine uses the same `DecisionEngine` as live trading, ensuring strategy performance translates to production.

```bash
# Run backtest with default config
python -m src.backtesting --config config/backtest.yaml

# Backtest specific pair and date range
python -m src.backtesting \
  --pair BTC/USDT \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --strategy bull_trend

# Include realistic simulation
python -m src.backtesting \
  --slippage 0.001 \
  --fee 0.001 \
  --initial-capital 10000
```

### Backtesting Features

- Realistic slippage and fee simulation
- Multiple strategy comparison
- Walk-forward optimization support
- Performance metrics: Sharpe ratio, max drawdown, win rate, profit factor
- Trade-by-trade export to CSV

---

## Notifications

FKCrypto supports multi-channel notifications for trade events, risk alerts, and system health.

| Channel | Configuration | Events |
|---------|--------------|--------|
| **Telegram** | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Trades, alerts, daily summary |
| **Discord** | `DISCORD_WEBHOOK_URL` | Trades, alerts, anomalies |
| **Slack** | `SLACK_WEBHOOK_URL` | Trades, alerts, daily summary |

### Notification Events

- Order executed (entry/exit)
- Risk threshold breached
- Kill switch activated
- Anomaly detected
- Daily performance summary
- System health alerts

---

## Safety Warnings

> **DISCLAIMER:** This software is for educational and research purposes only. Cryptocurrency trading carries significant financial risk. Past performance does not guarantee future results.

- **Never trade with money you cannot afford to lose**
- **Always test strategies thoroughly in backtesting before live trading**
- **Start with paper trading or very small positions**
- **Monitor the kill switch and risk metrics at all times**
- **This system is not financial advice**

The authors and contributors are not responsible for any financial losses incurred through the use of this software.

---

## License

[MIT License](../LICENSE)

---

## Contributing

Contributions are welcome. Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Write tests for new functionality
4. Ensure all tests pass (`pytest`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

---

## Acknowledgments

- [Freqtrade](https://www.freqtrade.io/) — Open-source crypto trading bot
- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration framework
- [ccxt](https://github.com/ccxt/ccxt) — Cryptocurrency exchange library
- [LiteLLM](https://github.com/BerriAI/litellm) — LLM API abstraction
