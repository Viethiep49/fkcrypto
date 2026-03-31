"""Prometheus metrics HTTP server for FKCrypto trading system."""

from __future__ import annotations

from typing import Any

import structlog
from prometheus_client import start_http_server

logger = structlog.get_logger(__name__)


def start_metrics_server(port: int = 9090, addr: str = "0.0.0.0") -> Any:
    """Start an HTTP server exposing Prometheus metrics.

    Args:
        port: Port to listen on. Defaults to 9090.
        addr: Address to bind to. Defaults to 0.0.0.0.

    Returns:
        The HTTP server handle for shutdown.
    """
    logger.info("starting_metrics_server", port=port, addr=addr)
    server = start_http_server(port=port, addr=addr)
    logger.info("metrics_server_started", port=port)
    return server
