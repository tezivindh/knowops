"""Recover durable uploads whose broker publication was interrupted.

Run as a separate process: python -m app.services.queue.reconcile.
Duplicate deliveries are safe: ingestion locks the document and skips ready versions.
"""

import asyncio
from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.modules.documents.models import DocumentVersion, ProcessingJob, VersionStatus
from app.modules.ingestion.tasks import enqueue_version_processing
from app.shared.utils import utcnow

logger = structlog.get_logger()


async def recover_pending_uploads(session: AsyncSession) -> int:
    jobs = await session.scalars(
        select(ProcessingJob)
        .join(DocumentVersion, DocumentVersion.id == ProcessingJob.version_id)
        .where(
            ProcessingJob.status == "queued",
            ProcessingJob.started_at.is_(None),
            ProcessingJob.created_at < utcnow() - timedelta(seconds=60),
            DocumentVersion.status != VersionStatus.READY,
        )
        .order_by(ProcessingJob.created_at)
        .limit(100)
        .with_for_update(of=ProcessingJob, skip_locked=True)
    )
    recovered = 0
    for job in jobs:
        if not await asyncio.to_thread(enqueue_version_processing, job.version_id):
            break  # Retry on the next pass; leave the durable record intact.
        recovered += 1
    return recovered


async def main() -> None:
    while True:
        try:
            async with async_session_factory() as session:
                recovered = await recover_pending_uploads(session)
                await session.commit()
                if recovered:
                    logger.info("Republished pending uploads", count=recovered)
        except Exception:
            logger.exception("Upload recovery failed; will retry")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
