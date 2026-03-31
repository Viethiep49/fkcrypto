"""Database repository — data access layer."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, desc, select
from sqlalchemy.orm import Session

from src.database.models import Base, SignalRecord, DecisionRecord, OrderRecord, PortfolioSnapshot, KillSwitchEvent


def create_engine_from_config(config: dict) -> "Engine":
    """Create SQLAlchemy engine from config dict."""
    db = config.get("database", {})
    host = db.get("host", "localhost")
    port = db.get("port", 5432)
    name = db.get("name", "fkcrypto")
    user = db.get("user", "fkcrypto")
    password = db.get("password", "")
    url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    return create_engine(url, echo=False)


class Repository:
    """Data access layer for all database operations."""

    def __init__(self, session: Session):
        self.session = session

    # --- Signals ---

    def save_signal(self, signal: SignalRecord) -> None:
        self.session.add(signal)
        self.session.commit()

    def get_signals(
        self,
        symbol: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> list[SignalRecord]:
        query = select(SignalRecord).order_by(desc(SignalRecord.timestamp)).limit(limit)
        if symbol:
            query = query.where(SignalRecord.symbol == symbol)
        if source:
            query = query.where(SignalRecord.source == source)
        return list(self.session.execute(query).scalars().all())

    # --- Decisions ---

    def save_decision(self, decision: DecisionRecord) -> None:
        self.session.add(decision)
        self.session.commit()

    def get_decisions(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
    ) -> list[DecisionRecord]:
        query = select(DecisionRecord).order_by(desc(DecisionRecord.timestamp)).limit(limit)
        if symbol:
            query = query.where(DecisionRecord.symbol == symbol)
        return list(self.session.execute(query).scalars().all())

    # --- Orders ---

    def save_order(self, order: OrderRecord) -> None:
        self.session.add(order)
        self.session.commit()

    def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[OrderRecord]:
        query = select(OrderRecord).order_by(desc(OrderRecord.timestamp)).limit(limit)
        if symbol:
            query = query.where(OrderRecord.symbol == symbol)
        if status:
            query = query.where(OrderRecord.status == status)
        return list(self.session.execute(query).scalars().all())

    # --- Portfolio ---

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self.session.add(snapshot)
        self.session.commit()

    def get_latest_snapshot(self) -> Optional[PortfolioSnapshot]:
        query = select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.timestamp)).limit(1)
        return self.session.execute(query).scalar_one_or_none()

    # --- Kill Switch ---

    def save_kill_switch(self, event: KillSwitchEvent) -> None:
        self.session.add(event)
        self.session.commit()

    def is_kill_switch_active(self) -> bool:
        query = select(KillSwitchEvent).where(KillSwitchEvent.active == True).limit(1)
        return self.session.execute(query).scalar_one_or_none() is not None

    def deactivate_kill_switch(self, reset_by: str = "manual") -> None:
        query = select(KillSwitchEvent).where(KillSwitchEvent.active == True)
        events = self.session.execute(query).scalars().all()
        for event in events:
            event.active = False
            event.reset_at = datetime.now()
            event.reset_by = reset_by
        self.session.commit()
