"""
Knowledge quality module — API router.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.dependencies import DbSession
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.modules.knowledge_quality.models import KnowledgeFinding
from app.modules.knowledge_quality.schemas import (
    FindingResponse,
    FindingUpdateRequest,
    QualitySummaryResponse,
    ScanStateResponse,
)
from app.modules.knowledge_quality.service import KnowledgeQualityService

router = APIRouter(prefix="/organizations/{org_id}/knowledge", tags=["knowledge quality"])


async def get_service(db: DbSession) -> KnowledgeQualityService:
    return KnowledgeQualityService(db)


def _finding_response(f: KnowledgeFinding, assignee_name: str | None) -> FindingResponse:
    try:
        evidence = json.loads(f.evidence) if f.evidence else {}
    except ValueError:
        evidence = {}
    try:
        related = json.loads(f.related_documents) if f.related_documents else []
    except ValueError:
        related = []
    return FindingResponse(
        id=f.id,
        organization_id=f.organization_id,
        finding_type=f.finding_type.value,
        title=f.title,
        description=f.description,
        evidence=evidence if isinstance(evidence, dict) else {},
        severity=f.severity.value,
        status=f.status.value,
        related_documents=related if isinstance(related, list) else [],
        assigned_to=f.assigned_to,
        assigned_to_name=assignee_name,
        resolved_by=f.resolved_by,
        resolution_notes=f.resolution_notes,
        detected_by=f.detected_by,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


@router.get("/summary", response_model=QualitySummaryResponse)
async def quality_summary(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: KnowledgeQualityService = Depends(get_service),
) -> dict[str, Any]:
    """Open findings by type, document processing counts, and scan state."""
    return await service.summary(org_id, current_user.id)


@router.get("/findings", response_model=list[FindingResponse])
async def list_findings(
    org_id: str,
    finding_type: str | None = Query(None, alias="type"),
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    service: KnowledgeQualityService = Depends(get_service),
) -> list[FindingResponse]:
    """List findings visible to the caller, most recently updated first."""
    rows = await service.list_findings(org_id, current_user.id, finding_type, status)
    return [_finding_response(f, name) for f, name in rows]


@router.patch("/findings/{finding_id}", response_model=FindingResponse)
async def update_finding(
    org_id: str,
    finding_id: str,
    request: FindingUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: KnowledgeQualityService = Depends(get_service),
) -> FindingResponse:
    """Change a finding's status, notes, or assignee."""
    finding = await service.update_finding(
        org_id, current_user.id, finding_id, request.model_dump(exclude_unset=True)
    )
    name = None
    if finding.assigned_to:
        assignee = await service.db.get(User, finding.assigned_to)
        name = assignee.full_name if assignee else None
    return _finding_response(finding, name)


@router.get("/scan", response_model=ScanStateResponse)
async def scan_state(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: KnowledgeQualityService = Depends(get_service),
) -> dict[str, Any]:
    """State of the most recent knowledge scan."""
    from app.modules.organizations.service import OrganizationService

    await OrganizationService(service.db).require_membership(current_user.id, org_id)
    return await service.get_scan_state(org_id)


@router.post("/scan", response_model=ScanStateResponse, status_code=202)
async def start_scan(
    org_id: str,
    current_user: User = Depends(get_current_user),
    service: KnowledgeQualityService = Depends(get_service),
) -> dict[str, Any]:
    """Queue a scan for stale documents and conflicting passages."""
    return await service.request_scan(org_id, current_user.id)
