"""Embeddings service package."""

from app.services.embeddings.client import EmbeddingService, get_embedding_service

__all__ = ["EmbeddingService", "get_embedding_service"]
