"""Risk Guardian Agent — real-time risk monitoring and kill switch."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from src.agents.base import BaseAgent
from src.agents.reasoning import Reasoning, ReasoningFactor
from src.agents.signal import Signal

logger = structlog.get_logger()


class RiskGuardianAgent(BaseAgent):
    """Real-time risk monitoring agent.

    Monitors:
    - Portfolio drawdown
    - Daily loss limits
    - Position limits and exposure
    - Market volatility (ATR spikes)
    - API health (exchange connectivity)

    Has authority to trigger the kill switch and halt all trading.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="risk_guardian", config=config)
        risk_config = config.get("risk_guardian", {})

        # Check interval
        self.check_interval_sec = risk_config.get("check_interval_sec", 30)

        # Risk limits
        limits = risk_config.get("limits", {})
        self.max_drawdown_pct = limits.get("max_drawdown_pct", 0.20)
        self.max_daily_loss_pct = limits.get("max_daily_loss_pct", 0.05)
        self.max_positions = limits.get("max_positions", 5)
        self.max_exposure_pct = limits.get("max_exposure_pct", 0.30)
        self.max_loss_per_position = limits.get("max_loss_per_position", 0.10)

        # Kill switch
        ks_cfg = risk_config.get("kill_switch", {})
        self.kill_switch_enabled = ks_cfg.get("enabled", True)
        self.auto_close_positions = ks_cfg.get("auto_close_positions", True)
        self.notification_channels = ks_cfg.get("notification_channels", [])
        self.manual_reset_required = ks_cfg.get("manual_reset_required", True)

        # Volatility
        vol_cfg = risk_config.get("volatility", {})
        self.atr_spike_multiplier = vol_cfg.get("atr_spike_multiplier", 3.0)

        # API health
        api_cfg = risk_config.get("api_health", {})
        self.max_consecutive_errors = api_cfg.get("max_consecutive_errors", 10)
        self.api_check_interval_sec = api_cfg.get("check_interval_sec", 60)

        # State
        self._kill_switch_active = False
        self._kill_switch_reason: str | None = None
        self._kill_switch_timestamp: datetime | None = None
        self._consecutive_api_errors = 0
        self._portfolio_peak_value: float = 0.0
        self._daily_start_balance: float = 0.0
        self._last_api_check: datetime | None = None

        # Data source
        self._data_source = config.get("data_source")

        # Monitoring loop task
        self._monitor_task: asyncio.Task | None = None

        # Symbols to monitor for volatility
        self.symbols = config.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    # ── Portfolio health checks ────────────────────────────────────────────

    def check_drawdown(
        self,
        current_value: float,
        peak_value: float,
    ) -> tuple[bool, float]:
        """Check if portfolio drawdown exceeds threshold.

        Returns:
            Tuple of (is_breached, drawdown_pct).
        """
        if peak_value <= 0:
            return False, 0.0

        drawdown = (peak_value - current_value) / peak_value
        is_breached = drawdown > self.max_drawdown_pct
        return is_breached, drawdown

    def check_daily_loss(
        self,
        current_value: float,
        starting_balance: float,
    ) -> tuple[bool, float]:
        """Check if daily loss exceeds threshold.

        Returns:
            Tuple of (is_breached, loss_pct).
        """
        if starting_balance <= 0:
            return False, 0.0

        pnl = current_value - starting_balance
        loss_pct = abs(min(pnl, 0)) / starting_balance
        is_breached = loss_pct > self.max_daily_loss_pct
        return is_breached, loss_pct

    # ── Position limit checks ──────────────────────────────────────────────

    def check_position_limits(
        self,
        positions: list[dict[str, Any]],
    ) -> list[str]:
        """Check position limits and return list of violations."""
        violations: list[str] = []

        if len(positions) > self.max_positions:
            violations.append(
                f"Too many positions: {len(positions)} > {self.max_positions}"
            )

        total_exposure = sum(abs(p.get("value_usd", 0)) for p in positions)
        portfolio_value = sum(p.get("value_usd", 0) for p in positions)
        if portfolio_value > 0:
            exposure_pct = total_exposure / portfolio_value
            if exposure_pct > self.max_exposure_pct:
                violations.append(
                    f"Exposure exceeded: {exposure_pct:.1%} > {self.max_exposure_pct:.1%}"
                )

        for p in positions:
            symbol = p.get("symbol", "UNKNOWN")
            unrealized_pnl_pct = p.get("unrealized_pnl_pct", 0.0)
            if unrealized_pnl_pct < -self.max_loss_per_position:
                violations.append(
                    f"{symbol} loss exceeds limit: {unrealized_pnl_pct:.1%} < -{self.max_loss_per_position:.1%}"
                )

        return violations

    # ── Market volatility check ────────────────────────────────────────────

    async def check_volatility(self, symbol: str) -> tuple[bool, float, float]:
        """Check if market volatility is extreme (ATR spike).

        Returns:
            Tuple of (is_extreme, current_atr, average_atr).
        """
        if self._data_source is None:
            return False, 0.0, 0.0

        try:
            candles = await self._data_source.get_ohlcv(
                symbol=symbol,
                timeframe="1h",
                limit=100,
            )

            if len(candles) < 30:
                return False, 0.0, 0.0

            # Compute ATR for recent candles
            atr_values = self._compute_atr_from_candles(candles, period=14)
            if len(atr_values) < 20:
                return False, 0.0, 0.0

            current_atr = atr_values[-1]
            average_atr = sum(atr_values[-20:-1]) / 19 if len(atr_values) >= 20 else atr_values[-1]

            if average_atr == 0:
                return False, current_atr, average_atr

            is_extreme = current_atr > average_atr * self.atr_spike_multiplier
            return is_extreme, current_atr, average_atr

        except Exception as exc:
            self._logger.error(
                "volatility_check_failed",
                symbol=symbol,
                error=str(exc),
            )
            return False, 0.0, 0.0

    def _compute_atr_from_candles(
        self,
        candles: list[dict[str, Any]],
        period: int,
    ) -> list[float]:
        """Compute ATR from OHLCV candle data."""
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]

        if len(highs) < period + 1:
            return []

        true_ranges: list[float] = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return []

        atr_values = [sum(true_ranges[:period]) / period]
        for i in range(period, len(true_ranges)):
            atr_values.append(
                (atr_values[-1] * (period - 1) + true_ranges[i]) / period
            )
        return atr_values

    # ── API health check ───────────────────────────────────────────────────

    async def check_api_health(self) -> dict[str, Any]:
        """Check connectivity to exchange and data sources.

        Returns:
            Dict with health status for each component.
        """
        results: dict[str, Any] = {
            "exchange": False,
            "data_source": False,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            if self._data_source:
                available = await self._data_source.is_available()
                results["data_source"] = available
                results["exchange"] = available

                if available:
                    self._consecutive_api_errors = 0
                else:
                    self._consecutive_api_errors += 1
            else:
                results["data_source"] = False
                self._consecutive_api_errors += 1

        except Exception as exc:
            self._logger.error("api_health_check_failed", error=str(exc))
            self._consecutive_api_errors += 1
            results["error"] = str(exc)

        self._last_api_check = datetime.now(UTC)
        return results

    # ── Kill switch ────────────────────────────────────────────────────────

    def _trigger_kill_switch(self, reason: str) -> Signal:
        """Activate the kill switch and emit emergency signal.

        Args:
            reason: Human-readable reason for triggering.

        Returns:
            Emergency Signal object.
        """
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self._kill_switch_timestamp = datetime.now(UTC)

        self._logger.critical(
            "kill_switch_triggered",
            reason=reason,
            timestamp=self._kill_switch_timestamp.isoformat(),
        )

        reasoning = Reasoning(
            agent="risk_guardian",
            confidence=1.0,
            summary=f"KILL SWITCH: {reason}. Dừng giao dịch ngay lập tức để bảo vệ vốn.",
            factors=[ReasoningFactor(
                type="risk",
                description=f"Kích hoạt kill switch: {reason}",
                impact=-1.0,
                metadata={"event": "kill_switch", "reason": reason},
            )],
        )

        return Signal(
            symbol="ALL",
            timeframe="1m",
            action="sell",
            confidence=1.0,
            strength=-1.0,
            source="risk",
            metadata={
                "event": "kill_switch",
                "reason": reason,
                "emergency": True,
                "auto_close": self.auto_close_positions,
                "manual_reset_required": self.manual_reset_required,
                "timestamp": self._kill_switch_timestamp.isoformat(),
            },
            reasoning=reasoning,
        )

    def reset_kill_switch(self) -> None:
        """Manually reset the kill switch.

        Requires manual intervention as per configuration.
        """
        if not self._kill_switch_active:
            return

        self._kill_switch_active = False
        self._kill_switch_reason = None
        self._kill_switch_timestamp = None
        self._consecutive_api_errors = 0

        self._logger.info("kill_switch_reset")

    # ── Risk signal emission ───────────────────────────────────────────────

    def _emit_risk_warning(
        self,
        symbol: str,
        event_type: str,
        current_value: float,
        threshold: float,
        severity: str = "warning",
    ) -> Signal:
        """Emit a non-emergency risk warning signal."""
        confidence = min(abs(current_value) / abs(threshold) if threshold != 0 else 0.5, 0.90)
        action = "sell" if current_value < 0 else "hold"

        severity_label = {"warning": "cảnh báo", "critical": "nguy hiểm"}.get(severity, severity)
        event_descriptions = {
            "drawdown_warning": f"Sụt giảm danh mục {abs(current_value):.2%} (ngưỡng {abs(threshold):.2%})",
            "daily_loss_warning": f"Lỗ hôm nay {abs(current_value):.2%} (ngưỡng {abs(threshold):.2%})",
            "api_health_warning": f"Lỗi API liên tiếp: {int(current_value)}/{int(threshold)}",
        }
        description = event_descriptions.get(event_type, f"Rủi ro: {event_type} ({current_value:.2%})")

        reasoning = Reasoning(
            agent="risk_guardian",
            confidence=confidence,
            summary=f"{severity_label.upper()}: {description}. Cần theo dõi sát.",
            factors=[ReasoningFactor(
                type="risk",
                description=description,
                impact=-confidence * 0.3,
                metadata={
                    "event": event_type,
                    "severity": severity,
                    "current_value": round(current_value, 6),
                    "threshold": round(threshold, 6),
                },
            )],
        )

        return Signal(
            symbol=symbol,
            timeframe="1h",
            action=action,
            confidence=round(confidence, 4),
            strength=round(max(-1.0, min(0.0, current_value)), 4),
            source="risk",
            metadata={
                "event": "risk_warning",
                "type": event_type,
                "current_value": round(current_value, 6),
                "threshold": round(threshold, 6),
                "severity": severity,
            },
            reasoning=reasoning,
        )

    # ── Main monitoring cycle ──────────────────────────────────────────────

    async def _run_checks(
        self,
        portfolio_value: float | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> list[Signal]:
        """Run all risk checks and return signals."""
        signals: list[Signal] = []

        # If kill switch is already active, skip checks
        if self._kill_switch_active:
            self._logger.warning("kill_switch_active_skipping_checks")
            return signals

        # Portfolio drawdown check
        if portfolio_value is not None and self._portfolio_peak_value > 0:
            drawdown_breached, drawdown_pct = self.check_drawdown(
                portfolio_value, self._portfolio_peak_value
            )
            if drawdown_breached:
                signals.append(
                    self._trigger_kill_switch(
                        f"drawdown_exceeded: {drawdown_pct:.2%} > {self.max_drawdown_pct:.2%}"
                    )
                )
                return signals
            elif drawdown_pct > self.max_drawdown_pct * 0.75:
                # Warning zone (75% of threshold)
                signals.append(
                    self._emit_risk_warning(
                        symbol="PORTFOLIO",
                        event_type="drawdown_warning",
                        current_value=drawdown_pct,
                        threshold=self.max_drawdown_pct,
                        severity="warning",
                    )
                )

            # Update peak
            if portfolio_value > self._portfolio_peak_value:
                self._portfolio_peak_value = portfolio_value

        # Daily loss check
        if portfolio_value is not None and self._daily_start_balance > 0:
            daily_breached, daily_loss_pct = self.check_daily_loss(
                portfolio_value, self._daily_start_balance
            )
            if daily_breached:
                signals.append(
                    self._trigger_kill_switch(
                        f"daily_loss_exceeded: {daily_loss_pct:.2%} > {self.max_daily_loss_pct:.2%}"
                    )
                )
                return signals
            elif daily_loss_pct > self.max_daily_loss_pct * 0.75:
                signals.append(
                    self._emit_risk_warning(
                        symbol="PORTFOLIO",
                        event_type="daily_loss_warning",
                        current_value=-daily_loss_pct,
                        threshold=-self.max_daily_loss_pct,
                        severity="warning",
                    )
                )

        # Position limits check
        if positions is not None:
            violations = self.check_position_limits(positions)
            if violations:
                for violation in violations:
                    self._logger.warning("position_limit_violation", violation=violation)
                    reasoning = Reasoning(
                        agent="risk_guardian",
                        confidence=0.8,
                        summary=f"Vi phạm giới hạn vị thế: {violation}",
                        factors=[ReasoningFactor(
                            type="risk",
                            description=violation,
                            impact=-0.3,
                            metadata={"violation": violation},
                        )],
                    )
                    signals.append(
                        Signal(
                            symbol="PORTFOLIO",
                            timeframe="1h",
                            action="sell",
                            confidence=0.8,
                            strength=-0.5,
                            source="risk",
                            metadata={
                                "event": "position_limit_violation",
                                "violation": violation,
                            },
                            reasoning=reasoning,
                        )
                    )

                # Check if violations warrant kill switch
                if len(violations) >= 3:
                    signals.append(
                        self._trigger_kill_switch(
                            f"multiple_position_violations: {len(violations)}"
                        )
                    )
                    return signals

        # Market volatility check
        for symbol in self.symbols:
            try:
                is_extreme, current_atr, average_atr = await self.check_volatility(symbol)
                if is_extreme:
                    spike_ratio = current_atr / average_atr if average_atr > 0 else 0
                    self._logger.warning(
                        "atr_spike_detected",
                        symbol=symbol,
                        current_atr=current_atr,
                        average_atr=average_atr,
                        ratio=spike_ratio,
                    )
                    signals.append(
                        Signal(
                            symbol=symbol,
                            timeframe="1h",
                            action="sell",
                            confidence=min(spike_ratio / (self.atr_spike_multiplier * 2), 0.90),
                            strength=-0.5,
                            source="risk",
                            metadata={
                                "event": "volatility_spike",
                                "current_atr": round(current_atr, 4),
                                "average_atr": round(average_atr, 4),
                                "ratio": round(spike_ratio, 2),
                            },
                            reasoning=Reasoning(
                                agent="risk_guardian",
                                confidence=min(spike_ratio / (self.atr_spike_multiplier * 2), 0.90),
                                summary=f"Biến động mạnh bất thường: ATR {spike_ratio:.1f}x trung bình tại {symbol}",
                                factors=[ReasoningFactor(
                                    type="risk",
                                    description=f"ATR spike {spike_ratio:.1f}x ({current_atr:.2f} vs {average_atr:.2f})",
                                    impact=-0.25,
                                    metadata={"current_atr": round(current_atr, 4), "average_atr": round(average_atr, 4), "ratio": round(spike_ratio, 2)},
                                )],
                            ),
                        )
                    )

                    # Kill switch on extreme volatility
                    if spike_ratio > self.atr_spike_multiplier * 2:
                        signals.append(
                            self._trigger_kill_switch(
                                f"extreme_volatility: {symbol} ATR {spike_ratio:.1f}x average"
                            )
                        )
                        return signals
            except Exception as exc:
                self._logger.error(
                    "volatility_check_error",
                    symbol=symbol,
                    error=str(exc),
                )

        # API health check
        api_health = await self.check_api_health()
        if not api_health.get("data_source", False):
            self._logger.warning(
                "api_health_degraded",
                consecutive_errors=self._consecutive_api_errors,
            )
            if self._consecutive_api_errors >= self.max_consecutive_errors:
                signals.append(
                    self._trigger_kill_switch(
                        f"api_health_critical: {self._consecutive_api_errors} consecutive errors"
                    )
                )
                return signals
            elif self._consecutive_api_errors >= self.max_consecutive_errors * 0.5:
                signals.append(
                    self._emit_risk_warning(
                        symbol="SYSTEM",
                        event_type="api_health_warning",
                        current_value=float(self._consecutive_api_errors),
                        threshold=float(self.max_consecutive_errors),
                        severity="warning",
                    )
                )

        return signals

    async def run(
        self,
        portfolio_value: float | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> list[Signal]:
        """Execute one risk monitoring cycle.

        Args:
            portfolio_value: Current portfolio value in USD.
            positions: List of current position dicts.

        Returns:
            List of risk Signal objects.
        """
        signals = await self._run_checks(portfolio_value, positions)

        self._logger.info(
            "risk_cycle_complete",
            signals=len(signals),
            kill_switch_active=self._kill_switch_active,
            api_errors=self._consecutive_api_errors,
        )
        return signals

    async def start_monitoring(
        self,
        portfolio_value: float | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Start continuous risk monitoring loop."""
        if self._monitor_task and not self._monitor_task.done():
            self._logger.warning("monitoring_already_running")
            return

        # Initialize tracking values
        if portfolio_value is not None:
            self._portfolio_peak_value = max(
                self._portfolio_peak_value, portfolio_value
            )
            self._daily_start_balance = portfolio_value

        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(portfolio_value, positions)
        )
        self._logger.info(
            "risk_monitoring_started",
            interval_sec=self.check_interval_sec,
        )

    async def _monitor_loop(
        self,
        portfolio_value: float | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Continuous monitoring loop running every 30 seconds."""
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
        """Stop the risk guardian agent."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await super().stop()

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def is_kill_switch_active(self) -> bool:
        """Check if the kill switch is currently active."""
        return self._kill_switch_active

    @property
    def kill_switch_reason(self) -> str | None:
        """Get the reason for the kill switch activation."""
        return self._kill_switch_reason

    def set_portfolio_value(self, value: float) -> None:
        """Update portfolio tracking values."""
        if value > self._portfolio_peak_value:
            self._portfolio_peak_value = value
        if self._daily_start_balance == 0:
            self._daily_start_balance = value

    def reset_daily_tracking(self, new_balance: float) -> None:
        """Reset daily loss tracking (e.g., at start of new trading day)."""
        self._daily_start_balance = new_balance
        self._logger.info("daily_tracking_reset", balance=new_balance)
