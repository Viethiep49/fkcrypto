# FKCrypto Development Guide

Standards, workflows, and tooling for contributing to the FKCrypto codebase.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Package Management | `pyproject.toml` + `requirements.txt` |
| Testing | pytest, pytest-asyncio, pytest-cov |
| Linting | ruff |
| Type Checking | mypy (strict mode) |
| Pre-commit | pre-commit hooks |

## Project Structure

```
fkcrypto/
├── src/           # Main source code
├── tests/         # Test suite
├── config/        # YAML configuration
├── dashboard/     # Streamlit dashboard
├── docker/        # Docker setup
├── docs/          # Documentation
└── scripts/       # Utility scripts
```

## Getting Started

### Environment Setup

```bash
# Clone and install
git clone <repository-url>
cd fkcrypto
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Verify Setup

```bash
# Run full test suite
pytest

# Lint check
ruff check src/

# Type check
mypy src/
```

## Testing

### Framework Configuration

Tests use pytest with async support in auto mode:

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### Test Organization

```
tests/
├── test_risk/
│   └── test_risk_engine.py      # RiskEngine, position sizing, exposure
└── test_execution/
    └── test_order_validator.py  # OrderValidator
```

### Writing Tests

**Unit Test Pattern**

Use `MagicMock` for repository dependencies and factory helpers for quick setup:

```python
from unittest.mock import MagicMock
from src.risk.engine import RiskEngine

def make_risk_engine(**overrides) -> RiskEngine:
    """Factory helper for quick test setup."""
    config = {
        "max_position_size": 0.1,
        "max_exposure": 0.5,
        "stop_loss_pct": 0.02,
    }
    config.update(overrides)
    return RiskEngine(config=config)

class TestRiskEngine:
    def test_position_sizing_within_limits(self):
        engine = make_risk_engine()
        result = engine.calculate_position_size(
            capital=10000,
            signal_strength=0.8,
            stop_loss=0.02
        )
        assert result <= 1000  # 10% of capital

    def test_exposure_limit_enforced(self):
        engine = make_risk_engine(max_exposure=0.3)
        assert engine.max_exposure == 0.3
```

**Async Test Pattern**

```python
import pytest
from unittest.mock import AsyncMock

class TestOrderValidator:
    @pytest.mark.asyncio
    async def test_valid_order_passes(self):
        repo = AsyncMock()
        repo.get_position.return_value = None

        validator = OrderValidator(repository=repo)
        result = await validator.validate(order)

        assert result.is_valid is True
```

**Float Comparisons**

Use `pytest.approx()` for floating-point assertions:

```python
def test_sharpe_ratio_calculation(self):
    result = compute_metrics(trades, equity)
    assert result.sharpe_ratio == pytest.approx(1.42, rel=1e-2)
```

### Running Tests

```bash
# All tests
pytest

# With verbose output
pytest -v

# Specific test file
pytest tests/test_risk/test_risk_engine.py

# Specific test class
pytest tests/test_risk/test_risk_engine.py::TestRiskEngine

# Specific test method
pytest tests/test_risk/test_risk_engine.py::TestRiskEngine::test_position_sizing

# With coverage report
pytest --cov=src --cov-report=html

# Coverage in terminal
pytest --cov=src --cov-report=term-missing

# Async tests only
pytest -k "async"
```

## Code Quality

### Linting (ruff)

Configuration targets Python 3.11 with 100-character line length:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
```

```bash
# Check for issues
ruff check src/

# Auto-fix safe corrections
ruff check src/ --fix

# Check with unsafe fixes
ruff check src/ --fix --unsafe-fixes
```

### Type Checking (mypy)

Runs in strict mode for maximum type safety:

```toml
[tool.mypy]
strict = true
python_version = "3.11"
```

```bash
# Full type check
mypy src/

# Check specific module
mypy src/risk/engine.py

# Ignore missing imports for third-party libs
mypy src/ --ignore-missing-imports
```

### Pre-commit Hooks

