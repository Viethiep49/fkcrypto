# FKCrypto Configuration Guide

Complete reference for configuring the FKCrypto AI trading system.

## Table of Contents

- [Overview](#overview)
- [Configuration Architecture](#configuration-architecture)
- [Environment Variables](#environment-variables)
- [Main Configuration (default.yaml)](#main-configuration-defaultyaml)
  - [LLM Configuration](#llm-configuration)
  - [Data Sources](#data-sources)
  - [Trading Configuration](#trading-configuration)
  - [Risk Management](#risk-management)
  - [Decision Engine](#decision-engine)
  - [Execution Engine](#execution-engine)
  - [Scheduler](#scheduler)
  - [Notifications](#notifications)
- [Exchange Configuration (exchanges.yaml)](#exchange-configuration-exchangesyaml)
- [Notification Configuration (notifications.yaml)](#notification-configuration-notificationsyaml)
- [Strategy Configuration](#strategy-configuration)
  - [Bull Trend Strategy](#bull-trend-strategy)
  - [Mean Reversion Strategy](#mean-reversion-strategy)
  - [Momentum Breakout Strategy](#momentum-breakout-strategy)
  - [News Sentiment Strategy](#news-sentiment-strategy)
  - [Portfolio Rebalancer](#portfolio-rebalancer)
  - [Scalping EMA Strategy](#scalping-ema-strategy)
  - [Whale Watcher Strategy](#whale-watcher-strategy)
- [Configuration Loader](#configuration-loader)
- [Best Practices](#best-practices)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

---

## Overview

FKCrypto uses a three-layer configuration system that combines the flexibility of YAML files with the security of environment variables:

1. **YAML Files** - Human-readable configuration stored in `config/`
2. **Environment Variables** - Secrets and environment-specific values stored in `.env`
3. **Variable Substitution** - `${VAR_NAME}` placeholders in YAML are resolved from environment variables at load time

This architecture ensures:
- Secrets never appear in version control
- Easy environment switching (dev/staging/production)
- Clear separation of concerns
- Hot-reloadable configuration for non-critical settings

---

## Configuration Architecture

```
fkcrypto/
├── .env                          # Environment-specific secrets
├── .env.example                  # Template for required env vars
├── config/
│   ├── default.yaml              # Main configuration
│   ├── exchanges.yaml            # Per-exchange settings
│   ├── notifications.yaml        # Notification channel config
│   └── strategies/               # Strategy-specific configs
│       ├── bull-trend.yaml
│       ├── mean-reversion.yaml
│       ├── momentum-breakout.yaml
│       ├── news-sentiment.yaml
│       ├── portfolio-rebalancer.yaml
│       ├── scalping-ema.yaml
│       └── whale-watcher.yaml
└── litellm_config.example.yaml   # LiteLLM proxy configuration
```

### Configuration Loading Order

1. Load `.env` file via `python-dotenv`
2. Parse YAML files
3. Resolve `${VAR_NAME}` placeholders with environment variables
4. Merge strategy configs into main configuration
5. Validate final configuration schema

---

## Environment Variables

All sensitive values and environment-specific settings are managed through environment variables. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

### Exchange API Keys

| Variable | Description | Required |
|----------|-------------|----------|
| `BINANCE_API_KEY` | Binance API key | Yes |
| `BINANCE_API_SECRET` | Binance API secret | Yes |
| `BYBIT_API_KEY` | Bybit API key | No |
| `BYBIT_API_SECRET` | Bybit API secret | No |
| `OKX_API_KEY` | OKX API key | No |
| `OKX_API_SECRET` | OKX API secret | No |
| `OKX_PASSPHRASE` | OKX API passphrase | No |

### Data Source API Keys

| Variable | Description | Required |
|----------|-------------|----------|
| `COINGECKO_API_KEY` | CoinGecko API key | No |
| `CRYPTOPANIC_API_KEY` | CryptoPanic news API key | No |
| `LUNARCRUSH_API_KEY` | LunarCrush social metrics API key | No |
| `SERPAPI_API_KEY` | SERP API for web search | No |

### LLM Provider Keys

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key (for GPT models) | Yes* |
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude models) | No |
| `GOOGLE_API_KEY` | Google API key (for Gemini models) | No |

*Required if using OpenAI as the LLM provider.

### Notification Credentials

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | No |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for messages | No |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | No |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL | No |

### Infrastructure

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `FREQTRADE_API_KEY` | FreqTrade bot API key | No |

### Example .env File

```env
# Exchange API Keys
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_API_SECRET=your_binance_api_secret_here

# Data Sources
COINGECKO_API_KEY=your_coingecko_api_key
CRYPTOPANIC_API_KEY=your_cryptopanic_api_key
LUNARCRUSH_API_KEY=your_lunarcrush_api_key
SERPAPI_API_KEY=your_serpapi_api_key

# LLM Provider
OPENAI_API_KEY=sk-proj-your_openai_key_here

# Notifications
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Infrastructure
DATABASE_URL=postgresql://user:password@localhost:5432/fkcrypto
REDIS_URL=redis://localhost:6379/0

# FreqTrade Integration
FREQTRADE_API_KEY=your_freqtrade_api_key
```

---

## Main Configuration (default.yaml)

The `config/default.yaml` file is the primary configuration file. All sections are described below.

### LLM Configuration

Controls the language model used for sentiment analysis and decision reasoning.

```yaml
llm:
  provider: litellm          # LLM provider (litellm, openai, anthropic)
  model: gpt-4o-mini         # Primary model to use
  temperature: 0.3           # Creativity (0.0-1.0, lower = more deterministic)
  max_tokens: 1000           # Maximum response tokens
  timeout: 30                # Request timeout in seconds
  retries: 3                 # Number of retry attempts on failure
  fallback_model: gpt-3.5-turbo  # Fallback if primary model fails
```

**Model Recommendations:**

| Use Case | Recommended Model | Temperature |
|----------|-------------------|-------------|
| Production trading | `gpt-4o` | 0.1-0.2 |
| Development/testing | `gpt-4o-mini` | 0.3 |
| Cost optimization | `gpt-3.5-turbo` | 0.3 |
| Complex reasoning | `claude-3-5-sonnet` | 0.2 |

### Data Sources

Configures all external data providers. API keys are injected via environment variables.

```yaml
data_sources:
  ccxt:
    exchange: binance        # Primary exchange via CCXT
    api_key: ${BINANCE_API_KEY}
    api_secret: ${BINANCE_API_SECRET}
  coingecko:
    api_key: ${COINGECKO_API_KEY}
  cryptopanic:
    api_key: ${CRYPTOPANIC_API_KEY}
  lunarcrush:
    api_key: ${LUNARCRUSH_API_KEY}
  serpapi:
    api_key: ${SERPAPI_API_KEY}
```

### Trading Configuration

Defines which assets to trade and operational mode.

```yaml
trading:
  pairs:
    - BTC/USDT
    - ETH/USDT
    - SOL/USDT
    - BNB/USDT
    - XRP/USDT
  timeframe: 1h              # Candlestick interval
  mode: paper                # paper | live
```

**Trading Modes:**

| Mode | Description | Use Case |
|------|-------------|----------|
| `paper` | Simulated trading with real market data | Testing, development |
| `live` | Real order execution on exchange | Production |

**Common Timeframes:**

| Timeframe | Strategy Type | Latency Sensitivity |
|-----------|---------------|---------------------|
| `1m`, `5m` | Scalping | Very High |
| `15m`, `30m` | Day Trading | High |
| `1h`, `4h` | Swing Trading | Medium |
| `1d` | Position Trading | Low |

### Risk Management

Critical parameters that protect capital. These should be tuned conservatively.

```yaml
risk:
  max_positions: 5           # Maximum concurrent open positions
  risk_per_trade: 0.02       # 2% of portfolio risked per trade
  max_exposure: 0.50         # 50% maximum portfolio exposure
  stop_loss: 0.05            # 5% stop loss from entry
  max_daily_loss: 0.05       # 5% maximum daily loss (halts trading)
  max_drawdown: 0.15         # 15% maximum drawdown (halts system)
```

**Risk Parameter Guidelines:**

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| `risk_per_trade` | 0.01 (1%) | 0.02 (2%) | 0.05 (5%) |
| `max_exposure` | 0.30 (30%) | 0.50 (50%) | 0.80 (80%) |
| `stop_loss` | 0.03 (3%) | 0.05 (5%) | 0.10 (10%) |
| `max_daily_loss` | 0.03 (3%) | 0.05 (5%) | 0.10 (10%) |
| `max_drawdown` | 0.10 (10%) | 0.15 (15%) | 0.25 (25%) |

### Decision Engine

Controls how signals from different analyzers are weighted and combined.

```yaml
decision:
  weights:
    technical: 0.30          # Technical analysis weight
    sentiment: 0.20          # News/sentiment analysis weight
    momentum: 0.20           # Momentum indicators weight
    risk: 0.15               # Risk assessment weight
    ml: 0.10                 # Machine learning model weight
    on_chain: 0.05           # On-chain data weight
  thresholds:
    buy: 0.6                 # Composite score to trigger buy
    sell: -0.6               # Composite score to trigger sell
    min_confidence: 0.5      # Minimum confidence for any signal
```

**Weight Adjustment Guidelines:**

- Weights must sum to `1.0`
- Increase `technical` weight for trend-following strategies
- Increase `sentiment` weight for news-driven strategies
- Increase `ml` weight when ML models are well-trained
- Set `on_chain` higher when whale tracking data is reliable

### Execution Engine

Configures order execution and external bot integration.

```yaml
execution:
  freqtrade:
    url: http://freqtrade:8080
    api_key: ${FREQTRADE_API_KEY}
  rate_limit: 10             # Maximum orders per minute
  dry_run: true              # Simulate orders without submitting
```

### Scheduler

Defines how frequently each component runs.

```yaml
schedule:
  analyst_interval: 300      # 5 minutes - Technical analysis cycle
  news_interval: 900         # 15 minutes - News/sentiment refresh
  risk_check_interval: 60    # 1 minute - Risk monitoring
```

**Scheduler Tuning:**

| Component | Min Interval | Recommended | Max Interval |
|-----------|--------------|-------------|--------------|
| Analyst | 60s | 300s | 3600s |
| News | 300s | 900s | 3600s |
| Risk Check | 10s | 60s | 300s |

### Notifications

Quick toggle for notification channels. Full configuration is in `notifications.yaml`.

```yaml
notifications:
  telegram:
    enabled: false
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
  discord:
    enabled: false
    webhook_url: ${DISCORD_WEBHOOK_URL}
  slack:
    enabled: false
    webhook_url: ${SLACK_WEBHOOK_URL}
```

---

## Exchange Configuration (exchanges.yaml)

Per-exchange settings for rate limits, order types, and exchange-specific behavior.

```yaml
exchanges:
  binance:
    enabled: true
    rate_limit: 1200         # Requests per minute
    order_types:
      - market
      - limit
      - stop_loss
      - stop_loss_limit
    sandbox: false
    options:
      defaultType: spot
      recvWindow: 5000

  bybit:
    enabled: false
    rate_limit: 600
    order_types:
      - market
      - limit
      - conditional
    sandbox: false
    options:
      defaultType: linear

  okx:
    enabled: false
    rate_limit: 600
    order_types:
      - market
      - limit
      - stop
    sandbox: false
    options:
      defaultType: spot
```

---

## Notification Configuration (notifications.yaml)

Detailed notification channel settings.

```yaml
notifications:
  telegram:
    enabled: false
    bot_token: ${TELEGRAM_BOT_TOKEN}
    chat_id: ${TELEGRAM_CHAT_ID}
    parse_mode: Markdown
    disable_notification: false

  discord:
    enabled: false
    webhook_url: ${DISCORD_WEBHOOK_URL}
    username: FKCrypto Bot
    avatar_url: ""

  slack:
    enabled: false
    webhook_url: ${SLACK_WEBHOOK_URL}
    channel: "#trading-alerts"
    username: FKCrypto Bot

  email:
    enabled: false
    smtp_host: smtp.gmail.com
    smtp_port: 587
    username: ${EMAIL_USERNAME}
    password: ${EMAIL_PASSWORD}
    recipients:
      - admin@example.com
```

**Priority Levels:**

| Level | Description | Channels |
|-------|-------------|----------|
| `info` | Routine updates (trade executed, analysis complete) | All enabled |
| `warning` | Attention needed (high exposure, unusual activity) | All enabled |
| `critical` | Immediate action required (max drawdown hit, system error) | All enabled + email |

---

## Strategy Configuration

Strategy files live in `config/strategies/`. Each strategy has an `enabled` flag and strategy-specific parameters.

### Bull Trend Strategy

**File:** `config/strategies/bull-trend.yaml`
**Status:** Enabled by default
**Type:** Trend-following

```yaml
strategy:
  name: bull-trend
  enabled: true
  description: "EMA crossover trend-following strategy"

  indicators:
    fast_ema_period: 9
    slow_ema_period: 21
    confirmation_ema: 50

  signals:
    entry:
      condition: "fast_ema > slow_ema"
      confirmation: "price > confirmation_ema"
    exit:
      condition: "fast_ema < slow_ema"

  multi_timeframe:
    enabled: true
    higher_timeframe: 4h
    alignment_required: true

  risk:
    stop_loss: 0.05
    take_profit: 0.15
    trailing_stop: 0.03
```

### Mean Reversion Strategy

**File:** `config/strategies/mean-reversion.yaml`
**Status:** Enabled by default
**Type:** Mean reversion

```yaml
strategy:
  name: mean-reversion
  enabled: true
  description: "Bollinger Bands + RSI mean reversion"

  indicators:
    bb_period: 20
    bb_std_dev: 2.0
    rsi_period: 14
    rsi_oversold: 30
    rsi_overbought: 70

  signals:
    entry:
      condition: "price <= lower_bb AND rsi <= rsi_oversold"
    exit:
      condition: "price >= upper_bb AND rsi >= rsi_overbought"

  filters:
    min_volume: 1.5        # Volume must be 1.5x average
    trend_filter: false    # Don't filter by trend direction
```

### Momentum Breakout Strategy

**File:** `config/strategies/momentum-breakout.yaml`
**Status:** Enabled by default
**Type:** Breakout

```yaml
strategy:
  name: momentum-breakout
  enabled: true
  description: "Donchian Channel breakout with volume confirmation"

  indicators:
    donchian_period: 20
    volume_sma_period: 20
    volume_spike_multiplier: 2.0

  signals:
    entry:
      condition: "price > donchian_upper AND volume > volume_sma * volume_spike_multiplier"
    exit:
      condition: "price < donchian_lower"

  filters:
    min_adx: 25           # Minimum ADX for trend strength
    cooldown_periods: 3   # Bars to wait after exit before re-entry
```

### News Sentiment Strategy

**File:** `config/strategies/news-sentiment.yaml`
**Status:** Enabled by default
**Type:** LLM-based sentiment

```yaml
strategy:
  name: news-sentiment
  enabled: true
  description: "LLM-powered news sentiment analysis trading"

  sentiment:
    sources:
      - cryptopanic
      - serpapi
    positive_threshold: 0.6
    negative_threshold: -0.6
    neutral_range: [-0.2, 0.2]

  signals:
    entry:
      condition: "sentiment_score >= positive_threshold"
    exit:
      condition: "sentiment_score <= negative_threshold"

  llm:
    model: gpt-4o-mini
    max_articles: 10
    analysis_window: 3600  # 1 hour lookback
```

### Portfolio Rebalancer

**File:** `config/strategies/portfolio-rebalancer.yaml`
**Status:** Enabled by default
**Type:** Portfolio management

```yaml
strategy:
  name: portfolio-rebalancer
  enabled: true
  description: "Automated portfolio rebalancing to target allocations"

  allocation:
    BTC: 0.40
    ETH: 0.30
    SOL: 0.15
    USDT: 0.15

  rebalance:
    trigger: "drift"         # drift | time | both
    max_drift: 0.05          # 5% deviation triggers rebalance
    interval: 86400          # 24 hours (if time-based)
    min_trade_size: 10       # Minimum trade size in USDT
```

### Scalping EMA Strategy

**File:** `config/strategies/scalping-ema.yaml`
**Status:** Disabled by default
**Type:** Scalping

```yaml
strategy:
  name: scalping-ema
  enabled: false
  description: "Short-term EMA scalping strategy"

  timeframe: 5m

  indicators:
    fast_ema: 5
    slow_ema: 13
    signal_ema: 21

  signals:
    entry:
      condition: "fast_ema > slow_ema AND fast_ema > signal_ema"
    exit:
      condition: "fast_ema < slow_ema"

  risk:
    stop_loss: 0.01         # Tight 1% stop
    take_profit: 0.02       # Quick 2% target
    max_hold_time: 1800     # 30 minutes max hold
```

### Whale Watcher Strategy

**File:** `config/strategies/whale-watcher.yaml`
**Status:** Disabled by default
**Type:** On-chain analysis

```yaml
strategy:
  name: whale-watcher
  enabled: false
  description: "On-chain whale movement tracking"

  whale_threshold:
    btc: 100                # 100 BTC minimum transaction
    eth: 1000               # 1000 ETH minimum transaction

  signals:
    entry:
      condition: "net_exchange_flow < 0 AND whale_count > threshold"
    exit:
      condition: "net_exchange_flow > 0"

  monitoring:
    wallets:
      - label: "Binance Hot Wallet"
        address: "0x..."
      - label: "Unknown Whale"
        address: "0x..."
    interval: 300           # 5 minutes
```

---

## Configuration Loader

The configuration is loaded via `src/utils/config.py`.

### Basic Usage

```python
from src.utils.config import load_config

# Load all configuration
config = load_config()

# Access nested values
model = config['llm']['model']
pairs = config['trading']['pairs']
risk_per_trade = config['risk']['risk_per_trade']
```

### How It Works

```python
# Simplified loading process
def load_config(config_path="config/default.yaml"):
    # 1. Load .env file
    load_dotenv()

    # 2. Read YAML file
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # 3. Resolve ${VAR} placeholders
    config = resolve_env_vars(config)

    # 4. Load and merge strategy configs
    strategies = load_strategies("config/strategies/")
    config['strategies'] = strategies

    return config
```

### Variable Substitution

Any value in YAML matching `${VAR_NAME}` is replaced with the corresponding environment variable:

```yaml
# config/default.yaml
data_sources:
  ccxt:
    api_key: ${BINANCE_API_KEY}  # Replaced at load time
```

If the environment variable is not set, the placeholder remains as-is. Use defaults with `${VAR_NAME:-default_value}` syntax:

```yaml
llm:
  model: ${LLM_MODEL:-gpt-4o-mini}
```

---

## Best Practices

### Security

1. **Never commit `.env` files** - Add `.env` to `.gitignore`
2. **Rotate API keys regularly** - Especially exchange API keys
3. **Use read-only API keys** where possible for data sources
4. **Restrict exchange API permissions** - Disable withdrawal permissions
5. **Use IP whitelisting** on exchange API keys when available

### Environment Management

1. **Maintain separate `.env` files** for each environment:
   ```
   .env.development
   .env.staging
   .env.production
   ```

2. **Use environment-specific config overrides:**
   ```yaml
   # config/default.yaml
   trading:
     mode: ${TRADING_MODE:-paper}
   ```

3. **Document all required variables** in `.env.example`

### Risk Configuration

1. **Start conservative** - Use lower risk parameters initially
2. **Paper trade first** - Run in `paper` mode for at least 2 weeks
3. **Set hard limits** - `max_drawdown` should always be set
4. **Monitor daily** - Check `max_daily_loss` triggers
5. **Gradually increase** - Scale up risk parameters as confidence grows

### Strategy Management

1. **Enable one strategy at a time** when testing
2. **Use different timeframes** for different strategies to avoid correlation
3. **Set `enabled: false`** for strategies not in use
4. **Version control strategy configs** - Track parameter changes
5. **Backtest before enabling** - Validate parameters historically

---

## Common Patterns

### Production Setup

```yaml
# config/default.yaml (production)
trading:
  mode: live
  pairs:
    - BTC/USDT
    - ETH/USDT

risk:
  max_positions: 3
  risk_per_trade: 0.01
  max_exposure: 0.30
  stop_loss: 0.03
  max_daily_loss: 0.03
  max_drawdown: 0.10

execution:
  dry_run: false
  rate_limit: 5

notifications:
  telegram:
    enabled: true
  discord:
    enabled: true
```

### Development Setup

```yaml
# config/default.yaml (development)
trading:
  mode: paper
  pairs:
    - BTC/USDT

llm:
  model: gpt-4o-mini
  temperature: 0.5

risk:
  max_positions: 10
  risk_per_trade: 0.05
  max_exposure: 0.80

execution:
  dry_run: true
```

### Multi-Exchange Setup

```yaml
# config/exchanges.yaml
exchanges:
  binance:
    enabled: true
    role: primary
  bybit:
    enabled: true
    role: secondary
  okx:
    enabled: true
    role: arbitrage
```

### Cost-Optimized LLM Setup

```yaml
llm:
  provider: litellm
  model: gpt-4o-mini
  fallback_model: gpt-3.5-turbo
  timeout: 30
  retries: 2

# Use cheaper model for high-frequency tasks
decision:
  weights:
    technical: 0.40
    sentiment: 0.10    # Reduced - LLM calls are expensive
    momentum: 0.25
    risk: 0.15
    ml: 0.10
    on_chain: 0.00     # Disabled if not using
```

---

## Troubleshooting

### Environment Variables Not Resolving

**Symptom:** `${VAR_NAME}` appears literally in config values.

**Fix:**
1. Verify `.env` file exists in project root
2. Check variable name spelling matches exactly
3. Ensure no spaces around `=` in `.env`: `KEY=value` (not `KEY = value`)
4. Restart the application after changing `.env`

### API Key Errors

**Symptom:** Authentication failures with exchanges or data sources.

**Fix:**
1. Verify API key has correct permissions
2. Check IP whitelist settings on exchange
3. Confirm API key is not expired
4. Test key manually with exchange API

### Configuration Validation Errors

**Symptom:** Application fails to start with config errors.

**Fix:**
1. Validate YAML syntax: `python -c "import yaml; yaml.safe_load(open('config/default.yaml'))"`
2. Check all required fields are present
3. Verify numeric values are not quoted strings
4. Ensure weights in `decision.weights` sum to 1.0

### Strategy Not Triggering

**Symptom:** Enabled strategy produces no signals.

**Fix:**
1. Verify `enabled: true` in strategy config
2. Check indicator parameters are reasonable
3. Confirm trading pairs have sufficient volume
4. Review timeframe matches data availability
5. Check thresholds are not too strict

### Notification Failures

**Symptom:** Notifications not being delivered.

**Fix:**
1. Verify webhook URLs / bot tokens are correct
2. Check channel permissions (Telegram bot must be in group)
3. Test webhook manually with curl
4. Verify notification channel is `enabled: true`
