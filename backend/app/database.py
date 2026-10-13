"""
Database engine and session management.

Async SQLAlchemy setup with connection pooling.
Sessions are request-scoped via FastAPI dependency injection.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from app.config import get_settings


class Base(MappedAsDataclass, DeclarativeBase, kw_only=True):
    """Base class for all SQLAlchemy models with keyword-only dataclass fields.

    ``eager_defaults`` makes the ORM fetch server-generated values (e.g. the
    ``updated_at`` set by ``onupdate=func.now()``) via RETURNING at flush time.
    Without it those attributes are expired after an UPDATE, and reading them
    afterwards triggers a lazy load, which raises ``MissingGreenlet`` under
    asyncio.
    """

    __mapper_args__ = {"eager_defaults": True}


def create_engine(database_url: str | None = None) -> AsyncEngine:
    """Create async SQLAlchemy engine."""
    settings = get_settings()
    url = database_url or settings.effective_database_url

    return create_async_engine(
        url,
        echo=settings.database_echo,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine = create_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
