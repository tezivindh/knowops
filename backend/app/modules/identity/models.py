"""
Identity module — SQLAlchemy models.

Users, refresh tokens, and authentication state.
Password hashes use bcrypt. Refresh tokens implement
family-based rotation with theft detection.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class User(Base):
    """Application user. Belongs to organizations via memberships."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
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
    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", init=False, default_factory=list
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", init=False, default_factory=list
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class RefreshToken(Base):
    """Refresh token with family-based rotation and theft detection.

    Each token chain shares a token_family. Reuse of a revoked
    token invalidates the entire family (security: token theft).
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    token_family: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens", init=False)

    __table_args__ = (
        Index("ix_refresh_tokens_family_active", "token_family", "revoked_at"),
    )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __repr__(self) -> str:
        return f"<RefreshToken {self.id} user={self.user_id}>"


# Forward reference resolution
from app.modules.organizations.models import Membership  # noqa: E402, F401
