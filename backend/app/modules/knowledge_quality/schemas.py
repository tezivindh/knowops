"""
Knowledge quality module — Pydantic schemas.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class FindingResponse(BaseModel):
    id: str
    organization_id: str
    finding_type: str
    title: str
    description: str
    evidence: dict[str, Any]
    severity: str
    status: str
    related_documents: list[str]
    assigned_to: str | None
    assigned_to_name: str | None = None
    resolved_by: str | None
    resolution_notes: str | None
    detected_by: str | None
    created_at: datetime
    updated_at: datetime


class FindingUpdateRequest(BaseModel):
    status: Literal["open", "in_review", "resolved", "dismissed"] | None = None
    resolution_notes: str | None = Field(default=None, max_length=5000)
    # Empty string clears the assignee.
    assigned_to: str | None = Field(default=None, max_length=26)


class ScanStateResponse(BaseModel):
    status: Literal["idle", "queued", "running", "completed", "failed"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    summary: dict[str, Any] | None = None


class QualitySummaryResponse(BaseModel):
    open_by_type: dict[str, int]
    total_open: int
    resolved: int
    documents_ready: int
    documents_processing: int
    documents_failed: int
    indexed_chunks: int
    embedding_model: str
    scan: ScanStateResponse
