"""Knowledge Graph — entity relationships for crypto trading context.

Inspired by GoClaw's knowledge graph. Stores relationships between:
- Tokens and their properties (market cap, sector, chain)
- Exchanges and their listings
- Events and their affected tokens
- Agents and their analysis history

Uses SQLite FTS5 for text search + graph traversal for relationship queries.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class Entity:
    """A node in the knowledge graph."""

    id: str
    entity_type: str  # token, exchange, event, agent, indicator
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "name": self.name,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Relationship:
    """An edge between two entities."""

    from_id: str
    to_id: str
    relation_type: str  # listed_on, affected_by, analyzed_by, correlates_with
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "metadata": self.metadata,
        }


class KnowledgeGraph:
    """SQLite-backed knowledge graph for crypto entities.

    Features:
    - Entity storage with typed properties
    - Relationship tracking with weights
    - FTS5 text search across entity names and properties
    - Graph traversal for relationship queries
    - Persistence to SQLite database
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialize the knowledge graph.

        Args:
            db_path: Path to SQLite database (or :memory: for in-memory).
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create database schema."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS relationships (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                PRIMARY KEY (from_id, to_id, relation_type),
                FOREIGN KEY (from_id) REFERENCES entities(id),
                FOREIGN KEY (to_id) REFERENCES entities(id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS entity_search
                USING fts5(id, name, entity_type, properties);

            CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_relation_type ON relationships(relation_type);
            CREATE INDEX IF NOT EXISTS idx_from_id ON relationships(from_id);
            CREATE INDEX IF NOT EXISTS idx_to_id ON relationships(to_id);
        """)
        self._conn.commit()

    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph.

        Args:
            entity: Entity to add.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO entities (id, entity_type, name, properties, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                entity.id,
                entity.entity_type,
                entity.name,
                json.dumps(entity.properties),
                entity.created_at.isoformat(),
            ),
        )
        # Update FTS index
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_search (id, name, entity_type, properties) VALUES (?, ?, ?, ?)",
            (
                entity.id,
                entity.name,
                entity.entity_type,
                json.dumps(entity.properties),
            ),
        )
        self._conn.commit()

    def add_relationship(self, rel: Relationship) -> None:
        """Add a relationship between two entities.

        Args:
            rel: Relationship to add.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO relationships (from_id, to_id, relation_type, weight, metadata) VALUES (?, ?, ?, ?, ?)",
            (
                rel.from_id,
                rel.to_id,
                rel.relation_type,
                rel.weight,
                json.dumps(rel.metadata),
            ),
        )
        self._conn.commit()

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID.

        Args:
            entity_id: Entity ID.

        Returns:
            Entity or None if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            return None
        return Entity(
            id=row["id"],
            entity_type=row["entity_type"],
            name=row["name"],
            properties=json.loads(row["properties"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def search_entities(self, query: str, limit: int = 10) -> list[Entity]:
        """Search entities using FTS5 full-text search.

        Args:
            query: Search query.
            limit: Max results.

        Returns:
            Matching entities.
        """
        rows = self._conn.execute(
            """
            SELECT e.* FROM entity_search es
            JOIN entities e ON e.id = es.id
            WHERE entity_search MATCH ?
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()

        return [
            Entity(
                id=row["id"],
                entity_type=row["entity_type"],
                name=row["name"],
                properties=json.loads(row["properties"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def get_related(
        self,
        entity_id: str,
        relation_type: str = "",
        direction: str = "outbound",
    ) -> list[tuple[Entity, Relationship]]:
        """Get entities related to a given entity.

        Args:
            entity_id: Source entity ID.
            relation_type: Filter by relation type (empty = all).
            direction: "outbound", "inbound", or "both".

        Returns:
            List of (related_entity, relationship) tuples.
        """
        results: list[tuple[Entity, Relationship]] = []

        if direction in ("outbound", "both"):
            query = "SELECT r.*, e.* FROM relationships r JOIN entities e ON e.id = r.to_id WHERE r.from_id = ?"
            params: list[Any] = [entity_id]
            if relation_type:
                query += " AND r.relation_type = ?"
                params.append(relation_type)

            for row in self._conn.execute(query, params).fetchall():
                entity = Entity(
                    id=row["id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    properties=json.loads(row["properties"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                rel = Relationship(
                    from_id=row["from_id"],
                    to_id=row["to_id"],
                    relation_type=row["relation_type"],
                    weight=row["weight"],
                    metadata=json.loads(row["metadata"]),
                )
                results.append((entity, rel))

        if direction in ("inbound", "both"):
            query = "SELECT r.*, e.* FROM relationships r JOIN entities e ON e.id = r.from_id WHERE r.to_id = ?"
            params = [entity_id]
            if relation_type:
                query += " AND r.relation_type = ?"
                params.append(relation_type)

            for row in self._conn.execute(query, params).fetchall():
                entity = Entity(
                    id=row["id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    properties=json.loads(row["properties"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                rel = Relationship(
                    from_id=row["from_id"],
                    to_id=row["to_id"],
                    relation_type=row["relation_type"],
                    weight=row["weight"],
                    metadata=json.loads(row["metadata"]),
                )
                results.append((entity, rel))

        return results

    def get_stats(self) -> dict[str, Any]:
        """Get graph statistics."""
        entity_count = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relation_count = self._conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]

        entity_types = {}
        for row in self._conn.execute(
            "SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type"
        ).fetchall():
            entity_types[row["entity_type"]] = row["cnt"]

        return {
            "total_entities": entity_count,
            "total_relationships": relation_count,
            "entity_types": entity_types,
        }

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
