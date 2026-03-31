"""Agent node implementations for LangGraph workflow.

Each node function wraps a real agent and translates between
LangGraph state dicts and agent-native Signal objects.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.gateway.graph import AgentState

logger = structlog.get_logger(__name__)


def make_market_monitor_node(market_monitor):
    """Create a market_monitor node backed by a MarketMonitorAgent instance."""

    async def node(state: AgentState) -> dict:
        try:
            signals = await market_monitor.run()
            signal_dicts = [s.to_dict() for s in signals]
            existing = list(state.get("signals", []))
            return {
                "signals": existing + signal_dicts,
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("market_monitor_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "signals": state.get("signals", []),
                "errors": errors + [f"market_monitor: {exc}"],
            }

    return node


def make_analyst_node(analyst):
    """Create an analyst node backed by a TechnicalAnalystAgent instance."""

    async def node(state: AgentState) -> dict:
        try:
            signals = await analyst.run()
            signal_dicts = [s.to_dict() for s in signals]
            existing = list(state.get("signals", []))
            return {
                "signals": existing + signal_dicts,
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("analyst_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "signals": state.get("signals", []),
                "errors": errors + [f"analyst: {exc}"],
            }

    return node


def make_sentiment_node(sentiment_agent):
    """Create a sentiment node backed by a NewsSentimentAgent instance."""

    async def node(state: AgentState) -> dict:
        try:
            signals = await sentiment_agent.run()
            signal_dicts = [s.to_dict() for s in signals]
            existing = list(state.get("signals", []))
            return {
                "signals": existing + signal_dicts,
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("sentiment_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "signals": state.get("signals", []),
                "errors": errors + [f"sentiment: {exc}"],
            }

    return node


def make_risk_node(risk_guardian):
    """Create a risk node backed by a RiskGuardianAgent instance."""

    async def node(state: AgentState) -> dict:
        try:
            portfolio_value = state.get("portfolio_value")
            positions = state.get("positions")
            signals = await risk_guardian.run(
                portfolio_value=portfolio_value,
                positions=positions,
            )
            signal_dicts = [s.to_dict() for s in signals]
            existing = list(state.get("signals", []))
            return {
                "signals": existing + signal_dicts,
                "kill_switch_active": risk_guardian.is_kill_switch_active,
                "kill_switch_reason": risk_guardian.kill_switch_reason or "",
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("risk_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "signals": state.get("signals", []),
                "kill_switch_active": False,
                "kill_switch_reason": f"risk_check_error: {exc}",
                "errors": errors + [f"risk: {exc}"],
            }

    return node


def make_decision_node(decision_engine):
    """Create a decision node backed by a DecisionEngine instance."""

    async def node(state: AgentState) -> dict:
        try:
            from src.agents.signal import Signal

            symbol = state.get("symbol", "")
            raw_signals = state.get("signals", [])

            # Convert dicts back to Signal objects
            signals = [Signal.from_dict(s) for s in raw_signals]

            decision = await decision_engine.process_signals(signals, symbol)

            return {
                "score": decision.score,
                "decision": decision.action,
                "confidence": decision.confidence,
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("decision_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "score": 0.0,
                "decision": "hold",
                "confidence": 0.0,
                "errors": errors + [f"decision: {exc}"],
            }

    return node


def make_execution_node(execution_service):
    """Create an execution node backed by an ExecutionService instance."""

    async def node(state: AgentState) -> dict:
        try:
            from src.agents.decision_engine import Decision

            decision = Decision(
                symbol=state.get("symbol", ""),
                action=state.get("decision", "hold"),
                score=state.get("score", 0.0),
                confidence=state.get("confidence", 0.0),
                signals=[],
            )

            result = await execution_service.execute(decision)

            return {
                "execution_result": {
                    "success": result.success,
                    "order_id": result.order_id,
                    "message": result.message,
                    "rejected_reason": result.rejected_reason,
                },
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("execution_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "execution_result": {
                    "success": False,
                    "message": str(exc),
                },
                "errors": errors + [f"execution: {exc}"],
            }

    return node


def make_alpha_seeker_node(alpha_seeker):
    """Create an alpha_seeker node backed by an AlphaSeekerAgent instance."""

    async def node(state: AgentState) -> dict:
        try:
            signals = await alpha_seeker.run()
            signal_dicts = [s.to_dict() for s in signals]
            existing = list(state.get("signals", []))
            return {
                "signals": existing + signal_dicts,
                "timestamp": state.get("timestamp", ""),
            }
        except Exception as exc:
            logger.error("alpha_seeker_node_failed", error=str(exc))
            errors = list(state.get("errors", []))
            return {
                "signals": state.get("signals", []),
                "errors": errors + [f"alpha_seeker: {exc}"],
            }

    return node
