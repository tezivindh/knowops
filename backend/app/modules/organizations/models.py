"""
Organizations module — SQLAlchemy models.

Organizations, memberships, groups, and group memberships.
Every tenant-owned record traces back to an organization.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OrgRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class Organization(Base):
    """Multi-tenant organization (company / workspace)."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    settings: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )  # JSON string for org-level config
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
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", init=False, default_factory=list
    )
    groups: Mapped[list["Group"]] = relationship(
        back_populates="organization", init=False, default_factory=list
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"


class Membership(Base):
    """Links a user to an organization with a specific role."""

    __tablename__ = "memberships"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="org_role"), default=OrgRole.MEMBER, nullable=False
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membership_status"),
        default=MembershipStatus.ACTIVE,
        nullable=False,
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
    user: Mapped["User"] = relationship(back_populates="memberships", init=False)
    organization: Mapped["Organization"] = relationship(
        back_populates="memberships", init=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_user_org"),
        Index("ix_memberships_org_user", "organization_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Membership user={self.user_id} org={self.organization_id} role={self.role}>"


class Group(Base):
    """Department or team within an organization.

    Used for group-level document permissions.
    """

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        back_populates="groups", init=False
    )
    members: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group", init=False, default_factory=list
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_org_group_name"),
    )

    def __repr__(self) -> str:
        return f"<Group {self.name} org={self.organization_id}>"


class GroupMembership(Base):
    """Links a user to a group within an organization."""

    __tablename__ = "group_memberships"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="members", init=False)

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_user"),
        Index("ix_group_memberships_user", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<GroupMembership group={self.group_id} user={self.user_id}>"


class OrgInvitation(Base):
    """An invitation for someone without an account yet.

    When a user registers with ``email`` they become a member with ``role``
    automatically. Accepted invitations are kept (``accepted_at`` set) as a
    record; cancelled ones are deleted.
    """

    __tablename__ = "org_invitations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="org_role"), nullable=False
    )
    invited_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    __table_args__ = (
        # At most one pending invitation per email per organization.
        Index(
            "uq_org_invitation_pending",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
        Index("ix_org_invitations_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<OrgInvitation {self.email} org={self.organization_id}>"


# Forward reference resolution
from app.modules.identity.models import User  # noqa: E402, F401
