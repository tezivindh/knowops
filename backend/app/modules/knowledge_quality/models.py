"""
Knowledge quality module — SQLAlchemy models.

Findings for conflicts, gaps, stale knowledge, and unanswered questions.
Each finding has evidence, severity, status, and assignment workflows.
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


class FindingType(str, enum.Enum):
    CONFLICT = "conflict"
    GAP = "gap"
    STALE = "stale"
    UNANSWERED = "unanswered"


class FindingSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, enum.Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class KnowledgeFinding(Base):
    """A detected knowledge quality issue.

    Evidence-backed, with severity, assignment, and resolution tracking.
    """

    __tablename__ = "knowledge_findings"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    finding_type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, name="finding_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of evidence objects
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity"),
        default=FindingSeverity.MEDIUM,
        nullable=False,
    )
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status"),
        default=FindingStatus.OPEN,
        nullable=False,
    )
    # Related documents (JSON array of document version IDs)
    related_documents: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    assigned_to: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    resolved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    resolution_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    detected_by: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )  # "system", "user", "auto_scan"
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

    __table_args__ = (
        Index("ix_findings_org_status", "organization_id", "status"),
        Index("ix_findings_org_type", "organization_id", "finding_type"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeFinding {self.finding_type} status={self.status}>"
