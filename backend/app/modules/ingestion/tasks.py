"""
Ingestion — Celery tasks.

Runs the synchronous Celery task around the async ingestion pipeline and
provides a fire-and-forget enqueue helper used by the documents API.
"""

from __future__ import annotations

from typing import Any

import structlog
from celery import Task
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import engine
from app.modules.documents.models import DocumentVersion
from app.modules.ingestion.service import IngestionService, PermanentIngestionError
from app.services.queue.async_runner import run_async
from app.services.queue.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(
    name="ingestion.process_document_version",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_document_version(self: Task[Any, Any], version_id: str) -> str:
    """Process a single document version into the vector index."""

    async def _run() -> None:
        try:
            # Keep the advisory lock on a dedicated connection across pipeline commits.
            # Serialize all versions of one document, including duplicate deliveries.
            async with engine.connect() as connection:
                document_id = (
                    await connection.execute(
                        select(DocumentVersion.document_id).where(DocumentVersion.id == version_id)
                    )
                ).scalar_one_or_none()
                if document_id is None:
                    return
                await connection.execute(
                    text("SELECT pg_advisory_lock(hashtextextended(:id, 0))"), {"id": document_id}
                )
                await connection.commit()
                try:
                    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                        await IngestionService(session).process_version(version_id)
                finally:
                    await connection.rollback()
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:id, 0))"),
                        {"id": document_id},
                    )
                    await connection.commit()
        finally:
            # Release database connections after each task; async service clients
            # keep using the worker's persistent event loop.
            await engine.dispose()

    try:
        run_async(_run())
        return f"processed:{version_id}"
    except PermanentIngestionError as exc:
        # Already recorded on the version; retrying would fail the same way.
        logger.warning("Ingestion failed permanently", version_id=version_id, error=str(exc))
        return f"failed:{version_id}"
    except Exception as exc:  # noqa: BLE001 — retry with backoff
        logger.error(
            "Ingestion task failed",
            version_id=version_id,
            attempts=self.request.retries + 1,
            error_type=type(exc).__name__,
        )
        raise self.retry(exc=exc) from exc


def enqueue_version_processing(version_id: str) -> bool:
    """Publish a job; the caller persists broker failures for explicit retry."""
    if get_settings().is_testing:
        return True
    try:
        process_document_version.delay(version_id)
        return True
    except Exception as exc:  # noqa: BLE001 — broker may be unavailable
        logger.warning(
            "Could not enqueue ingestion task",
            version_id=version_id,
            error_type=type(exc).__name__,
        )
        return False
