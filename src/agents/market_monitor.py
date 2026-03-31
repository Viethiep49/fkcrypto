"""Market Monitor Agent — real-time price, volume, and order book monitoring."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from src.agents.base import BaseAgent
from src.agents.signal import Signal

logger = structlog.get_logger()


class MarketMonitorAgent(BaseAgent):
    """Real-time market monitoring agent.

    Detects:
    - Price spikes (>threshold% in window)
    - Volume anomalies (>N std dev above mean)
    - Order book imbalance (bid/ask ratio)
    - Flash crashes (rapid price drops)

    Emits momentum signals when anomalies are detected.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="market_monitor", config=config)
        monitor_config = config.get("market_monitor", {})

        # Check interval
        self.check_interval_sec = monitor_config.get("check_interval_sec", 5)

        # Price spike detection
        price_spike = monitor_config.get("price_spike", {})
        self.price_spike_threshold_pct = price_spike.get("threshold_pct", 2.0)
        self.price_spike_window_sec = price_spike.get("window_sec", 300)

        # Volume anomaly detection
        volume_anomaly = monitor_config.get("volume_anomaly", {})
        self.volume_std_multiplier = volume_anomaly.get("std_multiplier", 3.0)
        self.volume_lookback_periods = volume_anomaly.get("lookback_periods", 20)

        # Order book monitoring
        order_book = monitor_config.get("order_book", {})
        self.ob_depth = order_book.get("depth", 20)
        self.ob_imbalance_ratio = order_book.get("imbalance_ratio", 3.0)
        self.ob_wall_threshold_btc = order_book.get("wall_threshold_btc", 100)

        # Symbols to monitor
        self.symbols = config.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

        # Rolling price history per symbol: {symbol: deque[(timestamp, price)]}
        self._price_history: dict[str, deque] = {}
        # Rolling volume history per symbol: {symbol: deque[volume]}
        self._volume_history: dict[str, deque] = {}
        # Last known price per symbol
        self._last_prices: dict[str, float] = {}

        # CCXT source (injected or created)
        self._data_source = config.get("data_source")

        # Monitoring loop task
        self._monitor_task: asyncio.Task | None = None

    def _init_history(self, symbol: str) -> None:
        """Initialize rolling history buffers for a symbol."""
        if symbol not in self._price_history:
            window_size = max(self.price_spike_window_sec // self.check_interval_sec, 60)
            self._price_history[symbol] = deque(maxlen=window_size)
        if symbol not in self._volume_history:
            self._volume_history[symbol] = deque(maxlen=self.volume_lookback_periods)

    def _detect_price_spike(self, symbol: str, current_price: float) -> Signal | None:
        """Detect if price has spiked beyond threshold within the window."""
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return None

        now_ts = datetime.now(timezone.utc).timestamp()
        window_start = now_ts - self.price_spike_window_sec

        # Find oldest price within window
        window_prices = [(ts, price) for ts, price in history if ts >= window_start]
        if not window_prices:
            return None

        oldest_price = window_prices[0][1]
        if oldest_price == 0:
            return None

        change_pct = ((current_price - oldest_price) / oldest_price) * 100.0

        if abs(change_pct) >= self.price_spike_threshold_pct:
            action = "buy" if change_pct > 0 else "sell"
            confidence = min(abs(change_pct) / (self.price_spike_threshold_pct * 2), 0.95)
            strength = max(-1.0, min(1.0, change_pct / 100.0))

            return Signal(
                symbol=symbol,
                timeframe="1m",
                action=action,
                confidence=round(confidence, 4),
                strength=round(strength, 4),
                source="momentum",
                metadata={
                    "event": "price_spike",
                    "change_pct": round(change_pct, 4),
                    "window_sec": self.price_spike_window_sec,
                    "oldest_price": oldest_price,
                    "current_price": current_price,
                },
            )
        return None

    def _detect_volume_anomaly(self, symbol: str, current_volume: float) -> Signal | None:
        """Detect volume anomalies using standard deviation method."""
        history = self._volume_history.get(symbol)
        if not history or len(history) < 5:
            return None

        volumes = list(history)
        mean_vol = sum(volumes) / len(volumes)
        variance = sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)
        std_vol = variance ** 0.5

        if std_vol == 0:
            return None

        threshold = mean_vol + self.volume_std_multiplier * std_vol

        if current_volume > threshold:
            # Determine price direction to set action
            price_hist = self._price_history.get(symbol)
            direction = "buy"
            if price_hist and len(price_hist) >= 2:
                recent_prices = [p for _, p in list(price_hist)[-5:]]
                if len(recent_prices) >= 2 and recent_prices[-1] < recent_prices[0]:
                    direction = "sell"

            deviation = (current_volume - mean_vol) / std_vol
            confidence = min(deviation / (self.volume_std_multiplier * 2), 0.90)

            return Signal(
                symbol=symbol,
                timeframe="1m",
                action=direction,
                confidence=round(confidence, 4),
                strength=round(max(-1.0, min(1.0, deviation / 10.0)), 4),
                source="momentum",
                metadata={
                    "event": "volume_anomaly",
                    "current_volume": current_volume,
                    "mean_volume": round(mean_vol, 4),
                    "std_volume": round(std_vol, 4),
                    "deviation_sigma": round(deviation, 2),
                    "threshold": round(threshold, 4),
                },
            )
        return None

    def _detect_order_book_imbalance(self, orderbook: dict[str, Any]) -> Signal | None:
        """Detect order book imbalance from bid/ask depth ratio."""
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        if not bids or not asks:
            return None

        # Calculate total depth (price * quantity) for top levels
        bid_depth = sum(price * qty for price, qty in bids[:self.ob_depth])
        ask_depth = sum(price * qty for price, qty in asks[:self.ob_depth])

        if ask_depth == 0:
            return None

        ratio = bid_depth / ask_depth
        symbol = orderbook.get("symbol", "UNKNOWN")

        if ratio >= self.ob_imbalance_ratio:
            confidence = min((ratio - 1) / (self.ob_imbalance_ratio * 2), 0.85)
            return Signal(
                symbol=symbol,
                timeframe="1m",
                action="buy",
                confidence=round(confidence, 4),
                strength=round(min(1.0, (ratio - 1) / 2), 4),
                source="momentum",
                metadata={
                    "event": "order_book_imbalance",
                    "bid_depth": round(bid_depth, 4),
                    "ask_depth": round(ask_depth, 4),
                    "ratio": round(ratio, 4),
                    "type": "bid_dominant",
                },
            )
        elif ratio <= 1.0 / self.ob_imbalance_ratio:
            confidence = min((1 / ratio - 1) / (self.ob_imbalance_ratio * 2), 0.85)
            return Signal(
                symbol=symbol,
                timeframe="1m",
                action="sell",
                confidence=round(confidence, 4),
                strength=round(max(-1.0, -(1 / ratio - 1) / 2), 4),
                source="momentum",
                metadata={
                    "event": "order_book_imbalance",
                    "bid_depth": round(bid_depth, 4),
                    "ask_depth": round(ask_depth, 4),
                    "ratio": round(ratio, 4),
                    "type": "ask_dominant",
                },
            )
        return None

    def _detect_flash_crash(self, symbol: str, current_price: float) -> Signal | None:
        """Detect flash crash — price drop >5% in <1 minute."""
        history = self._price_history.get(symbol)
        if not history or len(history) < 2:
            return None

        now_ts = datetime.now(timezone.utc).timestamp()
        one_min_ago = now_ts - 60

        recent_prices = [(ts, price) for ts, price in history if ts >= one_min_ago]
        if not recent_prices:
            return None

        oldest_in_minute = recent_prices[0][1]
        if oldest_in_minute == 0:
            return None

        drop_pct = ((current_price - oldest_in_minute) / oldest_in_minute) * 100.0

        if drop_pct <= -5.0:
            return Signal(
                symbol=symbol,
                timeframe="1m",
                action="sell",
                confidence=0.95,
                strength=-1.0,
                source="momentum",
                metadata={
                    "event": "flash_crash",
                    "drop_pct": round(drop_pct, 4),
                    "window_sec": 60,
                    "price_before": oldest_in_minute,
                    "price_after": current_price,
                    "emergency": True,
                },
            )
        return None

    async def _check_symbol(self, symbol: str) -> list[Signal]:
        """Run all detection checks for a single symbol."""
        signals: list[Signal] = []

        try:
            if self._data_source is None:
                self._logger.warning("no_data_source_configured", symbol=symbol)
                return signals

            # Fetch current ticker data
            ticker = await self._data_source.get_ticker(symbol)
            current_price = ticker.get("last")
            current_volume = ticker.get("volume", 0)

            if current_price is None:
                return signals

            now_ts = datetime.now(timezone.utc).timestamp()

            # Update rolling histories
            self._init_history(symbol)
            self._price_history[symbol].append((now_ts, current_price))
            self._volume_history[symbol].append(current_volume)
            self._last_prices[symbol] = current_price

            # Run all detectors
            spike_signal = self._detect_price_spike(symbol, current_price)
            if spike_signal:
                signals.append(spike_signal)
                self._logger.info(
                    "price_spike_detected",
                    symbol=symbol,
                    change_pct=spike_signal.metadata.get("change_pct"),
                )

            volume_signal = self._detect_volume_anomaly(symbol, current_volume)
            if volume_signal:
                signals.append(volume_signal)
                self._logger.info(
                    "volume_anomaly_detected",
                    symbol=symbol,
                    deviation=volume_signal.metadata.get("deviation_sigma"),
                )

            flash_signal = self._detect_flash_crash(symbol, current_price)
            if flash_signal:
                signals.append(flash_signal)
                self._logger.warning(
                    "flash_crash_detected",
                    symbol=symbol,
                    drop_pct=flash_signal.metadata.get("drop_pct"),
                )

            # Order book check
            try:
                orderbook = await self._data_source.get_orderbook(symbol, limit=self.ob_depth)
                ob_signal = self._detect_order_book_imbalance(orderbook)
                if ob_signal:
                    signals.append(ob_signal)
                    self._logger.info(
                        "order_book_imbalance_detected",
                        symbol=symbol,
                        ratio=ob_signal.metadata.get("ratio"),
                    )
            except Exception as exc:
                self._logger.debug("orderbook_check_failed", symbol=symbol, error=str(exc))

        except Exception as exc:
            self._logger.error(
                "symbol_check_failed",
                symbol=symbol,
                error=str(exc),
            )

        return signals

    async def run(self) -> list[Signal]:
        """Execute one monitoring cycle across all symbols.

        Returns:
            List of Signal objects from detected anomalies.
        """
        all_signals: list[Signal] = []

        for symbol in self.symbols:
            signals = await self._check_symbol(symbol)
            all_signals.extend(signals)

        self._logger.info(
            "monitor_cycle_complete",
            symbols_checked=len(self.symbols),
            signals_emitted=len(all_signals),
        )
        return all_signals

    async def start_monitoring(self) -> None:
        """Start continuous monitoring loop."""
        if self._monitor_task and not self._monitor_task.done():
            self._logger.warning("monitoring_already_running")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._logger.info(
            "monitoring_started",
            interval_sec=self.check_interval_sec,
            symbols=self.symbols,
        )

    async def _monitor_loop(self) -> None:
        """Continuous monitoring loop with configurable interval."""
        while self._running:
            try:
                await self.safe_run()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.error("monitor_loop_error", error=str(exc))

            try:
                await asyncio.sleep(self.check_interval_sec)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        """Stop the monitoring agent."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await super().stop()
