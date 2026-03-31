"""Data replay engine for backtesting.

Steps through historical OHLCV candles one at a time (or in windows),
yielding data slices for agents to process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DataWindow:
    """A slice of historical data presented to agents at one replay step."""

    symbol: str
    timeframe: str
    candles: list[dict[str, Any]]
    current_candle: dict[str, Any]
    timestamp: datetime
    step_index: int
    total_steps: int


class DataReplayEngine:
    """Replays historical OHLCV data candle-by-candle for backtesting.

    Feeds sliding windows of candles to agents so they compute indicators
    on the same data they would see in live trading.
    """

    def __init__(
        self,
        candles: list[dict[str, Any]],
        symbol: str,
        timeframe: str,
        lookback: int = 250,
    ) -> None:
        self._candles = candles
        self._symbol = symbol
        self._timeframe = timeframe
        self._lookback = lookback
        self._step = 0

    @property
    def total_steps(self) -> int:
        return len(self._candles)

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def current_timestamp(self) -> Optional[datetime]:
        if self._step < len(self._candles):
            ts = self._candles[self._step].get("timestamp")
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            if isinstance(ts, datetime):
                return ts
        return None

    def reset(self) -> None:
        self._step = 0

    async def stream(self) -> AsyncIterator[DataWindow]:
        """Yield DataWindow objects one per candle.

        Each window contains up to `lookback` candles ending at the
        current step, so agents always have enough history for indicators.
        """
        min_warmup = self._lookback
        total = len(self._candles)

        if total < min_warmup:
            logger.warning(
                "insufficient_data_for_replay",
                symbol=self._symbol,
                available=total,
                required=min_warmup,
            )
            return

        for i in range(min_warmup - 1, total):
            self._step = i
            window_start = max(0, i - self._lookback + 1)
            window_candles = self._candles[window_start : i + 1]
            current = self._candles[i]

            ts_raw = current.get("timestamp")
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc)
            elif isinstance(ts_raw, datetime):
                ts = ts_raw
            else:
                ts = datetime.now(timezone.utc)

            yield DataWindow(
                symbol=self._symbol,
                timeframe=self._timeframe,
                candles=window_candles,
                current_candle=current,
                timestamp=ts,
                step_index=i,
                total_steps=total,
            )

        logger.info(
            "replay_complete",
            symbol=self._symbol,
            timeframe=self._timeframe,
            steps=total,
        )

    async def stream_batched(
        self,
        batch_size: int = 10,
    ) -> AsyncIterator[DataWindow]:
        """Yield DataWindow objects in batches for faster replay.

        Each step still advances by one candle, but agents receive
        the same interface. Useful when agent.run() is expensive.
        """
        async for window in self.stream():
            yield window
