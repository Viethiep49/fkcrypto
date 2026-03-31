"""FKCrypto Trading Dashboard — Streamlit-based monitoring UI."""

import os
import json
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

st.set_page_config(
    page_title="FKCrypto Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("FKCrypto Trading Dashboard")


@st.cache_resource
def get_db_engine():
    """Get cached database engine."""
    db_url = os.environ.get("DATABASE_URL", "sqlite:///fkcrypto.db")
    return create_engine(db_url, echo=False)


@st.cache_resource
def get_session_factory():
    """Get cached session factory."""
    engine = get_db_engine()
    return sessionmaker(bind=engine)


def fetch_recent_signals(limit=200):
    """Fetch recent signals from database."""
    from src.database.models import SignalRecord
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(SignalRecord).order_by(desc(SignalRecord.timestamp)).limit(limit)
        rows = session.execute(query).scalars().all()
        return [
            {
                "timestamp": r.timestamp,
                "symbol": r.symbol,
                "action": r.action,
                "confidence": r.confidence,
                "strength": r.strength,
                "source": r.source,
                "timeframe": r.timeframe,
                "reasoning_json": r.reasoning_json,
                "reasoning_summary": r.reasoning_summary,
            }
            for r in rows
        ]
    finally:
        session.close()


def fetch_recent_decisions(limit=100):
    """Fetch recent decisions from database."""
    from src.database.models import DecisionRecord
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(DecisionRecord).order_by(desc(DecisionRecord.timestamp)).limit(limit)
        rows = session.execute(query).scalars().all()
        return [
            {
                "timestamp": r.timestamp,
                "symbol": r.symbol,
                "action": r.action,
                "score": r.score,
                "confidence": r.confidence,
                "sources": r.sources,
                "explanation": r.explanation,
            }
            for r in rows
        ]
    finally:
        session.close()


def fetch_recent_orders(limit=100):
    """Fetch recent orders from database."""
    from src.database.models import OrderRecord
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(OrderRecord).order_by(desc(OrderRecord.timestamp)).limit(limit)
        rows = session.execute(query).scalars().all()
        return [
            {
                "timestamp": r.timestamp,
                "symbol": r.symbol,
                "action": r.action,
                "size_usd": r.size_usd,
                "status": r.status,
                "order_id": r.freqtrade_order_id,
                "reason": r.reason,
                "rejected_reason": r.rejected_reason,
            }
            for r in rows
        ]
    finally:
        session.close()


def fetch_portfolio_snapshots(limit=50):
    """Fetch portfolio snapshots from database."""
    from src.database.models import PortfolioSnapshot
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).limit(limit)
        rows = session.execute(query).scalars().all()
        return [
            {
                "timestamp": r.timestamp,
                "total_value": r.total_value,
                "cash": r.cash,
                "positions_value": r.positions_value,
                "drawdown_pct": r.drawdown_pct,
                "daily_pnl": r.daily_pnl,
            }
            for r in rows
        ]
    finally:
        session.close()


def fetch_kill_switch_events():
    """Fetch kill switch events."""
    from src.database.models import KillSwitchEvent
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(KillSwitchEvent).order_by(desc(KillSwitchEvent.triggered_at)).limit(20)
        rows = session.execute(query).scalars().all()
        return [
            {
                "timestamp": r.triggered_at,
                "reason": r.reason,
                "active": r.active,
                "reset_at": r.reset_at,
                "reset_by": r.reset_by,
            }
            for r in rows
        ]
    finally:
        session.close()


