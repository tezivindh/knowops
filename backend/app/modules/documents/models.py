"""
Documents module — SQLAlchemy models.

Documents, document versions, document permissions, and processing jobs.
Implements immutable versions, three-level permissions, and lifecycle management.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class VersionStatus(str, enum.Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class PermissionLevel(str, enum.Enum):
    VIEW = "view"
    EDIT = "edit"
    MANAGE = "manage"


class SubjectType(str, enum.Enum):
    USER = "user"
    GROUP = "group"


class Document(Base, kw_only=True):
    """A document owned by an organization.

    Has an active_version_id pointing to the current searchable version.
    Version switch only happens after successful processing + indexing.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    active_version_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, default=None
    )  # FK added after DocumentVersion definition
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    tags: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )  # JSON array as string
    # Restricted documents are visible only to their owner, org admins, and
    # explicit grantees. Kept as a flag (not "has any grant") so removing the
    # last grant never silently opens a document to the whole organization.
    restricted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        init=False,
    )

    # Relationships
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        init=False,
        default_factory=list,
        foreign_keys="DocumentVersion.document_id",
    )
    permissions: Mapped[list["DocumentPermission"]] = relationship(
        back_populates="document", init=False, default_factory=list
    )

    __table_args__ = (
        Index("ix_documents_org_status", "organization_id", "status"),
        Index("ix_documents_org_category", "organization_id", "category"),
    )

    def __repr__(self) -> str:
        return f"<Document {self.title} org={self.organization_id}>"


class DocumentVersion(Base):
    """Immutable snapshot of a document. Once created, never modified.

    Only the version with status=READY and matching document.active_version_id
    is included in search results.
    """

    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    object_key: Mapped[str] = mapped_column(
        String(500), nullable=False
    )  # MinIO path
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    status: Mapped[VersionStatus] = mapped_column(
        Enum(VersionStatus, name="version_status"),
        default=VersionStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        back_populates="versions",
        init=False,
        foreign_keys=[document_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_doc_version_number"
        ),
        Index("ix_doc_versions_status", "document_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<DocumentVersion {self.document_id} v{self.version_number}>"


class DocumentPermission(Base):
    """Explicit document-level access control.

    Subject can be a user or a group.
    Permission levels: view, edit, manage.
    """

    __tablename__ = "document_permissions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="subject_type"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        String(26), nullable=False
    )  # User ID or Group ID
    permission: Mapped[PermissionLevel] = mapped_column(
        Enum(PermissionLevel, name="permission_level"), nullable=False
    )
    granted_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        back_populates="permissions", init=False
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_id",
            name="uq_doc_permission_subject",
        ),
        Index("ix_doc_perm_subject", "subject_type", "subject_id"),
    )

    def __repr__(self) -> str:
        return f"<DocumentPermission doc={self.document_id} {self.subject_type}={self.subject_id}>"


class ProcessingJob(Base):
    """Tracks background processing of document versions.

    Idempotent: re-running a job for the same version_id
    replaces previous chunks and embeddings.
    """

    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.id} version={self.version_id}>"
