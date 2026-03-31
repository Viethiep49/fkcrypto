"""Database migration script for FKCrypto v2.0 features.

Adds new columns and tables for:
- Explainable AI (reasoning_json, reasoning_summary)
- Human-in-the-loop (approval_requests table)

Usage:
    python scripts/migrate_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import structlog

logger = structlog.get_logger()

MIGRATIONS = [
    # v2.0: Add reasoning columns to signals table
    """
    ALTER TABLE signals ADD COLUMN reasoning_json TEXT DEFAULT '{}';
    """,
    """
    ALTER TABLE signals ADD COLUMN reasoning_summary TEXT DEFAULT '';
    """,
    # v2.0: Approval requests table
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id VARCHAR(32) NOT NULL UNIQUE,
        symbol VARCHAR(32) NOT NULL,
        action VARCHAR(8) NOT NULL,
        score FLOAT NOT NULL,
        confidence FLOAT NOT NULL,
        size_usd FLOAT DEFAULT 0.0,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        reasoning_summary TEXT DEFAULT '',
        sources TEXT DEFAULT '',
        created_at DATETIME NOT NULL,
        responded_at DATETIME,
        responder VARCHAR(32),
        rejection_reason TEXT DEFAULT ''
    );
    """,
]


def run_migrations(db_url: str) -> None:
    """Run all pending database migrations.

    Args:
        db_url: SQLAlchemy database URL.
    """
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(db_url)

    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        # Check if signals table exists
        if "signals" not in existing_tables:
            logger.warning("signals_table_not_found", url=db_url)
            return

        # Check existing columns
        columns = [col["name"] for col in inspector.get_columns("signals")]

        for migration_sql in MIGRATIONS:
            sql = migration_sql.strip()
            if not sql:
                continue

            # Skip if column already exists
            if "ADD COLUMN reasoning_json" in sql and "reasoning_json" in columns:
                logger.info("migration_skipped", reason="reasoning_json already exists")
                continue
            if "ADD COLUMN reasoning_summary" in sql and "reasoning_summary" in columns:
                logger.info("migration_skipped", reason="reasoning_summary already exists")
                continue

            try:
                conn.execute(text(sql))
                conn.commit()
                logger.info("migration_applied", sql=sql[:80])
            except Exception as exc:
                # Column already exists or table exists — skip gracefully
                if "duplicate" in str(exc).lower() or "already exists" in str(exc).lower():
                    logger.info("migration_already_applied", sql=sql[:80])
                else:
                    logger.error("migration_failed", sql=sql[:80], error=str(exc))
                    raise

    logger.info("migrations_complete")


def main() -> None:
    """Run migrations from command line."""
    db_url = sys.argv[1] if len(sys.argv) > 1 else "sqlite:///fkcrypto.db"
    logger.info("starting_migrations", db_url=db_url)
    run_migrations(db_url)
    logger.info("done")


if __name__ == "__main__":
    main()
