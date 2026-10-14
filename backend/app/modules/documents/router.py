"""
Documents module — API router.

Document CRUD, file upload, version management, and permission operations.
All endpoints require authentication and organization membership.
"""

import json
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from app.config import get_settings
from app.dependencies import DbSession
from app.modules.audit.models import AuditAction
from app.modules.audit.service import AuditService
from app.modules.documents.models import Document, DocumentVersion
from app.modules.documents.schemas import (
    DocumentAccessRequest,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentPermissionResponse,
    DocumentResponse,
    DocumentUpdateRequest,
    DocumentUploadResponse,
    DocumentVersionResponse,
    GrantPermissionRequest,
    RevokePermissionRequest,
    Tag,
    Title,
)
from app.modules.documents.service import CONTENT_TYPE_MAP, DocumentService
from app.modules.identity.models import User
from app.modules.identity.router import get_current_user
from app.modules.organizations.service import OrganizationService
from app.shared.utils import AppError, client_ip, request_id_of

router = APIRouter(prefix="/organizations/{org_id}/documents", tags=["documents"])

_TITLE = TypeAdapter(Title)
_TAGS = TypeAdapter(list[Tag])


async def get_doc_service(db: DbSession) -> DocumentService:
    return DocumentService(db)


async def get_org_service(db: DbSession) -> OrganizationService:
    return OrganizationService(db)


def _parse_tags(raw: str | None) -> list[str] | None:
    """Tags arrive as a JSON array string or a comma-separated list."""
    if not raw or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = [part for part in raw.split(",") if part.strip()]
    if not isinstance(value, list):
        raise AppError("Tags must be a list of strings", "INVALID_TAGS", 422)
    try:
        tags = _TAGS.validate_python(value)
    except ValidationError:
        raise AppError(
            "Each tag must be text of at most 50 characters", "INVALID_TAGS", 422
        ) from None
    if len(tags) > 20:
        raise AppError("At most 20 tags are allowed", "INVALID_TAGS", 422)
    # De-duplicate while preserving order.
    return list(dict.fromkeys(tags)) or None


