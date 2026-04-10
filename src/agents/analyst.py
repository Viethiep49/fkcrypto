"""Technical Analyst Agent — computes indicators and generates deterministic trading signals."""

from __future__ import annotations

import math
import pandas as pd
import ta
import numpy as np
from pathlib import Path
from typing import Any

import structlog
import yaml

from src.agents.base import BaseAgent
from src.agents.reasoning import Reasoning, ReasoningFactor
from src.agents.signal import Signal

logger = structlog.get_logger()


class _IndicatorState:
    """Holds computed indicator values for a symbol/timeframe."""

    def __init__(self) -> None:
        self.rsi: float | None = None
        self.macd_line: float | None = None
        self.macd_signal: float | None = None
        self.macd_histogram: float | None = None
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.ema_200: float | None = None
        self.bb_upper: float | None = None
        self.bb_middle: float | None = None
        self.bb_lower: float | None = None
        self.atr: float | None = None
        self.volume_sma: float | None = None
        self.stoch_k: float | None = None
        self.stoch_d: float | None = None
        self.adx: float | None = None
        self.donchian_upper: float | None = None
        self.donchian_middle: float | None = None
        self.donchian_lower: float | None = None
        self.current_price: float | None = None
        self.current_volume: float | None = None


class TechnicalAnalystAgent(BaseAgent):
    """Scheduled technical analysis agent.

    Loads strategies from config/strategies/*.yaml, computes indicators,
    evaluates entry/exit conditions, and emits signals.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(name="technical_analyst", config=config)
        analyst_config = config.get("analyst", {})

        self.timeframes = analyst_config.get("timeframes", ["15m", "1h", "4h"])
        self.symbols = config.get("pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

        # Indicator parameters
        indicator_cfg = analyst_config.get("indicators", {})
        rsi_cfg = indicator_cfg.get("rsi", {})
        self.rsi_period = rsi_cfg.get("period", 14)

        ema_cfg = indicator_cfg.get("ema", {})
        self.ema_fast = ema_cfg.get("fast", 20)
        self.ema_slow = ema_cfg.get("slow", 50)

        macd_cfg = indicator_cfg.get("macd", {})
        self.macd_fast = macd_cfg.get("fast", 12)
        self.macd_slow = macd_cfg.get("slow", 26)
        self.macd_signal_period = macd_cfg.get("signal", 9)

        bb_cfg = indicator_cfg.get("bollinger", {})
        self.bb_period = bb_cfg.get("period", 20)
        self.bb_std = bb_cfg.get("std", 2.0)

        atr_cfg = indicator_cfg.get("atr", {})
        self.atr_period = atr_cfg.get("period", 14)

        self.volume_sma_period = indicator_cfg.get("volume_sma", {}).get("period", 20)
        self.stoch_k_period = indicator_cfg.get("stochastic", {}).get("k", 14)
        self.stoch_d_period = indicator_cfg.get("stochastic", {}).get("d", 3)
        self.adx_period = indicator_cfg.get("adx", {}).get("period", 14)
        self.donchian_period = indicator_cfg.get("donchian", {}).get("period", 20)

        # Multi-timeframe confirmation
        mtf_cfg = analyst_config.get("multi_timeframe", {})
        self.mtf_enabled = mtf_cfg.get("enabled", True)
        self.mtf_boost = mtf_cfg.get("confirmation_boost", 0.15)

        # Strategy directory
        self.strategy_dir = config.get("strategy_dir", "config/strategies")
        self._strategies: list[dict[str, Any]] = []
        self._load_strategies()

        # Data source
        self._data_source = config.get("data_source")

    def _load_strategies(self) -> None:
        """Load all enabled strategy YAML files from the strategy directory."""
        strategy_path = Path(self.strategy_dir)
        if not strategy_path.exists():
            self._logger.warning("strategy_directory_not_found", path=str(strategy_path))
            return

        loaded = 0
        for yaml_file in sorted(strategy_path.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    strategy = yaml.safe_load(f)

                if not isinstance(strategy, dict):
                    self._logger.warning("invalid_strategy_file", file=str(yaml_file))
                    continue

                if not strategy.get("enabled", False):
                    self._logger.debug("strategy_disabled", name=strategy.get("name", yaml_file.stem))
                    continue

                # Validate required fields
                required = ["name", "entry", "exit"]
                missing = [field for field in required if field not in strategy]
                if missing:
                    self._logger.warning(
                        "strategy_missing_fields",
                        file=str(yaml_file),
                        missing=missing,
                    )
                    continue

                self._strategies.append(strategy)
                loaded += 1
                self._logger.info("strategy_loaded", name=strategy["name"], file=yaml_file.name)

            except Exception as exc:
                self._logger.error(
                    "strategy_load_failed",
                    file=str(yaml_file),
                    error=str(exc),
                )

        self._logger.info("strategies_loaded", count=loaded)

    # ── Indicator computation ──────────────────────────────────────────────

    def _compute_indicators(self, candles: list[dict[str, Any]]) -> _IndicatorState:
        """Compute all indicators from OHLCV candle data using pandas and ta."""
        state = _IndicatorState()

        if len(candles) < 50:
            self._logger.warning("insufficient_candles", count=len(candles), needed=50)
            return state

        df = pd.DataFrame(candles)
        
        state.current_price = float(df["close"].iloc[-1])
        state.current_volume = float(df["volume"].iloc[-1])

        # RSI
        try:
            rsi_indicator = ta.momentum.RSIIndicator(close=df["close"], window=self.rsi_period)
            state.rsi = float(rsi_indicator.rsi().iloc[-1])
        except Exception:
            pass

        # MACD
        try:
            macd = ta.trend.MACD(
                close=df["close"], 
                window_fast=self.macd_fast, 
                window_slow=self.macd_slow, 
                window_sign=self.macd_signal_period
            )
            state.macd_line = float(macd.macd().iloc[-1])
            state.macd_signal = float(macd.macd_signal().iloc[-1])
            state.macd_histogram = float(macd.macd_diff().iloc[-1])
        except Exception:
            pass

        # EMAs
        try:
            state.ema_fast = float(ta.trend.EMAIndicator(close=df["close"], window=self.ema_fast).ema_indicator().iloc[-1])
            state.ema_slow = float(ta.trend.EMAIndicator(close=df["close"], window=self.ema_slow).ema_indicator().iloc[-1])
            state.ema_200 = float(ta.trend.EMAIndicator(close=df["close"], window=200).ema_indicator().iloc[-1])
        except Exception:
            pass

        # Bollinger Bands
        try:
            bb = ta.volatility.BollingerBands(close=df["close"], window=self.bb_period, window_dev=self.bb_std)
            state.bb_upper = float(bb.bollinger_hband().iloc[-1])
            state.bb_middle = float(bb.bollinger_mavg().iloc[-1])
            state.bb_lower = float(bb.bollinger_lband().iloc[-1])
        except Exception:
            pass

        # ATR
        try:
            atr = ta.volatility.AverageTrueRange(
                high=df["high"], low=df["low"], close=df["close"], window=self.atr_period
            )
            state.atr = float(atr.average_true_range().iloc[-1])
        except Exception:
            pass

        # Volume SMA
        try:
            state.volume_sma = float(df["volume"].rolling(window=self.volume_sma_period).mean().iloc[-1])
        except Exception:
            pass

        # Stochastic
        try:
            stoch = ta.momentum.StochasticOscillator(
                high=df["high"], low=df["low"], close=df["close"], window=self.stoch_k_period, smooth_window=self.stoch_d_period
            )
            state.stoch_k = float(stoch.stoch().iloc[-1])
            state.stoch_d = float(stoch.stoch_signal().iloc[-1])
        except Exception:
            pass

        # ADX
        try:
            adx = ta.trend.ADXIndicator(
                high=df["high"], low=df["low"], close=df["close"], window=self.adx_period
            )
            state.adx = float(adx.adx().iloc[-1])
        except Exception:
            pass

        # Donchian Channel
        try:
            dc = ta.volatility.DonchianChannel(
                high=df["high"], low=df["low"], close=df["close"], window=self.donchian_period
            )
            state.donchian_upper = float(dc.donchian_channel_hband().iloc[-1])
            state.donchian_middle = float(dc.donchian_channel_mband().iloc[-1])
            state.donchian_lower = float(dc.donchian_channel_lband().iloc[-1])
        except Exception:
            pass

        # Handle nan values
        for key, value in state.__dict__.items():
            if value is not None and (pd.isna(value) or math.isnan(value)):
                setattr(state, key, None)

        return state

    # ── Strategy evaluation ────────────────────────────────────────────────

    def _evaluate_condition(
        self,
        condition: dict[str, Any],
        state: _IndicatorState,
    ) -> bool:
        """Evaluate a single strategy condition against indicator state."""
        indicator = condition.get("indicator", "")
        params = condition.get("params", {})
        rule = condition.get("rule", "")
        price = state.current_price

        try:
            if indicator == "EMA":
                fast_period = params.get("fast", self.ema_fast)
                slow_period = params.get("slow", self.ema_slow)
                # Map to state values
                if fast_period == self.ema_fast and slow_period == self.ema_slow:
                    fast_val = state.ema_fast
                    slow_val = state.ema_slow
                elif fast_period == 50 and slow_period == 200:
                    fast_val = state.ema_slow  # approximate
                    slow_val = state.ema_200
                elif fast_period == 9 and slow_period == 21:
                    fast_val = state.ema_fast
                    slow_val = state.ema_slow
                else:
                    fast_val = state.ema_fast
                    slow_val = state.ema_slow

                if fast_val is None or slow_val is None:
                    return False

                if "fast > slow AND fast[1] <= slow[1]" in rule:
                    return fast_val > slow_val
                elif "fast > slow" in rule:
                    return fast_val > slow_val
                elif "fast < slow" in rule:
                    return fast_val < slow_val

            elif indicator == "RSI":
                if state.rsi is None:
                    return False
                rsi = state.rsi
                if "value > 50 AND value < 70" in rule:
                    return 50 < rsi < 70
                elif "value < 30" in rule:
                    return rsi < 30
                elif "value > 65" in rule:
                    return rsi > 65
                elif "value < 40" in rule:
                    return rsi < 40
                elif "value > 50 AND value < 65" in rule:
                    return 50 < rsi < 65
                elif "value > 75" in rule:
                    return rsi > 75
                elif "RSI < 25" in rule:
                    return rsi < 25

            elif indicator == "BollingerBands":
                if state.bb_lower is None or state.bb_middle is None or price is None:
                    return False
                if "price <= lower_band" in rule:
                    return price <= state.bb_lower
                elif "price >= middle_band" in rule:
                    return price >= state.bb_middle
                elif "price < lower_band * 0.99" in rule:
                    return price < state.bb_lower * 0.99

            elif indicator == "Volume":
                if state.current_volume is None or state.volume_sma is None:
                    return False
                vol = state.current_volume
                sma = state.volume_sma
                if sma == 0:
                    return False
                if "current > sma * 2.0" in rule:
                    return vol > sma * 2.0
                elif "current > sma * 1.5" in rule:
                    return vol > sma * 1.5
                elif "current > sma * 1.3" in rule:
                    return vol > sma * 1.3
                elif "current > sma * 1.2" in rule:
                    return vol > sma * 1.2
                elif "current > sma * 3.0" in rule:
                    return vol > sma * 3.0

            elif indicator == "DonchianChannel":
                if state.donchian_upper is None or state.donchian_middle is None or price is None:
                    return False
                if "price >= upper_band" in rule:
                    return price >= state.donchian_upper
                elif "price <= middle_band" in rule:
                    return price <= state.donchian_middle

            elif indicator == "MACD":
                if state.macd_histogram is None:
                    return False
                hist = state.macd_histogram
                if "histogram > 0 AND histogram > histogram[1]" in rule:
                    return hist > 0
                elif "histogram < histogram[1]" in rule:
                    return hist < 0

            elif indicator == "ATR":
                if state.atr is None:
                    return False
                if "current > sma * 1.3" in rule:
                    return True  # Simplified — always true if ATR exists

            elif indicator == "Stochastic":
                if state.stoch_k is None:
                    return False
                k = state.stoch_k
                d = state.stoch_d
                if d is not None:
                    if "k < 20 AND k > d" in rule:
                        return k < 20 and k > d
                if "k < 20" in rule:
                    return k < 20

            elif indicator == "ADX":
                if state.adx is None:
                    return False
                if "ADX > 25" in rule:
                    return state.adx > 25

        except Exception as exc:
            self._logger.debug(
                "condition_evaluation_error",
                indicator=indicator,
                error=str(exc),
            )

        return False

    def _evaluate_strategy(
        self,
        strategy: dict[str, Any],
        state: _IndicatorState,
        timeframe: str,
        symbol: str,
    ) -> Signal | None:
        """Evaluate a single strategy and return a Signal if conditions are met."""
        strategy_name = strategy["name"]
        entry = strategy.get("entry", {})
        exit_ = strategy.get("exit", {})

        entry_conditions = entry.get("conditions", [])
        exit_conditions = exit_.get("conditions", [])
        min_entry = entry.get("min_conditions", 1)
        min_exit = exit_.get("min_conditions", 1)

        # Evaluate entry conditions
        entry_hits = sum(1 for c in entry_conditions if self._evaluate_condition(c, state))
        exit_hits = sum(1 for c in exit_conditions if self._evaluate_condition(c, state))

        if entry_hits >= min_entry:
            # Entry signal triggered
            confidence_cfg = strategy.get("confidence", {})
            base_confidence = confidence_cfg.get("base", 0.5)
            max_confidence = confidence_cfg.get("max_confidence", 0.95)

            # Apply boosters
            boost = 0.0
            for booster in confidence_cfg.get("boosters", []):
                condition = booster.get("condition", "")
                bonus = booster.get("bonus", 0.0)
                # Simplified booster evaluation
                if "volume > sma * 2.0" in condition and state.current_volume and state.volume_sma:
                    if state.current_volume > state.volume_sma * 2.0:
                        boost += bonus
                elif "volume > sma * 3.0" in condition and state.current_volume and state.volume_sma:
                    if state.current_volume > state.volume_sma * 3.0:
                        boost += bonus
                elif "price > EMA200" in condition and state.ema_200 and state.current_price:
                    if state.current_price > state.ema_200:
                        boost += bonus
                elif "ADX > 25" in condition and state.adx:
                    if state.adx > 25:
                        boost += bonus
                elif "RSI < 25" in condition and state.rsi:
                    if state.rsi < 25:
                        boost += bonus
                elif "price < lower_band * 0.99" in condition and state.bb_lower and state.current_price:
                    if state.current_price < state.bb_lower * 0.99:
                        boost += bonus

            confidence = min(base_confidence + boost, max_confidence)

            # Calculate strength from how many conditions are met
            total_conditions = len(entry_conditions)
            strength = min(1.0, (entry_hits / total_conditions) * 1.5) if total_conditions > 0 else 0.5

            reasoning = self._build_reasoning(
                state=state,
                strategy_name=strategy_name,
                action="buy",
                entry_hits=entry_hits,
                total_conditions=total_conditions,
                timeframe=timeframe,
            )
            reasoning.confidence = round(confidence, 4)

            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                action="buy",
                confidence=round(confidence, 4),
                strength=round(strength, 4),
                source="technical",
                metadata={
                    "strategy": strategy_name,
                    "entry_conditions_met": entry_hits,
                    "total_entry_conditions": total_conditions,
                    "indicators": self._indicator_summary(state),
                },
                reasoning=reasoning,
            )

        elif exit_hits >= min_exit:
            # Exit signal triggered
            confidence_cfg = strategy.get("confidence", {})
            base_confidence = confidence_cfg.get("base", 0.5)

            reasoning = self._build_reasoning(
                state=state,
                strategy_name=strategy_name,
                action="sell",
                entry_hits=exit_hits,
                total_conditions=len(exit_conditions),
                timeframe=timeframe,
            )
            reasoning.confidence = round(base_confidence, 4)

            return Signal(
                symbol=symbol,
                timeframe=timeframe,
                action="sell",
                confidence=round(base_confidence, 4),
                strength=-0.5,
                source="technical",
                metadata={
                    "strategy": strategy_name,
                    "exit_conditions_met": exit_hits,
                    "total_exit_conditions": len(exit_conditions),
                    "indicators": self._indicator_summary(state),
                },
                reasoning=reasoning,
            )

        return None

    def _indicator_summary(self, state: _IndicatorState) -> dict[str, Any]:
        """Create a summary dict of current indicator values."""
        summary: dict[str, Any] = {}
        if state.rsi is not None:
            summary[f"rsi_{self.rsi_period}"] = round(state.rsi, 2)
        if state.macd_histogram is not None:
            summary["macd_histogram"] = round(state.macd_histogram, 4)
        if state.ema_fast is not None and state.ema_slow is not None:
            summary["ema_fast_slow"] = "bullish" if state.ema_fast > state.ema_slow else "bearish"
        if state.bb_upper is not None and state.bb_lower is not None:
            summary["bb_width"] = round(state.bb_upper - state.bb_lower, 4)
        if state.atr is not None:
            summary[f"atr_{self.atr_period}"] = round(state.atr, 4)
        if state.adx is not None:
            summary[f"adx_{self.adx_period}"] = round(state.adx, 2)
        if state.stoch_k is not None:
            summary["stoch_k"] = round(state.stoch_k, 2)
        if state.donchian_upper is not None:
            summary["donchian_upper"] = round(state.donchian_upper, 4)
        return summary

    def _build_reasoning(
        self,
        state: _IndicatorState,
        strategy_name: str,
        action: str,
        entry_hits: int,
        total_conditions: int,
        timeframe: str,
    ) -> Reasoning:
        """Build structured reasoning for a technical analysis signal.

        Args:
            state: Current indicator state.
            strategy_name: Name of the triggered strategy.
            action: Signal action (buy/sell).
            entry_hits: Number of entry conditions met.
            total_conditions: Total number of conditions evaluated.
            timeframe: Timeframe of the analysis.

        Returns:
            Reasoning object with structured factors and summary.
        """
        reasoning = Reasoning(
            agent="technical_analyst",
            confidence=0.0,
        )

        # RSI factor
        if state.rsi is not None:
            rsi = state.rsi
            if rsi < 30:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"RSI quá bán ({rsi:.1f} < 30) trên khung {timeframe}",
                    impact=0.15 if action == "buy" else -0.10,
                    metadata={"indicator": "RSI", "value": round(rsi, 2), "zone": "oversold"},
                ))
            elif rsi > 70:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"RSI quá mua ({rsi:.1f} > 70) trên khung {timeframe}",
                    impact=-0.10 if action == "buy" else 0.15,
                    metadata={"indicator": "RSI", "value": round(rsi, 2), "zone": "overbought"},
                ))
            elif 40 <= rsi <= 60:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"RSI trung tính ({rsi:.1f})",
                    impact=0.0,
                    metadata={"indicator": "RSI", "value": round(rsi, 2), "zone": "neutral"},
                ))

        # MACD factor
        if state.macd_histogram is not None:
            hist = state.macd_histogram
            if hist > 0:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"MACD histogram dương ({hist:.4f}), xu hướng tăng",
                    impact=0.10 if action == "buy" else -0.05,
                    metadata={"indicator": "MACD", "histogram": round(hist, 4), "direction": "bullish"},
                ))
            else:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"MACD histogram âm ({hist:.4f}), xu hướng giảm",
                    impact=-0.05 if action == "buy" else 0.10,
                    metadata={"indicator": "MACD", "histogram": round(hist, 4), "direction": "bearish"},
                ))

        # EMA factor
        if state.ema_fast is not None and state.ema_slow is not None:
            if state.ema_fast > state.ema_slow:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"EMA{self.ema_fast} > EMA{self.ema_slow} ({state.ema_fast:.2f} vs {state.ema_slow:.2f}), xu hướng tăng",
                    impact=0.10 if action == "buy" else -0.05,
                    metadata={"indicator": "EMA_cross", "fast": round(state.ema_fast, 2), "slow": round(state.ema_slow, 2)},
                ))
            else:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"EMA{self.ema_fast} < EMA{self.ema_slow} ({state.ema_fast:.2f} vs {state.ema_slow:.2f}), xu hướng giảm",
                    impact=-0.05 if action == "buy" else 0.10,
                    metadata={"indicator": "EMA_cross", "fast": round(state.ema_fast, 2), "slow": round(state.ema_slow, 2)},
                ))

        # Bollinger Bands factor
        if state.bb_lower is not None and state.current_price is not None:
            price = state.current_price
            if price <= state.bb_lower:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"Giá chạm dải dưới Bollinger Band ({price:.2f} <= {state.bb_lower:.2f})",
                    impact=0.12 if action == "buy" else -0.08,
                    metadata={"indicator": "Bollinger", "price": round(price, 2), "band": "lower"},
                ))
            elif state.bb_upper is not None and price >= state.bb_upper:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"Giá chạm dải trên Bollinger Band ({price:.2f} >= {state.bb_upper:.2f})",
                    impact=-0.08 if action == "buy" else 0.12,
                    metadata={"indicator": "Bollinger", "price": round(price, 2), "band": "upper"},
                ))

        # Volume factor
        if state.current_volume is not None and state.volume_sma is not None and state.volume_sma > 0:
            vol_ratio = state.current_volume / state.volume_sma
            if vol_ratio > 2.0:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"Volume tăng đột biến ({vol_ratio:.1f}x trung bình)",
                    impact=0.08,
                    metadata={"indicator": "Volume", "ratio": round(vol_ratio, 2)},
                ))

        # ADX factor
        if state.adx is not None and state.adx > 25:
            reasoning.add_factor(ReasoningFactor(
                type="indicator",
                description=f"ADX mạnh ({state.adx:.1f} > 25), xu hướng rõ ràng",
                impact=0.05,
                metadata={"indicator": "ADX", "value": round(state.adx, 2)},
            ))

        # Stochastic factor
        if state.stoch_k is not None:
            k = state.stoch_k
            if k < 20:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"Stochastic quá bán (%K={k:.1f})",
                    impact=0.08 if action == "buy" else -0.03,
                    metadata={"indicator": "Stochastic", "k": round(k, 2)},
                ))
            elif k > 80:
                reasoning.add_factor(ReasoningFactor(
                    type="indicator",
                    description=f"Stochastic quá mua (%K={k:.1f})",
                    impact=-0.03 if action == "buy" else 0.08,
                    metadata={"indicator": "Stochastic", "k": round(k, 2)},
                ))

        # Strategy condition factor
        condition_ratio = entry_hits / total_conditions if total_conditions > 0 else 0
        reasoning.add_factor(ReasoningFactor(
            type="pattern",
            description=f"Chiến lược '{strategy_name}': {entry_hits}/{total_conditions} điều kiện đạt ({condition_ratio:.0%})",
            impact=condition_ratio * 0.2,
            metadata={"strategy": strategy_name, "conditions_met": entry_hits, "total_conditions": total_conditions},
        ))

        # Build summary
        bullish_factors = [f for f in reasoning.factors if f.impact > 0]
        bearish_factors = [f for f in reasoning.factors if f.impact < 0]

        direction_word = "tăng" if action == "buy" else "giảm"
        summary_parts = [
            f"Phân tích kỹ thuật {direction_word} cho {timeframe}: ",
            f"{len(bullish_factors)} tín hiệu hỗ trợ, {len(bearish_factors)} tín hiệu chống đối. ",
        ]

        if bullish_factors:
            summary_parts.append(f"Lý do chính: {bullish_factors[0].description}.")

        reasoning.summary = "".join(summary_parts)
        reasoning.confidence = min(condition_ratio * 1.2, 0.95)

        return reasoning

    # ── Multi-timeframe confirmation ───────────────────────────────────────

    def _apply_mtf_confirmation(
        self,
        signals: list[Signal],
        symbol: str,
    ) -> list[Signal]:
        """Boost confidence if signals align across timeframes."""
        if not self.mtf_enabled or not signals:
            return signals

        # Group by action
        buy_signals = [s for s in signals if s.action == "buy"]
        sell_signals = [s for s in signals if s.action == "sell"]

        timeframes_seen = set(s.timeframe for s in signals)

        if len(buy_signals) > 1 and len(timeframes_seen) > 1:
            # Multiple buy signals across timeframes
            for sig in buy_signals:
                sig.confidence = min(sig.confidence + self.mtf_boost, 0.95)
                sig.metadata["mtf_boosted"] = True
                sig.metadata["mtf_timeframes"] = list(timeframes_seen)

        if len(sell_signals) > 1 and len(timeframes_seen) > 1:
            for sig in sell_signals:
                sig.confidence = min(sig.confidence + self.mtf_boost, 0.95)
                sig.metadata["mtf_boosted"] = True
                sig.metadata["mtf_timeframes"] = list(timeframes_seen)

        return signals

    # ── Main run ───────────────────────────────────────────────────────────

    async def run(self) -> list[Signal]:
        """Execute technical analysis across all symbols and timeframes.

        Returns:
            List of Signal objects from strategy evaluations.
        """
        if not self._strategies:
            self._logger.warning("no_strategies_loaded")
            return []

        if self._data_source is None:
            self._logger.error("no_data_source_configured")
            return []

        all_signals: list[Signal] = []

        for symbol in self.symbols:
            symbol_signals: list[Signal] = []

            for timeframe in self.timeframes:
                try:
                    # Fetch OHLCV data
                    candles = await self._data_source.get_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=250,
                    )

                    if len(candles) < 50:
                        self._logger.debug(
                            "insufficient_data",
                            symbol=symbol,
                            timeframe=timeframe,
                            count=len(candles),
                        )
                        continue

                    # Compute indicators
                    state = self._compute_indicators(candles)

                    # Evaluate each strategy
                    for strategy in self._strategies:
                        try:
                            signal = self._evaluate_strategy(
                                strategy, state, timeframe, symbol
                            )
                            if signal:
                                symbol_signals.append(signal)
                                self._logger.info(
                                    "strategy_triggered",
                                    strategy=strategy["name"],
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    action=signal.action,
                                    confidence=signal.confidence,
                                )
                        except Exception as exc:
                            self._logger.error(
                                "strategy_evaluation_failed",
                                strategy=strategy.get("name", "unknown"),
                                error=str(exc),
                            )

                except Exception as exc:
                    self._logger.error(
                        "timeframe_analysis_failed",
                        symbol=symbol,
                        timeframe=timeframe,
                        error=str(exc),
                    )

            # Apply multi-timeframe confirmation
            symbol_signals = self._apply_mtf_confirmation(symbol_signals, symbol)
            all_signals.extend(symbol_signals)

        self._logger.info(
            "analysis_cycle_complete",
            symbols=len(self.symbols),
            timeframes=len(self.timeframes),
            strategies=len(self._strategies),
            signals=len(all_signals),
        )
        return all_signals
