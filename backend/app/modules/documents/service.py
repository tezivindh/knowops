"""
Documents module — Service layer.

Document CRUD, file upload with version creation, permission management,
and lifecycle operations (archive, restore). All operations enforce
tenant scoping and permission checks.
"""

import asyncio
import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from ulid import ULID

from app.config import get_settings
from app.modules.documents.models import (
    Document,
    DocumentPermission,
    DocumentStatus,
    DocumentVersion,
    PermissionLevel,
    ProcessingJob,
    SubjectType,
    VersionStatus,
)
from app.modules.identity.models import User
from app.modules.ingestion.tasks import enqueue_version_processing
from app.modules.organizations.models import (
    Group,
    GroupMembership,
    Membership,
    MembershipStatus,
    OrgRole,
)
from app.services.storage.client import StorageService, get_storage_service
from app.shared.utils import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    escape_like,
)

logger = structlog.get_logger()


CONTENT_TYPE_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
}

_PERMISSION_RANK = {
    PermissionLevel.VIEW: 0,
    PermissionLevel.EDIT: 1,
    PermissionLevel.MANAGE: 2,
}


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


class DocumentService:
    """Document management with permission enforcement."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    @property
    def storage(self) -> StorageService:
        # Resolved lazily so read-only endpoints never need MinIO.
        return get_storage_service()

    # --- Upload ---

    def _validate_file(self, filename: str, file_data: bytes) -> str:
        ext = file_extension(filename)
        if ext not in self.settings.allowed_extensions:
            allowed = ", ".join(f".{e}" for e in self.settings.allowed_extensions)
            shown = f".{ext}" if ext else "(none)"
            raise AppError(
                f"File type {shown} is not supported. Allowed: {allowed}",
                "INVALID_FILE_TYPE",
                400,
            )
        if not file_data:
            raise AppError("The uploaded file is empty", "EMPTY_FILE", 400)
        if len(file_data) > self.settings.max_upload_size_bytes:
            raise AppError(
                f"File exceeds the maximum size of {self.settings.max_upload_size_mb} MB",
                "FILE_TOO_LARGE",
                413,
            )
        return ext

    async def _store_and_enqueue(
        self, version: DocumentVersion, org_id: str, ext: str, file_data: bytes
    ) -> None:
        """Upload bytes, create the processing job, commit, then enqueue.

        The commit must precede the enqueue so the worker can see the rows.
        If the storage upload fails the transaction is rolled back by the
        request scope, so no version ever points at a missing object.
        """
        content_type = CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
        await asyncio.to_thread(
            self.storage.upload_file, version.object_key, file_data, content_type
        )
        self.db.add(
            ProcessingJob(
                id=str(ULID()),
                version_id=version.id,
                organization_id=org_id,
                status="queued",
            )
        )
        await self.db.flush()
        await self.db.commit()
        if enqueue_version_processing(version.id) is False:
            version.status = VersionStatus.FAILED
            version.error_message = (
                "Could not reach the job queue. Retry processing when Redis is available."
            )
            jobs = await self.db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.version_id == version.id, ProcessingJob.status == "queued"
                )
            )
            for job in jobs.scalars():
                job.status = "failed"
                job.error_message = version.error_message
            await self.db.commit()

    async def upload_document(
        self,
        org_id: str,
        user_id: str,
        title: str,
        filename: str,
        file_data: bytes,
        description: str | None = None,
        category: str | None = None,
        department: str | None = None,
        tags: list[str] | None = None,
    ) -> tuple[Document, DocumentVersion]:
        """Upload a new document with its first version."""
        membership = await self._require_active_membership(user_id, org_id)
        if membership.role == OrgRole.VIEWER:
            raise ForbiddenError("Viewers cannot upload documents")

        ext = self._validate_file(filename, file_data)

        doc_id = str(ULID())
        document = Document(
            id=doc_id,
            organization_id=org_id,
            title=title,
            description=description or None,
            file_type=ext,
            original_filename=filename[:500],
            owner_id=user_id,
            status=DocumentStatus.UPLOADED,
            category=category or None,
            department=department or None,
            tags=json.dumps(tags) if tags else None,
        )
        self.db.add(document)
        await self.db.flush()

        version = DocumentVersion(
            id=str(ULID()),
            document_id=doc_id,
            version_number=1,
            file_checksum=hashlib.sha256(file_data).hexdigest(),
            object_key=StorageService.generate_object_key(org_id, doc_id, 1, filename),
            file_size_bytes=len(file_data),
            status=VersionStatus.PENDING,
            uploaded_by=user_id,
        )
        self.db.add(version)
        await self.db.flush()

        await self._store_and_enqueue(version, org_id, ext, file_data)
        logger.info(
            "Document uploaded",
            doc_id=doc_id,
            version_id=version.id,
            filename=filename,
            size_bytes=len(file_data),
        )
        return document, version

    async def upload_new_version(
        self,
        org_id: str,
        doc_id: str,
        user_id: str,
        filename: str,
        file_data: bytes,
    ) -> DocumentVersion:
        """Upload a new version of an existing document.

        The document keeps serving its current active version until the new
        one has been processed successfully.
        """
        document = (
            await self.db.execute(
                select(Document)
                .where(Document.id == doc_id, Document.organization_id == org_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document")
        await self._check_permission(user_id, document, PermissionLevel.EDIT)
        if document.status == DocumentStatus.ARCHIVED:
            raise AppError(
                "Restore this document before uploading a new version",
                "DOCUMENT_ARCHIVED",
                400,
            )

        ext = self._validate_file(filename, file_data)
        if ext != document.file_type:
            raise AppError(
                f"New versions must be .{document.file_type} files like the original",
                "FILE_TYPE_MISMATCH",
                400,
            )

        checksum = hashlib.sha256(file_data).hexdigest()
        latest = await self.db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        latest_version = latest.scalar_one_or_none()
        if latest_version is not None and latest_version.file_checksum == checksum:
            raise ConflictError("This file is identical to the latest version")
        next_version = (latest_version.version_number if latest_version else 0) + 1

        version = DocumentVersion(
            id=str(ULID()),
            document_id=doc_id,
            version_number=next_version,
            file_checksum=checksum,
            object_key=StorageService.generate_object_key(org_id, doc_id, next_version, filename),
            file_size_bytes=len(file_data),
            status=VersionStatus.PENDING,
            uploaded_by=user_id,
        )
        self.db.add(version)
        await self.db.flush()

        await self._store_and_enqueue(version, org_id, ext, file_data)
        return version

    # --- CRUD ---

    async def get_document(self, doc_id: str, org_id: str, user_id: str) -> Document:
        """Get a document with permission check."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.VIEW)
        return document

    async def list_documents(
        self,
        org_id: str,
        user_id: str,
        page: int = 1,
        per_page: int = 20,
        category: str | None = None,
        department: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Document], int]:
        """List documents in an organization that the user can view.

        Archived documents are hidden unless ``status_filter == "archived"``.
        """
        membership = await self._require_active_membership(user_id, org_id)
        query = select(Document).where(
            Document.organization_id == org_id,
            visible_documents_filter(user_id, membership),
        )

        if status_filter:
            try:
                status_value = DocumentStatus(status_filter)
            except ValueError:
                raise AppError(f"Unknown status '{status_filter}'", "INVALID_STATUS", 400) from None
            query = query.where(Document.status == status_value)
        else:
            query = query.where(Document.status != DocumentStatus.ARCHIVED)

        if category:
            query = query.where(Document.category == category)
        if department:
            query = query.where(Document.department == department)
        if search and search.strip():
            pattern = f"%{escape_like(search.strip())}%"
            query = query.where(
                or_(
                    Document.title.ilike(pattern, escape="\\"),
                    Document.original_filename.ilike(pattern, escape="\\"),
                )
            )

        total = (
            await self.db.execute(select(func.count()).select_from(query.subquery()))
        ).scalar() or 0

        query = (
            query.order_by(Document.updated_at.desc(), Document.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def update_document(
        self,
        doc_id: str,
        org_id: str,
        user_id: str,
        fields: dict[str, Any],
    ) -> Document:
        """Update document metadata. ``fields`` holds only the keys to change."""
        document = (
            await self.db.execute(
                select(Document)
                .where(Document.id == doc_id, Document.organization_id == org_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document")
        await self._check_permission(user_id, document, PermissionLevel.EDIT)

        if "title" in fields and fields["title"] is not None:
            document.title = fields["title"]
        for key in ("description", "category", "department"):
            if key in fields:
                setattr(document, key, fields[key] or None)
        if "tags" in fields:
            document.tags = json.dumps(fields["tags"]) if fields["tags"] else None

        await self.db.flush()
        return document

    async def archive_document(self, doc_id: str, org_id: str, user_id: str) -> Document:
        """Soft-delete a document. It disappears from search immediately."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.MANAGE)
        document.status = DocumentStatus.ARCHIVED
        await self.db.flush()
        return document

    async def restore_document(self, doc_id: str, org_id: str, user_id: str) -> Document:
        """Undo an archive, returning the document to its processing state."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.MANAGE)
        if document.status != DocumentStatus.ARCHIVED:
            raise AppError("Document is not archived", "NOT_ARCHIVED", 400)
        document.status = await self._derived_status(document)
        await self.db.flush()
        return document

    async def _derived_status(self, document: Document) -> DocumentStatus:
        if document.active_version_id:
            return DocumentStatus.READY
        latest = await self.db.execute(
            select(DocumentVersion.status)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        status = latest.scalar_one_or_none()
        if status == VersionStatus.FAILED:
            return DocumentStatus.FAILED
        if status == VersionStatus.PENDING:
            return DocumentStatus.UPLOADED
        return DocumentStatus.PROCESSING

    async def retry_processing(self, doc_id: str, org_id: str, user_id: str) -> DocumentVersion:
        """Re-run ingestion for the latest version after a failure."""
        document = (
            await self.db.execute(
                select(Document)
                .where(Document.id == doc_id, Document.organization_id == org_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document")
        await self._check_permission(user_id, document, PermissionLevel.EDIT)
        result = await self.db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise NotFoundError("DocumentVersion")
        if version.status != VersionStatus.FAILED:
            raise AppError("Only failed versions can be reprocessed", "NOT_FAILED", 400)
        version.status = VersionStatus.PENDING
        version.error_message = None
        self.db.add(
            ProcessingJob(
                id=str(ULID()),
                version_id=version.id,
                organization_id=org_id,
                status="queued",
            )
        )
        await self.db.flush()
        await self.db.commit()
        if enqueue_version_processing(version.id) is False:
            version.status = VersionStatus.FAILED
            version.error_message = (
                "Could not reach the job queue. Retry processing when Redis is available."
            )
            jobs = await self.db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.version_id == version.id, ProcessingJob.status == "queued"
                )
            )
            for job in jobs.scalars():
                job.status = "failed"
                job.error_message = version.error_message
            await self.db.commit()
        return version

    # --- Versions ---

    async def list_versions(
        self, doc_id: str, org_id: str, user_id: str
    ) -> tuple[Document, list[DocumentVersion]]:
        """List all versions of a document, newest first."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.VIEW)

        result = await self.db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc_id)
            .order_by(DocumentVersion.version_number.desc())
        )
        return document, list(result.scalars().all())

    async def get_version(self, document: Document, version_id: str | None) -> DocumentVersion:
        """Resolve a version of ``document``: explicit id, else active, else latest."""
        query = select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        if version_id:
            query = query.where(DocumentVersion.id == version_id)
        elif document.active_version_id:
            query = query.where(DocumentVersion.id == document.active_version_id)
        else:
            query = query.order_by(DocumentVersion.version_number.desc()).limit(1)
        version = (await self.db.execute(query)).scalar_one_or_none()
        if not version:
            raise NotFoundError("DocumentVersion")
        return version

    async def get_file(
        self, doc_id: str, org_id: str, user_id: str, version_id: str | None = None
    ) -> tuple[Document, DocumentVersion, bytes]:
        """Fetch the original file bytes for a version the user may view."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.VIEW)
        version = await self.get_version(document, version_id)
        data = await asyncio.to_thread(self.storage.download_file, version.object_key)
        return document, version, data

    # --- Permissions ---

    async def list_permissions(
        self, doc_id: str, org_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """List explicit grants with readable subject names."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.VIEW)
        result = await self.db.execute(
            select(DocumentPermission)
            .where(DocumentPermission.document_id == doc_id)
            .order_by(DocumentPermission.created_at)
        )
        perms = list(result.scalars().all())

        user_ids = [p.subject_id for p in perms if p.subject_type == SubjectType.USER]
        group_ids = [p.subject_id for p in perms if p.subject_type == SubjectType.GROUP]
        names: dict[str, str] = {}
        if user_ids:
            rows = await self.db.execute(
                select(User.id, User.full_name, User.email).where(User.id.in_(user_ids))
            )
            names.update({uid: f"{name} ({email})" for uid, name, email in rows.all()})
        if group_ids:
            group_rows = await self.db.execute(
                select(Group.id, Group.name).where(Group.id.in_(group_ids))
            )
            names.update({gid: name for gid, name in group_rows.all()})

        return [
            {
                "id": p.id,
                "document_id": p.document_id,
                "subject_type": p.subject_type.value,
                "subject_id": p.subject_id,
                "subject_name": names.get(p.subject_id),
                "permission": p.permission.value,
                "granted_by": p.granted_by,
                "created_at": p.created_at,
            }
            for p in perms
        ]

    async def grant_permission(
        self,
        doc_id: str,
        org_id: str,
        granter_id: str,
        subject_type: str,
        subject_id: str,
        permission: str,
    ) -> DocumentPermission:
        """Grant (or change) a permission on a document.

        Granting restricts the document: members without a grant (directly
        or through a group) lose their default view access.
        """
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(granter_id, document, PermissionLevel.MANAGE)
        subject = SubjectType(subject_type)
        await self._validate_subject(org_id, subject, subject_id)

        existing = await self.db.execute(
            select(DocumentPermission).where(
                DocumentPermission.document_id == doc_id,
                DocumentPermission.subject_type == subject,
                DocumentPermission.subject_id == subject_id,
            )
        )
        document.restricted = True
        perm = existing.scalar_one_or_none()
        if perm is not None:
            perm.permission = PermissionLevel(permission)
            perm.granted_by = granter_id
            await self.db.flush()
            return perm

        perm = DocumentPermission(
            id=str(ULID()),
            document_id=doc_id,
            subject_type=subject,
            subject_id=subject_id,
            permission=PermissionLevel(permission),
            granted_by=granter_id,
        )
        self.db.add(perm)
        await self.db.flush()
        return perm

    async def _validate_subject(self, org_id: str, subject: SubjectType, subject_id: str) -> None:
        if subject == SubjectType.USER:
            member = await _membership(self.db, subject_id, org_id)
            if member is None or member.status != MembershipStatus.ACTIVE:
                raise AppError(
                    "That user is not a member of this organization",
                    "INVALID_SUBJECT",
                    400,
                )
        else:
            group = await self.db.execute(
                select(Group.id).where(Group.id == subject_id, Group.organization_id == org_id)
            )
            if group.scalar_one_or_none() is None:
                raise AppError(
                    "That group does not exist in this organization",
                    "INVALID_SUBJECT",
                    400,
                )

    async def set_restricted(
        self, doc_id: str, org_id: str, user_id: str, restricted: bool
    ) -> Document:
        """Restrict a document, or open it to every member of the organization.

        Grants are kept either way: on an open document they still give
        edit/manage rights.
        """
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(user_id, document, PermissionLevel.MANAGE)
        document.restricted = restricted
        await self.db.flush()
        return document

    async def revoke_permission(
        self,
        doc_id: str,
        org_id: str,
        revoker_id: str,
        subject_type: str,
        subject_id: str,
    ) -> None:
        """Revoke a permission on a document."""
        document = await self._get_document(doc_id, org_id)
        await self._check_permission(revoker_id, document, PermissionLevel.MANAGE)

        result = await self.db.execute(
            select(DocumentPermission).where(
                DocumentPermission.document_id == doc_id,
                DocumentPermission.subject_type == SubjectType(subject_type),
                DocumentPermission.subject_id == subject_id,
            )
        )
        perm = result.scalar_one_or_none()
        if not perm:
            raise NotFoundError("Permission")

        await self.db.delete(perm)
        await self.db.flush()

    async def effective_permission(
        self, user_id: str, document: Document
    ) -> PermissionLevel | None:
        """The highest permission ``user_id`` holds on ``document`` (None = no access)."""
        for level in (PermissionLevel.MANAGE, PermissionLevel.EDIT, PermissionLevel.VIEW):
            try:
                await self._check_permission(user_id, document, level)
                return level
            except ForbiddenError:
                continue
        return None

    # --- Helpers ---

    async def _require_active_membership(self, user_id: str, org_id: str) -> Membership:
        membership = await _membership(self.db, user_id, org_id)
        if membership is None or membership.status != MembershipStatus.ACTIVE:
            raise ForbiddenError("You are not a member of this organization")
        return membership

    async def _get_document(self, doc_id: str, org_id: str) -> Document:
        """Get a document ensuring it belongs to the correct organization."""
        result = await self.db.execute(
            select(Document).where(
                Document.id == doc_id,
                Document.organization_id == org_id,
            )
        )
        document = result.scalar_one_or_none()
        if not document:
            raise NotFoundError("Document", doc_id)
        return document

    async def _check_permission(
        self,
        user_id: str,
        document: Document,
        required: PermissionLevel,
    ) -> None:
        """Check if user has the required permission level on a document.

        Resolution order:
        1. Organization owner/admin → full access
        2. Org viewers never get more than view access
        3. Document owner → full access
        4. Explicit grant to the user or one of their groups
        5. Documents without any grant → every member may view
        """
        membership = await self._require_active_membership(user_id, document.organization_id)

        if membership.role in (OrgRole.OWNER, OrgRole.ADMIN):
            return

        if membership.role == OrgRole.VIEWER and required != PermissionLevel.VIEW:
            raise ForbiddenError("Viewers have read-only access")

        if document.owner_id == user_id:
            return

        group_ids = select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)
        grants = await self.db.execute(
            select(DocumentPermission.permission).where(
                DocumentPermission.document_id == document.id,
                or_(
                    and_(
                        DocumentPermission.subject_type == SubjectType.USER,
                        DocumentPermission.subject_id == user_id,
                    ),
                    and_(
                        DocumentPermission.subject_type == SubjectType.GROUP,
                        DocumentPermission.subject_id.in_(group_ids),
                    ),
                ),
            )
        )
        if any(
            _PERMISSION_RANK[granted] >= _PERMISSION_RANK[required] for granted in grants.scalars()
        ):
            return

        if required == PermissionLevel.VIEW:
            if not document.restricted:
                return
            raise ForbiddenError("You do not have permission to view this document")

        raise ForbiddenError(f"You need '{required.value}' permission on this document")


def visible_documents_filter(
    user_id: str, membership: Membership | None
) -> ColumnElement[bool]:
    """SQL predicate selecting the documents ``user_id`` may view.

    Mirrors ``DocumentService._check_permission`` so listing, retrieval and
    single-document access always agree:

    - org owners/admins see everything;
    - everyone else sees documents they own, documents granted to them (or to
      one of their groups), and documents that aren't restricted.
    """
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        return false()
    if membership.role in (OrgRole.OWNER, OrgRole.ADMIN):
        return true()

    user_groups = select(GroupMembership.group_id).where(GroupMembership.user_id == user_id)
    has_my_grant = (
        select(DocumentPermission.id)
        .where(
            DocumentPermission.document_id == Document.id,
            or_(
                and_(
                    DocumentPermission.subject_type == SubjectType.USER,
                    DocumentPermission.subject_id == user_id,
                ),
                and_(
                    DocumentPermission.subject_type == SubjectType.GROUP,
                    DocumentPermission.subject_id.in_(user_groups),
                ),
            ),
        )
        .exists()
    )
    return or_(Document.owner_id == user_id, Document.restricted.is_(False), has_my_grant)


async def _membership(db: AsyncSession, user_id: str, org_id: str) -> Membership | None:
    result = await db.execute(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.organization_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def searchable_versions(
    db: AsyncSession,
    user_id: str,
    org_id: str,
    document_ids: list[str] | None = None,
) -> dict[str, str]:
    """Map document id -> active version id for every document the user may
    search: visible to them, not archived, and with a successfully indexed
    active version.

    Retrieval filters Qdrant by these version ids, so superseded versions and
    archived documents never surface in answers even though their vectors are
    still stored.
    """
    membership = await _membership(db, user_id, org_id)
    query = select(Document.id, Document.active_version_id).where(
        Document.organization_id == org_id,
        Document.status != DocumentStatus.ARCHIVED,
        Document.active_version_id.is_not(None),
        visible_documents_filter(user_id, membership),
    )
    if document_ids is not None:
        query = query.where(Document.id.in_(document_ids))
    result = await db.execute(query)
    return {doc_id: version_id for doc_id, version_id in result.all() if version_id is not None}