async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload, refusing to buffer more than the configured limit."""
    settings = get_settings()
    limit = settings.max_upload_size_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(
            f"File exceeds the maximum size of {settings.max_upload_size_mb} MB",
            "FILE_TOO_LARGE",
            413,
        )
    return data


def _doc_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        organization_id=doc.organization_id,
        title=doc.title,
        description=doc.description,
        file_type=doc.file_type,
        original_filename=doc.original_filename,
        status=doc.status.value,
        category=doc.category,
        department=doc.department,
        tags=json.loads(doc.tags) if doc.tags else None,
        active_version_id=doc.active_version_id,
        owner_id=doc.owner_id,
        restricted=doc.restricted,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _version_response(v: DocumentVersion, active_id: str | None) -> DocumentVersionResponse:
    return DocumentVersionResponse(
        id=v.id,
        document_id=v.document_id,
        version_number=v.version_number,
        file_size_bytes=v.file_size_bytes,
        page_count=v.page_count,
        status=v.status.value,
        error_message=v.error_message,
        uploaded_by=v.uploaded_by,
        is_active=v.id == active_id,
        created_at=v.created_at,
    )


async def _audit(
    service: DocumentService,
    request: Request,
    action: AuditAction,
    actor_id: str,
    org_id: str,
    doc_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await AuditService(service.db).log_event(
        action=action,
        actor_id=actor_id,
        organization_id=org_id,
        resource_type="document",
        resource_id=doc_id,
        details=json.dumps(details) if details else None,
        ip_address=client_ip(request),
        request_id=request_id_of(request),
    )


# --- Upload ---


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    org_id: str,
    http_request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    description: str | None = Form(None),
    category: str | None = Form(None),
    department: str | None = Form(None),
    tags: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    org_service: OrganizationService = Depends(get_org_service),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentUploadResponse:
    """Upload a new document to the organization.

    ``title`` defaults to the file name without its extension.
    """
    await org_service.require_membership(current_user.id, org_id)

    filename = (file.filename or "").strip() or "untitled"
    raw_title = title if title and title.strip() else filename.rsplit(".", 1)[0]
    try:
        clean_title = _TITLE.validate_python(raw_title or filename)
    except ValidationError:
        raise AppError("Title must be 1–500 characters", "INVALID_TITLE", 422) from None
    parsed_tags = _parse_tags(tags)
    file_data = await _read_upload(file)

    document, version = await doc_service.upload_document(
        org_id=org_id,
        user_id=current_user.id,
        title=clean_title,
        filename=filename,
        file_data=file_data,
        description=(description or "").strip() or None,
        category=(category or "").strip()[:100] or None,
        department=(department or "").strip()[:100] or None,
        tags=parsed_tags,
    )
    await _audit(
        doc_service,
        http_request,
        AuditAction.DOCUMENT_UPLOADED,
        current_user.id,
        org_id,
        document.id,
        {"filename": filename, "size_bytes": len(file_data)},
    )
    # The upload committed mid-request (so the worker can see it); persist the
    # audit row too.
    await doc_service.db.commit()

    return DocumentUploadResponse(
        id=document.id,
        title=document.title,
        file_type=document.file_type,
        original_filename=document.original_filename,
        status=document.status.value,
        version_number=version.version_number,
        organization_id=document.organization_id,
        created_at=document.created_at,
    )


# --- List ---


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    org_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    department: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentListResponse:
    """List documents in the organization that the caller may view."""
    documents, total = await doc_service.list_documents(
        org_id=org_id,
        user_id=current_user.id,
        page=page,
        per_page=per_page,
        category=category,
        department=department,
        status_filter=status,
        search=search,
    )

    return DocumentListResponse(
        items=[_doc_response(doc) for doc in documents],
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, (total + per_page - 1) // per_page),
    )


# --- Get ---


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    org_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentDetailResponse:
    """Get document details, including the caller's effective permission."""
    doc = await doc_service.get_document(doc_id, org_id, current_user.id)
    db = doc_service.db

    owner_name = None
    if doc.owner_id:
        owner_name = (
            await db.execute(select(User.full_name).where(User.id == doc.owner_id))
        ).scalar_one_or_none()
    version_count = (
        await db.execute(
            select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == doc.id)
        )
    ).scalar() or 0
    latest = (
        await db.execute(
            select(DocumentVersion.status, DocumentVersion.error_message)
            .where(DocumentVersion.document_id == doc.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
    ).first()
    permission = await doc_service.effective_permission(current_user.id, doc)

    return DocumentDetailResponse(
        **_doc_response(doc).model_dump(),
        owner_name=owner_name,
        version_count=version_count,
        latest_version_status=latest[0].value if latest else None,
        latest_version_error=latest[1] if latest else None,
        my_permission=permission.value if permission else None,
    )


# --- Update ---


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    org_id: str,
    doc_id: str,
    request: DocumentUpdateRequest,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentResponse:
    """Update document metadata. Send ``null``/empty to clear optional fields."""
    doc = await doc_service.update_document(
        doc_id=doc_id,
        org_id=org_id,
        user_id=current_user.id,
        fields=request.model_dump(exclude_unset=True),
    )
    return _doc_response(doc)


# --- Archive / restore / retry ---


@router.delete("/{doc_id}", status_code=204)
async def archive_document(
    org_id: str,
    doc_id: str,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> None:
    """Archive (soft-delete) a document."""
    await doc_service.archive_document(doc_id, org_id, current_user.id)
    await _audit(
        doc_service,
        http_request,
        AuditAction.DOCUMENT_ARCHIVED,
        current_user.id,
        org_id,
        doc_id,
    )


@router.post("/{doc_id}/restore", response_model=DocumentResponse)
async def restore_document(
    org_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentResponse:
    """Restore an archived document."""
    doc = await doc_service.restore_document(doc_id, org_id, current_user.id)
    return _doc_response(doc)


@router.post("/{doc_id}/reprocess", response_model=DocumentVersionResponse)
async def reprocess_document(
    org_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentVersionResponse:
    """Retry processing the latest version after a failure."""
    version = await doc_service.retry_processing(doc_id, org_id, current_user.id)
    document = await doc_service.get_document(doc_id, org_id, current_user.id)
    return _version_response(version, document.active_version_id)


# --- Versions ---


@router.get("/{doc_id}/versions", response_model=list[DocumentVersionResponse])
async def list_versions(
    org_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> list[DocumentVersionResponse]:
    """List all versions of a document, newest first."""
    document, versions = await doc_service.list_versions(doc_id, org_id, current_user.id)
    return [_version_response(v, document.active_version_id) for v in versions]


@router.post(
    "/{doc_id}/versions",
    response_model=DocumentVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_new_version(
    org_id: str,
    doc_id: str,
    http_request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentVersionResponse:
    """Upload a new version of an existing document."""
    file_data = await _read_upload(file)
    version = await doc_service.upload_new_version(
        org_id=org_id,
        doc_id=doc_id,
        user_id=current_user.id,
        filename=(file.filename or "").strip() or "untitled",
        file_data=file_data,
    )
    await _audit(
        doc_service,
        http_request,
        AuditAction.VERSION_CREATED,
        current_user.id,
        org_id,
        doc_id,
        {"version_number": version.version_number},
    )
    await doc_service.db.commit()
    return _version_response(version, None)


# --- Download ---


@router.get("/{doc_id}/download")
async def download_document(
    org_id: str,
    doc_id: str,
    version_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> Response:
    """Stream the original file of a version (active version by default).

    Served through the API rather than a presigned object-store URL so the
    browser never needs network access to MinIO.
    """
    document, version, data = await doc_service.get_file(
        doc_id, org_id, current_user.id, version_id
    )
    stem = document.original_filename.rsplit(".", 1)[0] or "document"
    filename = f"{stem} (v{version.version_number}).{document.file_type}"
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'")
    return Response(
        content=data,
        media_type=CONTENT_TYPE_MAP.get(document.file_type, "application/octet-stream"),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "private, no-store",
        },
    )


# --- Permissions ---


@router.put("/{doc_id}/access", response_model=DocumentResponse)
async def set_document_access(
    org_id: str,
    doc_id: str,
    request: DocumentAccessRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentResponse:
    """Restrict a document to its grantees, or open it to the whole organization."""
    doc = await doc_service.set_restricted(doc_id, org_id, current_user.id, request.restricted)
    await _audit(
        doc_service,
        http_request,
        AuditAction.PERMISSION_REVOKED if request.restricted else AuditAction.PERMISSION_GRANTED,
        current_user.id,
        org_id,
        doc_id,
        {"restricted": request.restricted},
    )
    return _doc_response(doc)


@router.get("/{doc_id}/permissions", response_model=list[DocumentPermissionResponse])
async def list_permissions(
    org_id: str,
    doc_id: str,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> list[DocumentPermissionResponse]:
    """List explicit grants on a document. Empty means every member may view it."""
    perms = await doc_service.list_permissions(doc_id, org_id, current_user.id)
    return [DocumentPermissionResponse(**p) for p in perms]


@router.post(
    "/{doc_id}/permissions",
    response_model=DocumentPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_permission(
    org_id: str,
    doc_id: str,
    request: GrantPermissionRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> DocumentPermissionResponse:
    """Grant (or update) a permission on a document."""
    perm = await doc_service.grant_permission(
        doc_id=doc_id,
        org_id=org_id,
        granter_id=current_user.id,
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        permission=request.permission,
    )
    await _audit(
        doc_service,
        http_request,
        AuditAction.PERMISSION_GRANTED,
        current_user.id,
        org_id,
        doc_id,
        request.model_dump(),
    )
    perms = await doc_service.list_permissions(doc_id, org_id, current_user.id)
    return DocumentPermissionResponse(**next(p for p in perms if p["id"] == perm.id))


@router.delete("/{doc_id}/permissions", status_code=204)
async def revoke_permission(
    org_id: str,
    doc_id: str,
    http_request: Request,
    subject_type: str | None = Query(None),
    subject_id: str | None = Query(None),
    request: RevokePermissionRequest | None = Body(None),
    current_user: User = Depends(get_current_user),
    doc_service: DocumentService = Depends(get_doc_service),
) -> None:
    """Revoke a permission. The subject may be given as query params or a JSON body."""
    if request is None:
        if not subject_type or not subject_id:
            raise AppError("subject_type and subject_id are required", "VALIDATION_ERROR", 422)
        try:
            request = RevokePermissionRequest(subject_type=subject_type, subject_id=subject_id)
        except ValidationError:
            raise AppError(
                "subject_type must be 'user' or 'group'", "VALIDATION_ERROR", 422
            ) from None
    await doc_service.revoke_permission(
        doc_id=doc_id,
        org_id=org_id,
        revoker_id=current_user.id,
        subject_type=request.subject_type,
        subject_id=request.subject_id,
    )
    await _audit(
        doc_service,
        http_request,
        AuditAction.PERMISSION_REVOKED,
        current_user.id,
        org_id,
        doc_id,
        request.model_dump(),
    )
