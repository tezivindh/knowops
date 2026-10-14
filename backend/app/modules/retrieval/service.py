"""
Retrieval — Service layer.

Semantic search over an organization's vector index with document-level
permission enforcement. Returns focused passages with source metadata so the
conversation layer can build grounded, citable answers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.documents.service import searchable_versions
from app.services.embeddings.client import get_embedding_service
from app.services.vector.client import get_vector_service

logger = structlog.get_logger()


@dataclass
class RetrievedChunk:
    """A retrieved passage and its provenance."""

    document_id: str
    version_id: str
    chunk_id: str
    text: str
    score: float
    chunk_index: int
    page_number: int | None = None
    section_heading: str | None = None
    file_type: str | None = None


class RetrievalService:
    """Permission-scoped semantic retrieval."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()
        self.vectors = get_vector_service()
        self.embeddings = get_embedding_service()

    async def search(
        self,
        org_id: str,
        user_id: str,
        query: str,
        limit: int | None = None,
        document_ids: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Semantic search constrained to documents the user may view."""
        query = query.strip()
        if not query:
            return []

        versions = await searchable_versions(self.db, user_id, org_id, document_ids=document_ids)
        if not versions:
            return []

        collection = self.vectors.collection_name(org_id, self.embeddings.model_tag)
        query_vector = await asyncio.to_thread(self.embeddings.embed_query, query)

        results = await self.vectors.search(
            collection,
            query_vector,
            limit=limit or self.settings.retrieval_top_k,
            org_id=org_id,
            version_ids=list(versions.values()),
            score_threshold=(
                self.settings.retrieval_score_threshold
                if score_threshold is None
                else score_threshold
            ),
        )

        chunks = [self._to_chunk(hit) for hit in results]
        logger.info(
            "Retrieval executed",
            org_id=org_id,
            hits=len(chunks),
            collection=collection,
        )
        return chunks

    @staticmethod
    def _to_chunk(hit: dict[str, Any]) -> RetrievedChunk:
        payload = hit.get("payload") or {}
        return RetrievedChunk(
            document_id=str(payload.get("document_id", "")),
            version_id=str(payload.get("version_id", "")),
            chunk_id=str(payload.get("chunk_id", hit.get("id", ""))),
            text=str(payload.get("text", "")),
            score=float(hit.get("score", 0.0)),
            chunk_index=int(payload.get("chunk_index", 0)),
            page_number=payload.get("page_number"),
            section_heading=payload.get("section_heading"),
            file_type=payload.get("file_type"),
        )
