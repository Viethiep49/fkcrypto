# Strategy Configuration

Each trading strategy is defined in its own YAML file under this directory.
The system loads all `*.yaml` files here at startup.

## File Naming

Name files descriptively: `momentum_scalp.yaml`, `mean_reversion.yaml`, etc.

## Required Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique strategy identifier |
| `enabled` | bool | Whether the strategy is active |
| `type` | string | Strategy category (e.g. `momentum`, `mean_reversion`, `breakout`) |
| `timeframes` | list | Timeframes the strategy operates on |
| `pairs` | list | Trading pairs to monitor |
| `parameters` | map | Strategy-specific parameters |
| `signals` | map | Signal thresholds for buy/sell/hold |
| `risk` | map | Risk overrides (falls back to global `risk` if omitted) |

## Template

```yaml
# Strategy: <name>
# Description: <brief description>

name: example_strategy
enabled: false
type: momentum
timeframes:
  - 15m
  - 1h
pairs:
  - BTC/USDT
  - ETH/USDT

parameters:
  rsi_period: 14
  rsi_overbought: 70
  rsi_oversold: 30
  ema_fast: 9
  ema_slow: 21
  volume_threshold: 1.5

signals:
  buy_threshold: 0.65
  sell_threshold: -0.65
  min_confidence: 0.5

risk:
  max_position_size: 0.1
  stop_loss: 0.03
  take_profit: 0.06
```

## Notes

- Secrets should use `${ENV_VAR}` placeholders — never hardcode values.
- Risk settings here override the global `risk` config in `default.yaml`.
- A strategy must have `enabled: true` to be loaded by the system.
