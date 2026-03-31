"""Database models — SQLAlchemy ORM definitions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class SignalRecord(Base):
    """Stores raw signals from all agents."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    timeframe = Column(String(16), nullable=False)
    action = Column(String(8), nullable=False)
    confidence = Column(Float, nullable=False)
    strength = Column(Float, default=0.0)
    source = Column(String(32), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    metadata_json = Column(Text, default="{}")
    reasoning_json = Column(Text, default="{}")
    reasoning_summary = Column(Text, default="")

    def __repr__(self) -> str:
        return f"<Signal {self.symbol} {self.action} conf={self.confidence}>"


class DecisionRecord(Base):
    """Stores final decisions from the Decision Engine."""

    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    action = Column(String(8), nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    signal_count = Column(Integer, default=0)
    sources = Column(Text, default="")  # comma-separated
    explanation = Column(Text, default="")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    # Relationship to orders
    orders = relationship("OrderRecord", back_populates="decision")

    def __repr__(self) -> str:
        return f"<Decision {self.symbol} {self.action} score={self.score}>"


class OrderRecord(Base):
    """Stores execution results — audit trail."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(Integer, ForeignKey("decisions.id"), nullable=True)
    symbol = Column(String(32), nullable=False, index=True)
    action = Column(String(8), nullable=False)
    size_usd = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    status = Column(String(16), nullable=False, default="pending")  # pending, filled, rejected, cancelled
    freqtrade_order_id = Column(String(64), nullable=True)
    reason = Column(Text, default="")
    rejected_reason = Column(Text, default="")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    filled_at = Column(DateTime, nullable=True)

    decision = relationship("DecisionRecord", back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order {self.symbol} {self.action} {self.status}>"


class PortfolioSnapshot(Base):
    """Stores periodic portfolio snapshots for tracking."""

    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_value_usd = Column(Float, nullable=False)
    cash_usd = Column(Float, nullable=False)
    positions_json = Column(Text, default="{}")
    daily_pnl = Column(Float, default=0.0)
    drawdown_pct = Column(Float, default=0.0)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return f"<Portfolio ${self.total_value_usd:,.2f} dd={self.drawdown_pct:.1%}>"


class KillSwitchEvent(Base):
    """Stores kill switch activation events."""

    __tablename__ = "kill_switch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reason = Column(String(64), nullable=False)
    detail = Column(Text, default="")
    triggered_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    reset_at = Column(DateTime, nullable=True)
    reset_by = Column(String(32), nullable=True)  # "manual" or "auto"
    active = Column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<KillSwitch {self.reason} active={self.active}>"


class ApprovalRecord(Base):
    """Stores human-in-the-loop approval requests."""

    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(32), nullable=False, index=True, unique=True)
    symbol = Column(String(32), nullable=False)
    action = Column(String(8), nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    size_usd = Column(Float, default=0.0)
    status = Column(String(16), nullable=False, default="pending")
    reasoning_summary = Column(Text, default="")
    sources = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    responded_at = Column(DateTime, nullable=True)
    responder = Column(String(32), nullable=True)
    rejection_reason = Column(Text, default="")

    def __repr__(self) -> str:
        return f"<Approval {self.symbol} {self.action} {self.status}>"
