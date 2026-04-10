"""Simple in-memory Vector DB mockup for RAG (Retrieval-Augmented Generation)."""

import math
from collections import Counter
from typing import Any
import structlog

logger = structlog.get_logger()

class InMemoryNewsDB:
    """A lightweight, zero-dependency vector database simulation.
    
    Uses TF-IDF/Cosine Similarity logic for text retrieval without 
    requiring heavy ML libraries, perfect for low-RAM environments.
    """
    
    def __init__(self):
        self.documents: list[dict[str, Any]] = []
    
    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenizer."""
        return text.lower().replace(".", "").replace(",", "").replace(":", "").split()
    
    def _cosine_similarity(self, text1: str, text2: str) -> float:
        """Calculate cosine similarity between two texts using word frequencies."""
        vec1 = Counter(self._tokenize(text1))
        vec2 = Counter(self._tokenize(text2))
        
        intersection = set(vec1.keys()) & set(vec2.keys())
        numerator = sum([vec1[x] * vec2[x] for x in intersection])
        
        sum1 = sum([vec1[x]**2 for x in vec1.keys()])
        sum2 = sum([vec2[x]**2 for x in vec2.keys()])
        denominator = math.sqrt(sum1) * math.sqrt(sum2)
        
        if not denominator:
            return 0.0
        return float(numerator) / denominator

    def add_news(self, text: str, metadata: dict[str, Any]) -> None:
        """Add a news item to the vector store."""
        # Avoid exact duplicates to save memory
        if any(doc["text"] == text for doc in self.documents):
            return
            
        self.documents.append({"text": text, "metadata": metadata})
        
        # Keep memory bounded (max 5000 items)
        if len(self.documents) > 5000:
            self.documents = self.documents[-5000:]

    def search_similar(self, query: str, k: int = 3, threshold: float = 0.1) -> list[dict[str, Any]]:
        """Search for top-k similar documents to the query."""
        if not query or not self.documents:
            return []
            
        results = []
        for doc in self.documents:
            score = self._cosine_similarity(query, doc["text"])
            if score >= threshold:
                results.append({
                    "text": doc["text"], 
                    "metadata": doc["metadata"], 
                    "score": score
                })
        
        # Sort by highest score first
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]
