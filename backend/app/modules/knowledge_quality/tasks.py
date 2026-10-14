"""
Knowledge quality — Celery tasks.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.config import get_settings
from app.database import async_session_factory, engine
from app.modules.knowledge_quality.service import KnowledgeQualityService
from app.services.queue.async_runner import run_async
from app.services.queue.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="knowledge.scan_organization")
def scan_organization(org_id: str) -> dict[str, Any]:
    """Run the stale + conflict scan for one organization.

    Not retried automatically: the scan records its own failure state, and a
    user can simply start another one.
    """

    async def _run() -> dict[str, Any]:
        try:
            async with async_session_factory() as session:
                return await KnowledgeQualityService(session).run_scan(org_id)
        finally:
            # Release database connections between tasks.
            await engine.dispose()

    return run_async(_run())


def enqueue_scan(org_id: str) -> bool:
    """Publish a scan job. Returns False if the broker is unreachable."""
    if get_settings().is_testing:
        return True
    try:
        scan_organization.delay(org_id)
        return True
    except Exception as exc:  # noqa: BLE001 — broker may be unavailable
        logger.warning("Could not enqueue knowledge scan", org_id=org_id, error=str(exc))
        return False
