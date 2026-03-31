"""LangGraph orchestrator — main state machine for the trading system."""

from __future__ import annotations

from typing import TypedDict, Optional
from datetime import datetime, timezone

from langgraph.graph import StateGraph, END


class AgentState(TypedDict):
    """Shared state passed between all nodes in the graph."""

    # Current trading pair being analyzed
    symbol: str

    # Signals collected from agents (list of signal dicts)
    signals: list[dict]

    # Aggregated score and decision
    score: float
    decision: str  # "buy", "sell", "hold"
    confidence: float

    # Risk state
    kill_switch_active: bool
    kill_switch_reason: str

    # Portfolio context (injected at runtime)
    portfolio_value: float
    positions: list[dict]

    # Error handling
    errors: list[str]
    retry_count: int

    # Execution result
    execution_result: dict

    # Metadata
    timestamp: str
    run_id: str


def build_graph() -> StateGraph:
    """Build the LangGraph workflow.

    Graph structure:
        market_monitor ──┐
        analyst      ────┼──→ decision ──→ execution
        sentiment    ────┤
        risk         ────┘
        alpha        ────┘
    """
    graph = StateGraph(AgentState)

    # Add placeholder nodes — actual callables are set in create_app()
    graph.add_node("market_monitor", _stub_node)
    graph.add_node("analyst", _stub_node)
    graph.add_node("sentiment", _stub_node)
    graph.add_node("risk", _stub_node)
    graph.add_node("alpha", _stub_node)
    graph.add_node("decision", _stub_node)
    graph.add_node("execution", _stub_node)

    # Add edges — agents run in parallel, then converge on decision
    graph.add_edge("market_monitor", "decision")
    graph.add_edge("analyst", "decision")
    graph.add_edge("sentiment", "decision")
    graph.add_edge("risk", "decision")
    graph.add_edge("alpha", "decision")

    # Decision → Execution
    graph.add_edge("decision", "execution")

    # Entry and exit points
    graph.set_entry_point("market_monitor")
    graph.add_edge("execution", END)

    return graph


def _stub_node(state: AgentState) -> AgentState:
    """Placeholder node — replaced at runtime with actual agent runners."""
    return state


def create_app(node_fns: dict[str, callable] | None = None):
    """Create and compile the LangGraph application.

    Args:
        node_fns: Optional dict mapping node names to callable functions.
                  If provided, replaces the stub nodes before compilation.
                  Expected keys: market_monitor, analyst, sentiment, risk, decision, execution

    Returns:
        Compiled LangGraph application.
    """
    graph = build_graph()

    if node_fns:
        for node_name, fn in node_fns.items():
            if node_name in ("market_monitor", "analyst", "sentiment", "risk", "decision", "execution"):
                graph.add_node(node_name, fn)

    return graph.compile()
