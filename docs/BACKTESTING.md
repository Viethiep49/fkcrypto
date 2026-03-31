# FKCrypto Backtesting Guide

Comprehensive guide to the FKCrypto backtesting system for validating trading strategies against historical data.

## Overview

The backtesting system simulates trading strategies on historical market data with realistic execution modeling. It shares the same `DecisionEngine` used in live trading, ensuring strategy behavior is identical between backtest and production environments.

## Architecture

```
src/backtesting/
├── engine.py          # BacktestEngine - main orchestrator
├── simulator.py       # TradingSimulator - order execution simulation
├── metrics.py         # Performance metrics computation
└── data_replay.py     # DataReplayEngine - historical data replay
```

## Components

### BacktestEngine

The `BacktestEngine` orchestrates the full backtest lifecycle:

1. **Data Replay** - Feeds historical candles through `DataReplayEngine`
2. **Signal Generation** - Strategy processes current market state
3. **Decision Making** - `DecisionEngine` evaluates signals against risk constraints
4. **Simulated Execution** - `TradingSimulator` fills orders with slippage and fees
5. **Metrics Computation** - Aggregates results into comprehensive performance report

```python
from src.backtesting.engine import BacktestEngine

engine = BacktestEngine(
    data_source=ccxt_source,
    decision_engine=decision_engine,
    start_date="2024-01-01",
    end_date="2024-06-01",
    initial_capital=10000,
    slippage=0.001,
    fee=0.001
)

result = engine.run()
```

**Key Design:** Uses the same `DecisionEngine` instance as live trading. This eliminates discrepancies where a strategy performs differently in backtest versus production.

### DataReplayEngine

Replays historical OHLCV data candle-by-candle with strict no-look-ahead guarantees:

- **Sliding Window** - Maintains a lookback period for indicator calculation
- **No Look-Ahead Bias** - Only exposes data available at each candle's timestamp
- **Timeframe Support** - Works with any timeframe configured in the data source

```python
from src.backtesting.data_replay import DataReplayEngine

replay = DataReplayEngine(
    data_source=data_source,
    lookback=100,
    start=start_date,
    end=end_date
)

for candle in replay:
    # candle contains only data available at that point in time
    process(candle)
```

### TradingSimulator

Simulates realistic order execution with configurable market impact:

- **Slippage Model** - Configurable percentage-based slippage on fills
- **Fee Structure** - Supports maker/taker fee simulation
- **Portfolio Tracking** - Maintains real-time balance, positions, and equity
- **Trade Recording** - Logs every entry and exit with fill prices and timestamps

```python
from src.backtesting.simulator import TradingSimulator

simulator = TradingSimulator(
    initial_capital=10000,
    slippage=0.001,    # 0.1% slippage
    fee=0.001          # 0.1% trading fee
)

# Submit order (simulated fill)
order = simulator.submit_order(
    symbol="BTC/USDT",
    side="buy",
    quantity=0.1,
    price=42000
)
```

### Metrics

The `compute_metrics()` function calculates comprehensive performance statistics from trade history and equity curve:

| Metric | Description |
|--------|-------------|
| **Win Rate** | Percentage of profitable trades |
| **Profit Factor** | Gross profit / Gross loss |
| **Maximum Drawdown** | Largest peak-to-trough decline |
| **Sharpe Ratio** | Risk-adjusted return (annualized) |
| **Sortino Ratio** | Downside risk-adjusted return |
| **Calmar Ratio** | Return / Maximum drawdown |
| **Average Trade Duration** | Mean holding period |

```python
from src.backtesting.metrics import compute_metrics

metrics = compute_metrics(trades, equity_curve)
print(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
print(f"Max Drawdown: {metrics.max_drawdown:.2%}")
print(f"Win Rate: {metrics.win_rate:.2%}")
```

## BacktestResult

The `BacktestResult` dataclass contains all outputs from a completed backtest:

```python
@dataclass
class BacktestResult:
    # Performance metrics
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    avg_trade_duration: timedelta

    # Trade data
    trades: list[Trade]
    decisions: list[Decision]

    # Time series
    equity_curve: list[EquitySnapshot]
```

## Quick Start

### Basic Backtest

```python
from src.backtesting.engine import BacktestEngine
from src.decision.engine import DecisionEngine
from src.data.sources.ccxt import CCXTDataSource

# Initialize components
data_source = CCXTDataSource(exchange="binance")
decision_engine = DecisionEngine(config=config)

# Run backtest
engine = BacktestEngine(
    data_source=data_source,
    decision_engine=decision_engine,
    start_date="2024-01-01",
    end_date="2024-06-01",
    initial_capital=10000,
    slippage=0.001,
    fee=0.001
)

result = engine.run()

# Review results
print(f"Total Trades: {len(result.trades)}")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
print(f"Win Rate: {result.win_rate:.2%}")
print(f"Profit Factor: {result.profit_factor:.2f}")
```

### Parameter Sweep

```python
results = []

for slippage in [0.0005, 0.001, 0.002]:
    for fee in [0.0005, 0.001]:
        engine = BacktestEngine(
            data_source=data_source,
            decision_engine=decision_engine,
            start_date="2024-01-01",
            end_date="2024-06-01",
            initial_capital=10000,
            slippage=slippage,
            fee=fee
        )
        result = engine.run()
        results.append({
            "slippage": slippage,
            "fee": fee,
            "sharpe": result.sharpe_ratio,
            "max_dd": result.max_drawdown,
        })
```

## Best Practices

### Avoiding Look-Ahead Bias

- The `DataReplayEngine` enforces strict temporal ordering
- Indicators must only use data up to the current candle
- Never reference future prices in signal generation

### Realistic Assumptions

- **Slippage**: Use 0.05%–0.2% for liquid pairs, higher for illiquid
- **Fees**: Check exchange-specific maker/taker rates
- **Latency**: Backtests assume instant fills; live trading has execution delay

### Interpreting Metrics

| Metric | Good | Caution |
|--------|------|---------|
| Sharpe Ratio | > 1.5 | < 0.5 |
| Profit Factor | > 1.5 | < 1.0 |
| Max Drawdown | < 15% | > 30% |
| Win Rate | > 55% | < 40% |

### Validation Checklist

- [ ] Same `DecisionEngine` config as live trading
- [ ] Slippage and fees reflect exchange reality
- [ ] Backtest period includes multiple market regimes
- [ ] No look-ahead bias in indicators
- [ ] Sufficient sample size (>100 trades for statistical significance)

## Troubleshooting

**Backtest runs too slowly**
- Reduce lookback period
- Use cached historical data
- Filter to specific symbols

**Results differ from live trading**
- Verify `DecisionEngine` config is identical
- Check for data gaps in historical feed
- Confirm slippage/fee assumptions match exchange

**Too few trades generated**
- Extend backtest period
- Widen signal thresholds
- Add more symbols to universe
