"""Tests for knowledge graph."""

from __future__ import annotations

import pytest

from src.agents.knowledge_graph import Entity, KnowledgeGraph, Relationship


class TestKnowledgeGraph:
    """Test knowledge graph for crypto entities."""

    def test_add_and_get_entity(self) -> None:
        kg = KnowledgeGraph()
        entity = Entity(
            id="btc",
            entity_type="token",
            name="Bitcoin",
            properties={"symbol": "BTC", "market_cap": 1000000},
        )
        kg.add_entity(entity)

        found = kg.get_entity("btc")
        assert found is not None
        assert found.name == "Bitcoin"
        assert found.properties["symbol"] == "BTC"

    def test_add_relationship(self) -> None:
        kg = KnowledgeGraph()
        kg.add_entity(Entity(id="btc", entity_type="token", name="Bitcoin"))
        kg.add_entity(Entity(id="binance", entity_type="exchange", name="Binance"))

        rel = Relationship(
            from_id="btc",
            to_id="binance",
            relation_type="listed_on",
            weight=1.0,
        )
        kg.add_relationship(rel)

        related = kg.get_related("btc", relation_type="listed_on")
        assert len(related) == 1
        assert related[0][0].name == "Binance"

    def test_search_entities(self) -> None:
        kg = KnowledgeGraph()
        kg.add_entity(Entity(id="btc", entity_type="token", name="Bitcoin"))
        kg.add_entity(Entity(id="eth", entity_type="token", name="Ethereum"))
        kg.add_entity(Entity(id="sol", entity_type="token", name="Solana"))

        results = kg.search_entities("Bitcoin")
        assert len(results) >= 1
        assert results[0].name == "Bitcoin"

    def test_get_related_bidirectional(self) -> None:
        kg = KnowledgeGraph()
        kg.add_entity(Entity(id="btc", entity_type="token", name="Bitcoin"))
        kg.add_entity(Entity(id="eth", entity_type="token", name="Ethereum"))
        kg.add_entity(Entity(id="defi", entity_type="sector", name="DeFi"))

        kg.add_relationship(Relationship(
            from_id="btc", to_id="defi", relation_type="belongs_to",
        ))
        kg.add_relationship(Relationship(
            from_id="eth", to_id="defi", relation_type="belongs_to",
        ))

        # Get entities in defi sector
        related = kg.get_related("defi", direction="inbound")
        assert len(related) == 2

    def test_get_stats(self) -> None:
        kg = KnowledgeGraph()
        kg.add_entity(Entity(id="btc", entity_type="token", name="Bitcoin"))
        kg.add_entity(Entity(id="eth", entity_type="token", name="Ethereum"))

        stats = kg.get_stats()
        assert stats["total_entities"] == 2
        assert stats["entity_types"]["token"] == 2

    def test_close(self) -> None:
        kg = KnowledgeGraph()
        kg.close()
        # Should not raise
