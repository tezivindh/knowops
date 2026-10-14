"""
Audit module — SQLAlchemy models.

Immutable audit trail for security-sensitive operations.
Separate from user-editable conversation history.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditAction(str, enum.Enum):
    # Authentication
    LOGIN = "login"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGED = "password_changed"

    # Organization
    ORG_CREATED = "org_created"
    ORG_UPDATED = "org_updated"
    MEMBER_INVITED = "member_invited"
    MEMBER_REMOVED = "member_removed"
    ROLE_CHANGED = "role_changed"

    # Documents
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_DELETED = "document_deleted"
    DOCUMENT_ARCHIVED = "document_archived"
    VERSION_CREATED = "version_created"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"

    # Actions
    ACTION_PROPOSED = "action_proposed"
    ACTION_APPROVED = "action_approved"
    ACTION_REJECTED = "action_rejected"
    ACTION_EXECUTED = "action_executed"
    ACTION_FAILED = "action_failed"

    # Security
    ACCESS_DENIED = "access_denied"
    CROSS_TENANT_ATTEMPT = "cross_tenant_attempt"


class AuditOutcome(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditEvent(Base, kw_only=True):
    """Immutable audit log entry. Never deleted or modified."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"), nullable=False
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )  # e.g., "document", "user", "organization"
    resource_id: Mapped[str | None] = mapped_column(
        String(26), nullable=True, default=None
    )
    outcome: Mapped[AuditOutcome] = mapped_column(
        Enum(AuditOutcome, name="audit_outcome"),
        default=AuditOutcome.SUCCESS,
        nullable=False,
    )
    details: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )  # JSON context
    ip_address: Mapped[str | None] = mapped_column(
        String(45), nullable=True, default=None
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    request_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    __table_args__ = (
        Index("ix_audit_org_action", "organization_id", "action"),
        Index("ix_audit_actor", "actor_id"),
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.action} actor={self.actor_id}>"
