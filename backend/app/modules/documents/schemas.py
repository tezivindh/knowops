"""
Documents module — Pydantic schemas.

Request/response models for document CRUD, upload, and permission management.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]

# --- Document ---

class DocumentUploadResponse(BaseModel):
    id: str
    title: str
    file_type: str
    original_filename: str
    status: str
    version_number: int
    organization_id: str
    created_at: datetime


class DocumentResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: str | None
    file_type: str
    original_filename: str
    status: str
    category: str | None
    department: str | None
    tags: list[str] | None = None
    active_version_id: str | None
    owner_id: str | None
    # Visible only to the owner, admins, and explicit grantees.
    restricted: bool = False
    created_at: datetime
    updated_at: datetime


class DocumentDetailResponse(DocumentResponse):
    owner_name: str | None = None
    version_count: int = 0
    latest_version_status: str | None = None
    latest_version_error: str | None = None
    # The caller's effective permission: "view", "edit" or "manage".
    my_permission: str | None = None


class DocumentUpdateRequest(BaseModel):
    title: Title | None = None
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    tags: list[Tag] | None = Field(default=None, max_length=20)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    per_page: int
    pages: int


# --- Document Version ---

class DocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    version_number: int
    file_size_bytes: int
    page_count: int | None
    status: str
    error_message: str | None
    uploaded_by: str | None
    is_active: bool = False
    created_at: datetime


# --- Document Permission ---

class GrantPermissionRequest(BaseModel):
    subject_type: Literal["user", "group"]
    subject_id: str = Field(min_length=1, max_length=26)
    permission: Literal["view", "edit", "manage"]


class DocumentPermissionResponse(BaseModel):
    id: str
    document_id: str
    subject_type: str
    subject_id: str
    subject_name: str | None = None
    permission: str
    granted_by: str | None
    created_at: datetime


class DocumentAccessRequest(BaseModel):
    restricted: bool


class RevokePermissionRequest(BaseModel):
    subject_type: Literal["user", "group"]
    subject_id: str = Field(min_length=1, max_length=26)
