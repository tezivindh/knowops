"""
Conversations module — SQLAlchemy models.

Conversations, messages, and message citations.
Citations link AI claims to specific document passages.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(Base):
    """A conversation thread between a user and the AI assistant."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="New conversation")
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
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        init=False,
        default_factory=list,
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_conversations_org_user", "organization_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.id} user={self.user_id}>"


class Message(Base):
    """A single message in a conversation."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    model_used: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )
    # clock_timestamp(), not now(): a question and its answer are inserted in
    # the same transaction, where now() is constant and would tie the order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.clock_timestamp(),
        server_default=func.now(),
        nullable=False,
        init=False,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        back_populates="messages", init=False
    )
    citations: Mapped[list["MessageCitation"]] = relationship(
        back_populates="message",
        init=False,
        default_factory=list,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Message {self.id} role={self.role}>"


class MessageCitation(Base):
    """Links an AI claim to a specific document passage.

    Server-side validated: citations point to real chunks
    from authorized document versions.
    """

    __tablename__ = "message_citations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(
        String(26), nullable=False
    )  # References Qdrant point ID
    quoted_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    section_heading: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    relevance_score: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None
    )  # Float as string for precision
    citation_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Order in the message [1], [2], etc.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        init=False,
    )

    # Relationships
    message: Mapped["Message"] = relationship(
        back_populates="citations", init=False
    )

    def __repr__(self) -> str:
        return f"<Citation {self.citation_index} msg={self.message_id}>"