def fetch_approval_requests():
    """Fetch approval requests from database."""
    from src.database.models import ApprovalRecord
    session = get_session_factory()()
    try:
        from sqlalchemy import desc, select
        query = select(ApprovalRecord).order_by(
            desc(ApprovalRecord.created_at)
        ).limit(50)
        rows = session.execute(query).scalars().all()
        return [
            {
                "request_id": r.request_id,
                "symbol": r.symbol,
                "action": r.action,
                "score": r.score,
                "confidence": r.confidence,
                "size_usd": r.size_usd,
                "status": r.status,
                "reasoning_summary": r.reasoning_summary,
                "sources": r.sources,
                "created_at": r.created_at,
                "responded_at": r.responded_at,
                "responder": r.responder,
                "rejection_reason": r.rejection_reason,
            }
            for r in rows
        ]
    finally:
        session.close()


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.header("Settings")
refresh_interval = st.sidebar.slider("Auto-refresh (seconds)", 5, 120, 30)
max_signals = st.sidebar.slider("Max signals to show", 50, 500, 200)
selected_symbol = st.sidebar.selectbox(
    "Filter by symbol",
    ["All", "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
)

# ── Fetch data ───────────────────────────────────────────────────────────────

signals = fetch_recent_signals(max_signals)
decisions = fetch_recent_decisions()
orders = fetch_recent_orders()
snapshots = fetch_portfolio_snapshots()
kill_events = fetch_kill_switch_events()
approvals = fetch_approval_requests()

# Apply symbol filter
if selected_symbol != "All":
    signals = [s for s in signals if s["symbol"] == selected_symbol]
    decisions = [d for d in decisions if d["symbol"] == selected_symbol]
    orders = [o for o in orders if o["symbol"] == selected_symbol]

# ── Status bar ───────────────────────────────────────────────────────────────

status_col1, status_col2, status_col3, status_col4 = st.columns(4)

total_signals = len(signals)
buy_signals = len([s for s in signals if s["action"] == "buy"])
sell_signals = len([s for s in signals if s["action"] == "sell"])
hold_signals = len([s for s in signals if s["action"] == "hold"])

status_col1.metric("Total Signals", total_signals)
status_col2.metric("Buy Signals", buy_signals)
status_col3.metric("Sell Signals", sell_signals)
status_col4.metric("Hold Signals", hold_signals)

# Kill switch status
active_kills = [k for k in kill_events if k.get("active")]
if active_kills:
    st.error(f"🚨 KILL SWITCH ACTIVE — {active_kills[0].get('reason', 'Unknown reason')}")
else:
    st.success("✅ System Operational")

# ── Portfolio chart ──────────────────────────────────────────────────────────

if snapshots:
    st.subheader("Portfolio Value")
    df_snap = pd.DataFrame(snapshots)
    df_snap["timestamp"] = pd.to_datetime(df_snap["timestamp"])
    df_snap = df_snap.sort_values("timestamp")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_snap["timestamp"],
        y=df_snap["total_value"],
        mode="lines+markers",
        name="Portfolio Value",
        line=dict(color="#00ff88", width=2),
    ))
    if "drawdown_pct" in df_snap.columns:
        fig.add_trace(go.Scatter(
            x=df_snap["timestamp"],
            y=df_snap["drawdown_pct"],
            mode="lines",
            name="Drawdown %",
            line=dict(color="#ff4444", width=1, dash="dash"),
            yaxis="y2",
        ))
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Value (USD)",
        yaxis2=dict(title="Drawdown %", overlaying="y", side="right", range=[-0.25, 0]),
        template="plotly_dark",
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Signal distribution ──────────────────────────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Signals by Source")
    if signals:
        df_sig = pd.DataFrame(signals)
        source_counts = df_sig["source"].value_counts()
        fig_pie = go.Figure(data=[go.Pie(
            labels=source_counts.index.tolist(),
            values=source_counts.values.tolist(),
            hole=0.4,
        )])
        fig_pie.update_layout(template="plotly_dark", height=300)
        st.plotly_chart(fig_pie, use_container_width=True)

