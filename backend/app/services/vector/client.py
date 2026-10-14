"""
Vector Service — Qdrant vector database client.

Handles collection management, vector upsert, search with filtering,
and embedding consistency enforcement per the technical spec.
"""

from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import get_settings

logger = structlog.get_logger()


class VectorService:
    """Qdrant vector database client for semantic search."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = AsyncQdrantClient(
            host=self.settings.qdrant_host,
            port=self.settings.qdrant_port,
            api_key=self.settings.qdrant_api_key or None,
        )

    def collection_name(self, org_id: str, model_version: str = "v1") -> str:
        """Generate collection name: org_{org_id}_v_{model_version}."""
        return f"org_{org_id}_v_{model_version}"

    async def ensure_collection(
        self,
        org_id: str,
        dimensions: int | None = None,
        model_version: str = "v1",
    ) -> str:
        """Create a collection if it doesn't exist. Returns collection name."""
        name = self.collection_name(org_id, model_version)
        dims = dimensions or self.settings.embedding_dimensions

        if await self.client.collection_exists(name):
            collection_info = await self.client.get_collection(name)
            existing = collection_info.config.params.vectors
            existing_size = getattr(existing, "size", None)
            if existing_size is not None and existing_size != dims:
                raise ValueError(
                    f"Collection {name} has dimension {existing_size}, "
                    f"expected {dims}. Cannot mix embedding models."
                )
            return name

        try:
            await self.client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dims,
                    distance=models.Distance.COSINE,
                ),
            )
        except UnexpectedResponse as exc:
            # Another worker created it between our check and create (409).
            if exc.status_code != 409:
                raise
        else:
            # Keyword indexes keep the permission/version filters fast.
            for field in ("org_id", "document_id", "version_id"):
                await self.client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            logger.info("Created Qdrant collection", collection=name, dimensions=dims)

        return name

    async def upsert_vectors(
        self,
        collection_name: str,
        points: list[dict[str, Any]],
    ) -> None:
        """Upsert vectors into a collection.

        Each point dict should have: id, vector, payload
        payload should include: document_id, version_id, org_id, chunk_index,
                                text, metadata
        """
        qdrant_points = [
            models.PointStruct(
                id=point["id"],
                vector=point["vector"],
                payload=point["payload"],
            )
            for point in points
        ]

        await self.client.upsert(
            collection_name=collection_name,
            points=qdrant_points,
            wait=True,
        )
        logger.info(
            "Upserted vectors",
            collection=collection_name,
            count=len(points),
        )

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
        org_id: str | None = None,
        document_ids: list[str] | None = None,
        version_ids: list[str] | None = None,
        exclude_document_id: str | None = None,
        score_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors with optional filtering.

        Enforces organization-level tenant scoping and document/version-level
        access control. A collection that does not exist yet (no document has
        been indexed for the organization) simply yields no results.
        """
        if not await self.client.collection_exists(collection_name):
            return []

        filters = []

        if org_id:
            filters.append(
                models.FieldCondition(
                    key="org_id",
                    match=models.MatchValue(value=org_id),
                )
            )

        if document_ids:
            filters.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            )

        if version_ids:
            filters.append(
                models.FieldCondition(
                    key="version_id",
                    match=models.MatchAny(any=version_ids),
                )
            )

        must_not = []
        if exclude_document_id:
            must_not.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=exclude_document_id),
                )
            )

        query_filter = (
            models.Filter(must=filters or None, must_not=must_not or None)
            if filters or must_not
            else None
        )

        results = await self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            }
            for point in results.points
        ]

    async def scroll_version(
        self,
        collection_name: str,
        version_id: str,
        with_vectors: bool = False,
        limit: int = 256,
    ) -> list[dict[str, Any]]:
        """Return the points (chunks) stored for one document version."""
        if not await self.client.collection_exists(collection_name):
            return []
        points, _ = await self.client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="version_id", match=models.MatchValue(value=version_id)
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=with_vectors,
        )
        return [{"id": p.id, "payload": p.payload or {}, "vector": p.vector} for p in points]

    async def delete_by_version(
        self,
        collection_name: str,
        version_id: str,
    ) -> None:
        """Delete all vectors for a specific document version."""
        if not await self.client.collection_exists(collection_name):
            return
        await self.client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="version_id",
                            match=models.MatchValue(value=version_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        logger.info(
            "Deleted vectors for version",
            collection=collection_name,
            version_id=version_id,
        )

    async def delete_by_document(
        self,
        collection_name: str,
        document_id: str,
    ) -> None:
        """Delete all vectors for a document (all versions)."""
        if not await self.client.collection_exists(collection_name):
            return
        await self.client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
        logger.info(
            "Deleted vectors for document",
            collection=collection_name,
            document_id=document_id,
        )

    async def count(
        self,
        collection_name: str,
        org_id: str | None = None,
        document_id: str | None = None,
    ) -> int:
        """Count points in a collection, optionally filtered."""
        must = []
        if org_id:
            must.append(models.FieldCondition(key="org_id", match=models.MatchValue(value=org_id)))
        if document_id:
            must.append(
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))
            )
        query_filter = models.Filter(must=must) if must else None
        try:
            result = await self.client.count(
                collection_name=collection_name,
                count_filter=query_filter,
                exact=True,
            )
            return int(result.count)
        except UnexpectedResponse as exc:
            if exc.status_code == 404:
                return 0
            raise

    async def health_check(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            await self.client.get_collections()
            return True
        except Exception:
            return False


# Singleton
_vector_service: VectorService | None = None


def get_vector_service() -> VectorService:
    """Factory for vector service (lazy singleton)."""
    global _vector_service
    if _vector_service is None:
        _vector_service = VectorService()
    return _vector_service
