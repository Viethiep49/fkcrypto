# AGENTS.md — FKCrypto Coding Agent Guidelines

This file provides instructions for agentic coding agents working in this repository.

## Project Overview

FKCrypto is a **Crypto Trading Agent System** — a hybrid multi-agent architecture combining deterministic technical analysis with LLM-assisted sentiment analysis, integrated with Freqtrade for order execution. Python 3.11+, uses LangGraph for orchestration.

## Build / Lint / Test Commands

### Setup
```bash
pip install -e ".[dev]"        # Install with dev dependencies
```

### Linting & Type Checking
```bash
ruff check src/ tests/          # Lint (E, F, I, N, W, UP rules)
ruff check src/ tests/ --fix    # Auto-fix
ruff format src/ tests/         # Format (if needed)
mypy src/                       # Strict type checking
```

### Testing
```bash
pytest                          # Run all tests
pytest tests/test_risk/         # Run a single test directory
pytest tests/test_risk/test_risk_engine.py              # Single test file
pytest tests/test_risk/test_risk_engine.py::TestRiskEngineValidation::test_valid_order_passes  # Single test
pytest -k "kill_switch"         # Run tests matching keyword
pytest --cov=src --cov-report=html  # Coverage report
```

### Run Application
```bash
python -m src.gateway           # Start the trading gateway
fkcrypto                        # Same (via entry point)
```

## Code Style Guidelines

### Imports
- Use `from __future__ import annotations` at the top of every file
- Group imports: stdlib → third-party → local (enforced by ruff rule `I`)
- Use absolute imports: `from src.agents.signal import Signal` (never relative)
- One import per line; sort alphabetically within groups

### Formatting
- **Line length:** 100 characters
- **Indentation:** 4 spaces
- **Trailing commas:** Use in multi-line structures
- **Quotes:** Double quotes for strings, single quotes acceptable in f-strings
- Let ruff handle formatting — run `ruff check --fix` before committing

### Types
- **mypy strict mode** is enforced — all code must pass `mypy src/`
- Annotate all function signatures: `def foo(x: int) -> str:`
- Use `typing` module: `Literal`, `Any`, `Optional`, `Union` from `typing`
- Use `dataclass` for data containers (see `Signal`, `Decision`, `ValidationResult`)
- Use `TypedDict` for structured dicts (see `AgentState` in graph.py)
- Return `None` explicitly for void functions: `def stop(self) -> None:`

### Naming Conventions
- **Classes:** PascalCase — `TechnicalAnalystAgent`, `RiskEngine`, `Signal`
- **Functions/Methods:** snake_case — `calculate_position_size()`, `safe_run()`
- **Constants:** UPPER_SNAKE_CASE — `VALID_ACTIONS`, `VALID_SOURCES`
- **Private methods:** Leading underscore — `_validate()`, `_check_exposure()`
- **Modules:** snake_case — `decision_engine.py`, `position_sizing.py`
- **Variables:** Descriptive snake_case — `total_balance`, `current_positions`

### Error Handling
- Use `structlog` for all logging — never `print()`
- Bind contextual info: `logger.bind(agent=name).info("event", key=value)`
- Agent `safe_run()` catches all exceptions — never let errors crash the system
- Raise `ValueError` for invalid input; use descriptive messages
- Use `pytest.approx()` for float comparisons in tests
- Use `MagicMock` for repository/external dependency mocking in tests

### Architecture Conventions
- **All agents** inherit from `BaseAgent` (src/agents/base.py)
- **All signals** use the `Signal` dataclass (src/agents/signal.py) — no custom signal types
- **Decision engine** is the sole decision-maker — agents emit signals, not decisions
- **Risk engine** validates every order independently — no bypassing
- **Data sources** implement the `DataSource` ABC (src/data/base.py)
- Use the **Repository pattern** for all database access (src/database/repository.py)
- Strategies are defined as **YAML files** in config/strategies/ — not hardcoded

### Test Conventions
- Class-based organization: `TestRiskEngineValidation`, `TestPositionSizing`
- Factory helpers for quick setup: `make_risk_engine(**overrides)`
- Test files mirror source structure: `src/risk/engine.py` → `tests/test_risk/test_risk_engine.py`
- Use `pytest-asyncio` in `auto` mode — async tests need no decorator
- Name tests descriptively: `test_valid_order_passes`, `test_kill_switch_rejects`

### Docstrings
- Use Google-style docstrings for public classes and methods
- Include Args, Returns, Raises sections where applicable
- Module-level docstring at top of every file

### Pre-commit Checklist
1. `ruff check src/ tests/` — no lint errors
2. `mypy src/` — no type errors
3. `pytest` — all tests pass
4. Update docs if behavior changed
