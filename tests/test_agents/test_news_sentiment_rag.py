"""Tests for NewsSentimentAgent RAG system."""

import pytest
from src.data.vector_db import InMemoryNewsDB


def test_in_memory_news_db():
    db = InMemoryNewsDB()
    
    # Add historical events
    db.add_news("Bitcoin ETF approved by SEC, causing a massive surge", {"sentiment": 0.9})
    db.add_news("Major exchange hacked, millions stolen", {"sentiment": -0.9})
    db.add_news("Federal Reserve raises interest rates", {"sentiment": -0.6})
    
    # Test 1: Similar to ETF
    results = db.search_similar("SEC approves spot Bitcoin ETF", k=1)
    assert len(results) == 1
    assert "Bitcoin ETF" in results[0]["text"]
    assert results[0]["metadata"]["sentiment"] == 0.9
    
    # Test 2: Similar to Hack
    results = db.search_similar("Hackers drain major exchange", k=1)
    assert len(results) == 1
    assert "hacked" in results[0]["text"]
    assert results[0]["metadata"]["sentiment"] == -0.9

    # Test 3: No match
    results = db.search_similar("Pizza recipe with pineapple", k=1, threshold=0.5)
    assert len(results) == 0

    # Test 4: Deduplication
    db.add_news("Federal Reserve raises interest rates", {"sentiment": -0.6})
    assert len(db.documents) == 3  # Should still be 3, exact duplicate ignored