with col2:
    st.subheader("Signal Confidence Distribution")
    if signals:
        df_sig = pd.DataFrame(signals)
        fig_hist = go.Figure(data=[go.Histogram(
            x=df_sig["confidence"],
            nbinsx=20,
            marker_color="#00ff88",
        )])
        fig_hist.update_layout(
            xaxis_title="Confidence",
            yaxis_title="Count",
            template="plotly_dark",
            height=300,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

# ── Score over time ──────────────────────────────────────────────────────────

if decisions:
    st.subheader("Decision Scores Over Time")
    df_dec = pd.DataFrame(decisions)
    df_dec["timestamp"] = pd.to_datetime(df_dec["timestamp"])
    df_dec = df_dec.sort_values("timestamp")

    color_map = {"buy": "#00ff88", "sell": "#ff4444", "hold": "#888888"}
    df_dec["color"] = df_dec["action"].map(color_map)

    fig_score = go.Figure()
    fig_score.add_trace(go.Scatter(
        x=df_dec["timestamp"],
        y=df_dec["score"],
        mode="markers+lines",
        marker=dict(
            size=8,
            color=df_dec["color"],
            line=dict(width=1, color="white"),
        ),
        name="Score",
    ))
    fig_score.add_hline(y=0.6, line_dash="dash", line_color="green", annotation_text="Buy threshold")
    fig_score.add_hline(y=-0.6, line_dash="dash", line_color="red", annotation_text="Sell threshold")
    fig_score.add_hline(y=0, line_dash="dot", line_color="gray")
    fig_score.update_layout(
        xaxis_title="Time",
        yaxis_title="Score",
        yaxis_range=[-1, 1],
        template="plotly_dark",
        height=350,
    )
    st.plotly_chart(fig_score, use_container_width=True)

# ── Recent decisions table ───────────────────────────────────────────────────

st.subheader("Recent Decisions")
if decisions:
    df_dec_table = pd.DataFrame(decisions)
    df_dec_table["timestamp"] = pd.to_datetime(df_dec_table["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(
        df_dec_table[["timestamp", "symbol", "action", "score", "confidence", "sources"]],
        use_container_width=True,
        hide_index=True,
    )

# ── Recent orders table ──────────────────────────────────────────────────────

st.subheader("Recent Orders")
if orders:
    df_ord = pd.DataFrame(orders)
    df_ord["timestamp"] = pd.to_datetime(df_ord["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(
        df_ord[["timestamp", "symbol", "action", "status", "size_usd", "order_id"]],
        use_container_width=True,
        hide_index=True,
    )

# ── Recent signals table ─────────────────────────────────────────────────────

st.subheader("Recent Signals")
if signals:
    df_sig_table = pd.DataFrame(signals)
    df_sig_table["timestamp"] = pd.to_datetime(df_sig_table["timestamp"])
    if "timestamp" in df_sig_table.columns:
        df_sig_table["timestamp"] = df_sig_table["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(
        df_sig_table[["timestamp", "symbol", "action", "confidence", "strength", "source", "timeframe"]],
        use_container_width=True,
        hide_index=True,
    )

# ── Agent Reasoning Log ──────────────────────────────────────────────────────

st.subheader("Agent Reasoning Log")
reasoning_signals = [s for s in signals if s.get("reasoning_summary")]
if reasoning_signals:
    reasoning_signals = sorted(
        reasoning_signals,
        key=lambda s: s["timestamp"],
        reverse=True,
    )[:50]

    for sig in reasoning_signals:
        reasoning = sig.get("reasoning_json")
        summary = sig.get("reasoning_summary", "")
        if not summary:
            continue

        agent_name = "Unknown"
        if isinstance(reasoning, str):
            try:
                reasoning = json.loads(reasoning)
            except (json.JSONDecodeError, TypeError):
                reasoning = {}

        if isinstance(reasoning, dict):
            agent_name = reasoning.get("agent", sig.get("source", "unknown"))

        action = sig.get("action", "").upper()
        symbol = sig.get("symbol", "")
        ts = sig.get("timestamp", "")
        confidence = sig.get("confidence", 0)

        action_colors = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
        action_icon = action_colors.get(action, "⚪")

        with st.expander(f"{action_icon} {symbol} — {action} ({confidence:.0%}) — {agent_name}"):
            st.markdown(f"**{summary}**")
            st.caption(f"Time: {ts} | Confidence: {confidence:.0%}")

            if isinstance(reasoning, dict) and "factors" in reasoning:
                factors = reasoning["factors"]
                if factors:
                    st.markdown("---")
                    st.markdown("**Chi tiết các yếu tố:**")
                    for factor in factors:
                        f_type = factor.get("type", "")
                        f_desc = factor.get("description", "")
                        f_impact = factor.get("impact", 0)

                        type_icons = {
                            "indicator": "📊",
                            "news": "📰",
                            "social": "💬",
                            "risk": "⚠️",
                            "pattern": "🔍",
                            "event": "🔔",
                        }
                        icon = type_icons.get(f_type, "•")
                        impact_arrow = "↑" if f_impact > 0 else "↓" if f_impact < 0 else "→"
                        st.markdown(f"- {icon} {f_desc} ({impact_arrow}{abs(f_impact):.2f})")
else:
    st.info("Chưa có dữ liệu reasoning. Các agents sẽ tự động sinh reasoning khi phát tín hiệu.")

# ── Kill switch events ───────────────────────────────────────────────────────

if kill_events:
    st.subheader("Kill Switch Events")
    df_kill = pd.DataFrame(kill_events)
    df_kill["timestamp"] = pd.to_datetime(df_kill["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    st.dataframe(
        df_kill[["timestamp", "reason", "active", "reset_at", "reset_by"]],
        use_container_width=True,
        hide_index=True,
    )

# ── Approval Requests (Human-in-the-loop) ────────────────────────────────────

st.subheader("Phê duyệt lệnh (Human-in-the-loop)")
pending_approvals = [a for a in approvals if a["status"] == "pending"]
if pending_approvals:
    st.warning(f"Có {len(pending_approvals)} lệnh đang chờ phê duyệt")
    for req in pending_approvals:
        action = req["action"].upper()
        symbol = req["symbol"]
        score = req["score"]
        confidence = req["confidence"]
        created = req["created_at"]
        reasoning = req.get("reasoning_summary", "")
        sources = req.get("sources", "")

        action_colors = {"BUY": "🟢", "SELL": "🔴"}
        icon = action_colors.get(action, "⚪")

        with st.container():
            st.markdown(f"### {icon} {symbol} — {action}")
            col_a1, col_a2, col_a3, col_a4 = st.columns(4)
            col_a1.metric("Score", f"{score:.2f}")
            col_a2.metric("Confidence", f"{confidence:.0%}")
            col_a3.metric("Nguồn", sources)
            col_a4.caption(f"Tạo: {created}")

            if reasoning:
                st.info(reasoning)

            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button(
                f"✅ Duyệt {symbol}",
                key=f"approve_{req['request_id']}",
            ):
                st.success(f"Đã duyệt lệnh {symbol} {action}")
            if btn_col2.button(
                f"❌ Bỏ qua {symbol}",
                key=f"reject_{req['request_id']}",
            ):
                st.warning(f"Đã bỏ qua lệnh {symbol} {action}")
            st.divider()
else:
    st.info("Không có lệnh nào đang chờ phê duyệt.")

if approvals:
    with st.expander("Lịch sử phê duyệt"):
        df_appr = pd.DataFrame(approvals)
        df_appr["created_at"] = pd.to_datetime(df_appr["created_at"]).dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        status_colors = {
            "pending": "🟡",
            "approved": "🟢",
            "rejected": "🔴",
            "expired": "⚪",
        }
        df_appr["status_icon"] = df_appr["status"].map(status_colors)
        st.dataframe(
            df_appr[
                ["status_icon", "request_id", "symbol", "action", "score", "confidence", "status", "created_at"]
            ],
            use_container_width=True,
            hide_index=True,
        )

# ── Visual Backtest Replay ───────────────────────────────────────────────────

st.subheader("Visual Backtest Replay")
st.caption("Chọn một lệnh trong quá khứ để xem lại bối cảnh thị trường và lập luận của bot tại thời điểm đó.")

if decisions:
    replay_decisions = [d for d in decisions if d.get("explanation")]
    if replay_decisions:
        decision_options = [
            f"{d['timestamp']} | {d['symbol']} | {d['action'].upper()} | Score: {d['score']:.2f}"
            for d in replay_decisions
        ]
        selected_idx = st.selectbox(
            "Chọn lệnh để replay",
            range(len(decision_options)),
            format_func=lambda i: decision_options[i],
        )
        if selected_idx is not None:
            selected_decision = replay_decisions[selected_idx]
            st.divider()

            col_r1, col_r2, col_r3, col_r4 = st.columns(4)
            col_r1.metric("Symbol", selected_decision["symbol"])
            action_val = selected_decision["action"].upper()
            col_r2.metric("Action", action_val)
            col_r3.metric("Score", f"{selected_decision['score']:.2f}")
            col_r4.metric("Confidence", f"{selected_decision['confidence']:.0%}")

            if selected_decision.get("explanation"):
                st.markdown("**Giải thích của Decision Engine:**")
                st.info(selected_decision["explanation"])

            st.markdown("**Nguồn tín hiệu:**")
            st.caption(selected_decision.get("sources", "N/A"))

            signals_for_decision = [
                s for s in signals
                if s.get("symbol") == selected_decision["symbol"]
                and abs((pd.to_datetime(s["timestamp"]) - pd.to_datetime(selected_decision["timestamp"])).total_seconds()) < 300
            ]
            if signals_for_decision:
                st.markdown("**Signals liên quan:**")
                for sig in signals_for_decision[:5]:
                    agent = sig.get("source", "unknown")
                    action_s = sig.get("action", "").upper()
                    conf_s = sig.get("confidence", 0)
                    summary = sig.get("reasoning_summary", "")
                    st.markdown(
                        f"- **{agent}**: {action_s} (conf={conf_s:.0%})"
                        f"{f' — {summary}' if summary else ''}"
                    )
            else:
                st.info("Không tìm thấy signals chi tiết cho lệnh này.")
    else:
        st.info("Chưa có decisions với explanation để replay.")
else:
    st.info("Chưa có dữ liệu decisions.")

# ── Auto-refresh ─────────────────────────────────────────────────────────────

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — Auto-refresh: {refresh_interval}s")
st.rerun()
