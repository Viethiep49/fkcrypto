"""Backtest engine — orchestrates replay, agents, decision engine, and simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from src.agents.analyst import TechnicalAnalystAgent
from src.agents.decision_engine import DecisionEngine
from src.agents.signal import Signal
from src.backtesting.data_replay import DataReplayEngine, DataWindow
from src.backtesting.metrics import compute_metrics
from src.backtesting.simulator import TradingSimulator

logger = structlog.get_logger(__name__)


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    symbol: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    initial_capital: float
    final_value: float
    total_return_pct: float
    buy_and_hold_return_pct: float
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    avg_trade_duration_hours: float
    decisions: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "initial_capital": self.initial_capital,
            "final_value": self.final_value,
            "total_return_pct": self.total_return_pct,
            "buy_and_hold_return_pct": self.buy_and_hold_return_pct,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "avg_trade_duration_hours": self.avg_trade_duration_hours,
        }


class BacktestEngine:
    """Orchestrates a full backtest run.

    Uses the same Decision Engine and agents as live trading.
    Replays historical data candle-by-candle, generates signals,
    simulates execution, and computes metrics.
    """

    def __init__(
        self,
        candles: list[dict[str, Any]],
        symbol: str,
        timeframe: str,
        analyst_agent: TechnicalAnalystAgent,
        decision_engine: DecisionEngine,
        initial_capital: float = 100_000.0,
        fee_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        lookback: int = 250,
        allocation_pct: float = 0.95,
    ) -> None:
        self._replay = DataReplayEngine(
            candles=candles,
            symbol=symbol,
            timeframe=timeframe,
            lookback=lookback,
        )
        self._analyst = analyst_agent
        self._decision_engine = decision_engine
        self._symbol = symbol
        self._timeframe = timeframe
        self._allocation_pct = allocation_pct

        self._simulator = TradingSimulator(
            initial_capital=initial_capital,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
            symbol=symbol,
        )

        self._decisions: list[dict[str, Any]] = []
        self._prev_action: str = "hold"

    async def run(self) -> BacktestResult:
        """Execute the full backtest.

        Returns:
            BacktestResult with all metrics and history.
        """
        logger.info(
            "backtest_start",
            symbol=self._symbol,
            timeframe=self._timeframe,
            candles=len(self._replay._candles),
        )

        first_ts = self._replay._candles[0].get("timestamp", 0)
        last_ts = self._replay._candles[-1].get("timestamp", 0)

        if isinstance(first_ts, (int, float)):
            start_dt = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc)
        else:
            start_dt = first_ts if isinstance(first_ts, datetime) else datetime.now(timezone.utc)

        if isinstance(last_ts, (int, float)):
            end_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)
        else:
            end_dt = last_ts if isinstance(last_ts, datetime) else datetime.now(timezone.utc)

        buy_and_hold = self._calc_buy_and_hold()

        async for window in self._replay.stream():
            signals = await self._generate_signals(window)
            decision = await self._make_decision(signals, window.timestamp)
            await self._execute_decision(decision, window)
            self._simulator.snapshot(
                timestamp=window.timestamp,
                current_price=window.current_candle["close"],
                step_index=window.step_index,
            )

        summary = self._simulator.finalize()
        metrics = compute_metrics(
            trades=self._simulator.trades,
            snapshots=self._simulator.snapshots,
            initial_capital=self._simulator.initial_capital,
            buy_and_hold_return=buy_and_hold,
        )

        result = BacktestResult(
            symbol=self._symbol,
            timeframe=self._timeframe,
            start_time=start_dt,
            end_time=end_dt,
            initial_capital=self._simulator.initial_capital,
            final_value=summary["final_value"],
            total_return_pct=summary["total_return_pct"],
            buy_and_hold_return_pct=buy_and_hold,
            total_trades=summary["total_trades"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sharpe_ratio=metrics["sharpe_ratio"],
            sortino_ratio=metrics["sortino_ratio"],
            calmar_ratio=metrics["calmar_ratio"],
            avg_trade_duration_hours=metrics["avg_trade_duration_hours"],
            decisions=self._decisions,
            snapshots=[self._snap_to_dict(s) for s in self._simulator.snapshots],
            trades=[self._trade_to_dict(t) for t in self._simulator.trades],
        )

        logger.info(
            "backtest_complete",
            symbol=self._symbol,
            final_value=result.final_value,
            total_return_pct=result.total_return_pct,
            total_trades=result.total_trades,
            win_rate=result.win_rate,
        )

        return result

    async def _generate_signals(self, window: DataWindow) -> list[Signal]:
        self._analyst._data_source = None
        signals: list[Signal] = []

        for strategy in self._analyst._strategies:
            try:
                state = self._analyst._compute_indicators(window.candles)
                sig = self._analyst._evaluate_strategy(
                    strategy, state, self._timeframe, self._symbol
                )
                if sig:
                    sig.timestamp = window.timestamp
                    signals.append(sig)
            except Exception as exc:
                logger.warning(
                    "strategy_error_in_backtest",
                    strategy=strategy.get("name", "unknown"),
                    error=str(exc),
                )

        if self._analyst.mtf_enabled and len(signals) > 1:
            signals = self._analyst._apply_mtf_confirmation(signals, self._symbol)

        return signals

    async def _make_decision(
        self,
        signals: list[Signal],
        timestamp: datetime,
    ) -> dict[str, Any]:
        decision = await self._decision_engine.process_signals(signals, self._symbol)
        decision.timestamp = timestamp

        dec_dict = decision.to_dict()
        dec_dict["timestamp"] = timestamp.isoformat()
        self._decisions.append(dec_dict)

        return {
            "action": decision.action,
            "score": decision.score,
            "confidence": decision.confidence,
            "timestamp": timestamp,
        }

    async def _execute_decision(
        self,
        decision: dict[str, Any],
        window: DataWindow,
    ) -> None:
        price = window.current_candle["close"]
        action = decision["action"]

        if action == "buy" and not self._simulator.is_in_position:
            self._simulator.simulate_buy(
                price=price,
                timestamp=window.timestamp,
                allocation_pct=self._allocation_pct,
            )
        elif action == "sell" and self._simulator.is_in_position:
            self._simulator.simulate_sell(
                price=price,
                timestamp=window.timestamp,
            )

        self._prev_action = action

    def _calc_buy_and_hold(self) -> float:
        candles = self._replay._candles
        if len(candles) < 2:
            return 0.0
        start_price = candles[0]["close"]
        end_price = candles[-1]["close"]
        return (end_price - start_price) / start_price

    @staticmethod
    def _snap_to_dict(s: Any) -> dict[str, Any]:
        return {
            "timestamp": s.timestamp.isoformat(),
            "cash": s.cash,
            "position_size": s.position_size,
            "portfolio_value": s.portfolio_value,
            "step_index": s.step_index,
        }

    @staticmethod
    def _trade_to_dict(t: Any) -> dict[str, Any]:
        return {
            "symbol": t.symbol,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "size": t.size,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "fees": t.fees,
            "slippage": t.slippage,
        }
