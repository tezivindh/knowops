"""
Vector indexes tracking table.

Records which embedding model and dimensions are used for each collection.
Prevents mixing embeddings from different models in the same collection.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VectorIndex(Base):
    """Tracks Qdrant collection metadata and embedding configuration.

    Ensures embedding model consistency within a collection.
    Changing models requires creating a new collection and re-embedding.
    """

    __tablename__ = "vector_indexes"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection_name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )  # active, rebuilding, deprecated
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
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

    def __repr__(self) -> str:
        return f"<VectorIndex {self.collection_name} model={self.embedding_model}>"
