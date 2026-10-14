"""
Versioning — API router.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies import DbSession
from app.modules.documents.models import DocumentVersion
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.modules.versioning.service import Comparison, VersioningService

router = APIRouter(prefix="/organizations/{org_id}/documents/{doc_id}/compare", tags=["versioning"])


class VersionRef(BaseModel):
    id: str
    version_number: int
    created_at: datetime


class DiffLineResponse(BaseModel):
    kind: str
    text: str
    base_line: int | None
    target_line: int | None


class HunkResponse(BaseModel):
    base_start: int
    target_start: int
    lines: list[DiffLineResponse]


class ComparisonResponse(BaseModel):
    document_id: str
    base: VersionRef
    target: VersionRef
    added: int
    removed: int
    unchanged: int
    truncated: bool
    hunks: list[HunkResponse]


class SummaryResponse(BaseModel):
    base: VersionRef
    target: VersionRef
    summary: str


async def get_service(db: DbSession) -> VersioningService:
    return VersioningService(db)


def _ref(version: DocumentVersion) -> VersionRef:
    return VersionRef(
        id=version.id, version_number=version.version_number, created_at=version.created_at
    )


def _response(c: Comparison) -> ComparisonResponse:
    return ComparisonResponse(
        document_id=c.document.id,
        base=_ref(c.base),
        target=_ref(c.target),
        added=c.added,
        removed=c.removed,
        unchanged=c.unchanged,
        truncated=c.truncated,
        hunks=[
            HunkResponse(
                base_start=h.base_start,
                target_start=h.target_start,
                lines=[DiffLineResponse(**vars(line)) for line in h.lines],
            )
            for h in c.hunks
        ],
    )


@router.get("", response_model=ComparisonResponse)
async def compare_versions(
    org_id: str,
    doc_id: str,
    base: str | None = Query(None, description="Older version id (default: previous)"),
    target: str | None = Query(None, description="Newer version id (default: latest)"),
    current_user: User = Depends(get_current_user),
    service: VersioningService = Depends(get_service),
) -> ComparisonResponse:
    """Line-level diff of the extracted text of two versions."""
    comparison = await service.compare(org_id, doc_id, current_user.id, base, target)
    return _response(comparison)


@router.post("/summary", response_model=SummaryResponse)
async def summarize_changes(
    org_id: str,
    doc_id: str,
    base: str | None = Query(None),
    target: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    service: VersioningService = Depends(get_service),
) -> SummaryResponse:
    """AI summary of the substantive changes between two versions."""
    comparison = await service.compare(org_id, doc_id, current_user.id, base, target)
    summary = await service.summarize(comparison)
    return SummaryResponse(
        base=_ref(comparison.base), target=_ref(comparison.target), summary=summary
    )
