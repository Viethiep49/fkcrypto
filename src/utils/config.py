"""Configuration loader — loads from YAML + .env with variable substitution."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Pattern for ${VAR_NAME} substitution
_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute_env(value: str) -> str:
    """Replace ${VAR_NAME} with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    return _ENV_PATTERN.sub(replacer, value)


def _substitute_env_in_obj(obj: Any) -> Any:
    """Recursively substitute env vars in config structure."""
    if isinstance(obj, str):
        return _substitute_env(obj)
    if isinstance(obj, dict):
        return {k: _substitute_env_in_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_env_in_obj(item) for item in obj]
    return obj


def load_config(config_path: str | Path | None = None, env_path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file with .env support.

    Args:
        config_path: Path to YAML config file. Defaults to config/default.yaml.
        env_path: Path to .env file. Defaults to .env in project root.

    Returns:
        Configuration dictionary with env vars substituted.
    """
    # Load .env file
    if env_path is None:
        env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    # Load YAML config
    if config_path is None:
        config_path = Path(__file__).resolve().parents[2] / "config" / "default.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    # Substitute environment variables
    config = _substitute_env_in_obj(config)

    return config


def get_required_env(key: str, default: str | None = None) -> str:
    """Get required environment variable or raise."""
    value = os.environ.get(key, default)
    if value is None:
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value
