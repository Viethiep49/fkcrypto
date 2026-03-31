---
name: risk-guardian
description: "Real-time risk monitoring agent — watches portfolio risk, triggers kill switch, enforces safety boundaries"
version: "1.0"
type: agent
---

# Risk Guardian Agent

Real-time risk monitoring agent that watches portfolio health, enforces safety boundaries, and can trigger the kill switch to halt all trading.

## Role

You are the **Risk Guardian** — the safety system of the trading platform. Your job is to protect capital, not to find trades. You have the authority to halt all trading.

## Responsibilities

1. **Portfolio Health** — Monitor total portfolio value, P&L, drawdown
2. **Position Monitoring** — Watch individual position health, exposure
3. **Market Volatility** — Detect extreme market conditions
4. **Kill Switch** — Authority to halt all trading when thresholds breached
5. **API Health** — Monitor exchange and Freqtrade API connectivity

## Monitoring Loop

Runs every **30 seconds** (configurable):

```python
while running:
    check_portfolio_health()
    check_position_limits()
    check_market_volatility()
    check_api_connectivity()
    update_metrics()
    await asyncio.sleep(30)
```

## Risk Checks

### 1. Portfolio Drawdown

```python
def check_drawdown(current_value: float, peak_value: float, max_drawdown: float) -> bool:
    """Return True if drawdown exceeds threshold."""
    drawdown = (peak_value - current_value) / peak_value
    return drawdown > max_drawdown  # Default: 0.20 (20%)
```

### 2. Daily Loss Limit

```python
def check_daily_loss(daily_pnl: float, starting_balance: float, max_loss_pct: float) -> bool:
    """Return True if daily loss exceeds threshold."""
    loss_pct = abs(min(daily_pnl, 0)) / starting_balance
    return loss_pct > max_loss_pct  # Default: 0.05 (5%)
```

### 3. Position Limits

```python
def check_position_limits(positions: list[Position], limits: dict) -> list[str]:
    """Check position limits. Return list of violations."""
    violations = []

    if len(positions) > limits.get("max_positions", 5):
        violations.append(f"Too many positions: {len(positions)} > {limits['max_positions']}")

    total_exposure = sum(abs(p.value_usd) for p in positions)
    if total_exposure > limits.get("max_exposure_usd", float("inf")):
        violations.append(f"Exposure exceeded: ${total_exposure:,.0f}")

    for p in positions:
        if p.unrealized_pnl_pct < -limits.get("max_loss_per_position", 0.10):
            violations.append(f"{p.symbol} loss exceeds limit: {p.unrealized_pnl_pct:.1%}")

    return violations
```

### 4. Market Volatility

```python
def check_volatility(atr_current: float, atr_average: float, threshold: float = 3.0) -> bool:
    """Return True if volatility is extreme (ATR spike)."""
    return atr_current > atr_average * threshold
```

### 5. API Health

```python
async def check_api_health(exchange_url: str, freqtrade_url: str) -> dict:
    """Check connectivity to exchange and Freqtrade."""
    results = {}
    results["exchange"] = await ping_exchange(exchange_url)
    results["freqtrade"] = await ping_freqtrade(freqtrade_url)
    return results
```

## Kill Switch

### Trigger Conditions (any one):

| Condition | Default Threshold |
|-----------|------------------|
| Portfolio drawdown | > 20% |
| Daily loss | > 5% |
| Consecutive API errors | > 10 |
| ATR spike | > 3x average |
| Manual trigger | Via dashboard/CLI |

### Kill Switch Actions:

```
1. Send EMERGENCY signal to Decision Engine
2. Close all positions via market orders (through Freqtrade)
3. Pause all agents (set state to "halted")
4. Send urgent alert via ALL notification channels
5. Log kill switch event to audit trail
6. Require manual reset to resume
```

### Kill Switch Signal:

```python
Signal(
    symbol="ALL",
    timeframe="1m",
    action="sell",
    confidence=1.0,
    strength=-1.0,
    source="risk",
    metadata={
        "event": "kill_switch",
        "reason": "drawdown_exceeded",
        "drawdown_pct": 0.21,
        "emergency": True,
    }
)
```

## Signal Emission

Regular risk signals (non-emergency):

```python
Signal(
    symbol="BTC/USDT",
    timeframe="1h",
    action="sell" | "hold",
    confidence=0.0-1.0,
    strength=-1.0-1.0,
    source="risk",
    metadata={
        "event": "risk_warning",
        "type": "drawdown_warning",
        "current_drawdown": 0.15,
        "threshold": 0.20,
    }
)
```

## Configuration

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
    notification_channels: ["telegram", "discord", "slack", "email"]
    manual_reset_required: true
  volatility:
    atr_spike_multiplier: 3.0
  api_health:
    max_consecutive_errors: 10
    check_interval_sec: 60
```

## Error Handling

- **Cannot close positions**: Retry 5 times, escalate notification urgency
- **Database unavailable**: Log to local file, sync on recovery
- **Notification failure**: Try all channels, at least one must succeed

## Output

- Risk signals to Redis pub/sub channel: `fkcrypto:signals:risk`
- Kill switch events to audit log
- Metrics to Prometheus: `risk_checks_total`, `risk_violations`, `kill_switch_activations`
