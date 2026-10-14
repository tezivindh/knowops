"""
Ingestion — Service layer.

Orchestrates the full document-processing pipeline for a version:

    extract -> chunk -> embed -> upsert into Qdrant -> flip to READY

The pipeline is idempotent: re-running for the same version replaces its
existing vectors rather than duplicating them, and only advances the
document's ``active_version_id`` after a fully successful run.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.config import get_settings
from app.modules.documents.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    ProcessingJob,
    VersionStatus,
)
from app.modules.ingestion.chunking import chunk_segments
from app.modules.ingestion.extractors import extract_segments
from app.modules.ingestion.models import VectorIndex
from app.services.embeddings.client import get_embedding_service
from app.services.storage.client import get_storage_service
from app.services.vector.client import get_vector_service

logger = structlog.get_logger()


class PermanentIngestionError(Exception):
    """A failure that retrying cannot fix (corrupt file, no text, ...)."""


_UPSERT_BATCH = 256


def _no_text_message(file_type: str) -> str:
    if file_type == "pdf":
        return (
            "No text could be found in this PDF. It may be a scanned or image-only file; "
            "upload a version with selectable text."
        )
    return "This file doesn't contain any text. Check that it isn't blank, then upload it again."


def _point_id(version_id: str, chunk_index: int) -> int:
    """Deterministic unsigned-64-bit Qdrant point id for a chunk."""
    digest = hashlib.blake2b(f"{version_id}:{chunk_index}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class IngestionService:
    """Processes an uploaded document version into the vector index."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()
        self.storage = get_storage_service()
        self.vectors = get_vector_service()
        self.embeddings = get_embedding_service()

    async def process_version(self, version_id: str) -> None:
        """Run the pipeline for a single document version."""
        version = await self.db.get(DocumentVersion, version_id)
        if version is None:
            logger.warning("Ingestion: version not found", version_id=version_id)
            return
        document = await self.db.get(Document, version.document_id)
        if document is None:
            logger.warning("Ingestion: document not found", version_id=version_id)
            return

        if version.status == VersionStatus.READY:
            return  # Acknowledgement loss must never delete a successfully indexed version.

        job = await self._get_job(version_id)
        org_id = document.organization_id
        # Plain ids: ORM instances are expired by the rollback in the error path.
        document_id = document.id

        try:
            self._begin(version, document, job)
            await self.db.commit()

            # 1. Fetch raw bytes from object storage
            file_data = await asyncio.to_thread(self.storage.download_file, version.object_key)

            # 2. Extract + 3. chunk
            version.status = VersionStatus.EXTRACTING
            await self.db.commit()
            try:
                segments = await asyncio.to_thread(extract_segments, file_data, document.file_type)
            except Exception as exc:
                raise PermanentIngestionError(
                    f"Could not read this {document.file_type.upper()} file. Check its format."
                ) from exc
            if not segments:
                raise PermanentIngestionError(_no_text_message(document.file_type))

            version.status = VersionStatus.CHUNKING
            await self.db.commit()
            chunks = chunk_segments(
                segments,
                chunk_size=self.settings.chunk_size_tokens,
                overlap=self.settings.chunk_overlap_tokens,
            )
            if not chunks:
                raise PermanentIngestionError("Document produced no text chunks")

            # 4. Embed
            version.status = VersionStatus.EMBEDDING
            await self.db.commit()
            vectors = await asyncio.to_thread(
                self.embeddings.embed_documents, [c.text for c in chunks]
            )

            # 5. Ensure collection + index
            version.status = VersionStatus.INDEXING
            await self.db.commit()
            collection = await self.vectors.ensure_collection(
                org_id,
                dimensions=self.embeddings.dimensions,
                model_version=self.embeddings.model_tag,
            )
            await self.vectors.delete_by_version(collection, version_id)

            points = [
                {
                    "id": _point_id(version_id, chunk.index),
                    "vector": vector,
                    "payload": {
                        "org_id": org_id,
                        "document_id": document.id,
                        "version_id": version_id,
                        "chunk_id": _point_id(version_id, chunk.index),
                        "chunk_index": chunk.index,
                        "text": chunk.text,
                        "page_number": chunk.page_number,
                        "section_heading": chunk.section_heading,
                        "file_type": document.file_type,
                    },
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            for start in range(0, len(points), _UPSERT_BATCH):
                await self.vectors.upsert_vectors(collection, points[start : start + _UPSERT_BATCH])

            # 6. Flip to READY and activate this version
            page_count = max((s.page_number for s in segments if s.page_number), default=None)
            # Refresh and lock at activation: archive/update may have happened during parsing.
            await self.db.refresh(document, with_for_update=True)
            active = (
                await self.db.get(DocumentVersion, document.active_version_id)
                if document.active_version_id
                else None
            )
            self._complete(
                version,
                document,
                job,
                page_count=page_count,
                activate=active is None or active.version_number < version.version_number,
            )
            await self._refresh_index_metadata(org_id, collection)
            await self.db.commit()

            logger.info(
                "Ingestion complete",
                version_id=version_id,
                document_id=document.id,
                chunks=len(chunks),
                collection=collection,
            )

        except Exception as exc:  # noqa: BLE001 — record failure then re-raise
            await self.db.rollback()
            await self._fail(
                version_id,
                document_id,
                str(exc)
                if isinstance(exc, PermanentIngestionError)
                else "Processing service unavailable. Retry processing later.",
            )
            await self.db.commit()
            logger.error(
                "Ingestion failed",
                version_id=version_id,
                document_id=document_id,
                error_type=type(exc).__name__,
            )
            raise

    # --- State transitions ---

    def _begin(
        self, version: DocumentVersion, document: Document, job: ProcessingJob | None
    ) -> None:
        version.status = VersionStatus.EXTRACTING
        version.error_message = None
        if document.status != DocumentStatus.ARCHIVED:
            document.status = DocumentStatus.PROCESSING
        if job is not None:
            job.status = "running"
            job.attempts += 1
            job.started_at = datetime.now(UTC)
            job.error_message = None

    def _complete(
        self,
        version: DocumentVersion,
        document: Document,
        job: ProcessingJob | None,
        page_count: int | None,
        activate: bool = True,
    ) -> None:
        version.status = VersionStatus.READY
        version.page_count = page_count
        version.error_message = None
        if activate:
            document.active_version_id = version.id
        if document.status != DocumentStatus.ARCHIVED:
            document.status = DocumentStatus.READY
        if job is not None:
            job.status = "completed"
            job.completed_at = datetime.now(UTC)

    async def _fail(self, version_id: str, document_id: str, message: str) -> None:
        version = await self.db.get(DocumentVersion, version_id)
        if version is not None:
            version.status = VersionStatus.FAILED
            version.error_message = message[:2000]
        document = await self.db.get(Document, document_id)
        if document is not None and document.status != DocumentStatus.ARCHIVED:
            # A failed upgrade leaves the previous active version serving, so
            # the document stays READY; it only fails if nothing is servable.
            document.status = (
                DocumentStatus.READY
                if document.active_version_id not in (None, version_id)
                else DocumentStatus.FAILED
            )
        job = await self._get_job(version_id)
        if job is not None:
            job.status = "failed"
            job.error_message = message[:2000]

    # --- Helpers ---

    async def _get_job(self, version_id: str) -> ProcessingJob | None:
        result = await self.db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.version_id == version_id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _refresh_index_metadata(self, org_id: str, collection: str) -> None:
        result = await self.db.execute(
            select(VectorIndex).where(
                VectorIndex.organization_id == org_id,
                VectorIndex.collection_name == collection,
            )
        )
        index = result.scalar_one_or_none()
        if index is None:
            index = VectorIndex(
                id=str(ULID()),
                organization_id=org_id,
                collection_name=collection,
                embedding_model=self.embeddings.model_name,
                embedding_dimensions=self.embeddings.dimensions,
            )
            self.db.add(index)

        index.embedding_model = self.embeddings.model_name
        index.embedding_dimensions = self.embeddings.dimensions
        index.chunk_count = await self.vectors.count(collection, org_id=org_id)
        doc_count = await self.db.execute(
            select(func.count(Document.id)).where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.READY,
            )
        )
        index.document_count = doc_count.scalar() or 0
        await self.db.flush()