Hooks run automatically on `git commit`:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: ruff
        name: ruff
        entry: ruff check
        language: system
        types: [python]

      - id: mypy
        name: mypy
        entry: mypy
        language: system
        types: [python]

      - id: pytest
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
```

```bash
# Run hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files
```

## Development Workflow

### Feature Development

```bash
# 1. Create feature branch
git checkout -b feature/my-new-feature

# 2. Make changes
# ... edit code ...

# 3. Run quality checks
ruff check src/ --fix
mypy src/
pytest --cov=src

# 4. Commit
git add .
git commit -m "feat: add position sizing calculator"

# 5. Push and create PR
git push -u origin feature/my-new-feature
```

### Bug Fix Workflow

```bash
# 1. Reproduce the bug with a test
pytest tests/test_bug_reproduction.py  # should fail

# 2. Fix the code
# ... edit code ...

# 3. Verify fix
pytest tests/test_bug_reproduction.py  # should pass

# 4. Run full suite
pytest

# 5. Commit with reference to issue
git commit -m "fix: correct position sizing overflow (#123)"
```

## Contributing Guidelines

### Code Style

- Follow existing patterns and conventions in the codebase
- Use type hints on all function signatures and class attributes
- Keep functions focused and under 50 lines where possible
- Prefer composition over inheritance
- Use dataclasses for data containers

### Testing Requirements

- Write tests for all new features and bug fixes
- Maintain or improve code coverage
- Use factory helpers for common test object creation
- Mock external dependencies (exchanges, databases, APIs)
- Test edge cases and error conditions

### Documentation

- Update relevant docs when changing behavior
- Add docstrings to public functions and classes
- Include usage examples for new features
- Keep BACKTESTING.md and this guide up to date

### Commit Messages

Follow conventional commits format:

```
type: short description

Longer explanation if needed.

type options:
  feat:     new feature
  fix:      bug fix
  docs:     documentation only
  style:    formatting, no code change
  refactor: code restructuring
  test:     adding or updating tests
  chore:    maintenance tasks
```

Examples:

```
feat: add Sharpe ratio to backtest metrics
fix: correct slippage calculation in simulator
test: add RiskEngine position sizing tests
refactor: extract order validation into separate module
docs: update backtesting guide with new metrics
```

### Pull Requests

- Include a clear description of changes
- Reference related issues
- Add screenshots for UI changes
- Ensure all CI checks pass
- Request review from at least one maintainer

## Common Tasks

### Adding a New Strategy

```python
# src/strategies/my_strategy.py
from src.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def generate_signal(self, candles: list[Candle]) -> Signal:
        # Implementation
        return Signal(direction="long", strength=0.7)
```

```python
# tests/test_strategies/test_my_strategy.py
class TestMyStrategy:
    def test_generates_long_signal(self):
        strategy = MyStrategy()
        signal = strategy.generate_signal(test_candles)
        assert signal.direction == "long"
```

### Adding a New Metric

```python
# src/backtesting/metrics.py
def compute_new_metric(trades: list[Trade]) -> float:
    """Calculate custom performance metric."""
    # Implementation
    return result
```

Update `BacktestResult` dataclass and `compute_metrics()` to include the new metric.

### Configuration Changes

All configuration lives in YAML files under `config/`:

```yaml
# config/strategy.yaml
strategy:
  name: "my_strategy"
  parameters:
    lookback: 100
    threshold: 0.5
```

Load configuration in code:

```python
from src.config.loader import load_config

config = load_config("config/strategy.yaml")
```

## Troubleshooting

**Import errors after adding new modules**
- Ensure `__init__.py` files exist in package directories
- Reinstall in editable mode: `pip install -e ".[dev]"`

**mypy errors on third-party libraries**
- Add `ignore_missing_imports = true` in `pyproject.toml`
- Or use `# type: ignore` on specific imports

**Tests pass locally but fail in CI**
- Check Python version matches CI environment
- Ensure all dependencies are in `requirements.txt`
- Verify no local state affects test results

**Slow test execution**
- Use `pytest -x` to stop on first failure
- Run specific test files instead of full suite
- Consider `pytest-xdist` for parallel execution
