"""
Test configuration and shared fixtures.

Uses separate test database with transaction rollback per test.
Includes factory functions for creating test data.
"""

import os
from collections.abc import AsyncGenerator

# Configure the environment before the app (and its settings cache) loads.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://knowops:knowops@localhost:5432/knowops_test"
)
os.environ.update(
    APP_ENV="testing",
    SECRET_KEY="test-secret-key-that-is-at-least-32-characters-long",
    JWT_SECRET_KEY="test-jwt-secret-key-at-least-32-characters-long",
    DATABASE_URL=TEST_DATABASE_URL,
    TEST_DATABASE_URL=TEST_DATABASE_URL,
)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from ulid import ULID  # noqa: E402

import app.models  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.identity.service import AuthService  # noqa: E402

get_settings.cache_clear()


# --- Fixtures ---


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Per-test session inside an outer transaction that is always rolled back.

    Services call ``commit()`` mid-request (e.g. before enqueueing work); with
    ``join_transaction_mode="create_savepoint"`` those commits only release a
    savepoint, so nothing a test writes ever persists.
    """
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as schema_connection:
        await schema_connection.run_sync(Base.metadata.create_all)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test HTTP client bound to the per-test session."""
    app = create_app()

    async def override_db():
        yield db_session
        await db_session.flush()

    app.dependency_overrides[get_db] = override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


# --- Test Factories ---

class UserFactory:
    """Create test users with sensible defaults."""

    @staticmethod
    async def create(
        db: AsyncSession,
        email: str | None = None,
        full_name: str = "Test User",
        password: str = "testpassword123",
    ):
        from app.modules.identity.models import User

        user = User(
            id=str(ULID()),
            email=email or f"user-{ULID()}@test.com",
            full_name=full_name,
            password_hash=AuthService.hash_password(password),
        )
        db.add(user)
        await db.flush()
        return user


class OrgFactory:
    """Create test organizations with ownership."""

    @staticmethod
    async def create(
        db: AsyncSession,
        owner_id: str,
        name: str = "Test Org",
        slug: str | None = None,
    ):
        from app.modules.organizations.models import (
            Membership,
            MembershipStatus,
            Organization,
            OrgRole,
        )

        org = Organization(
            id=str(ULID()),
            name=name,
            slug=slug or f"test-org-{ULID()}".lower(),
        )
        db.add(org)
        await db.flush()

        membership = Membership(
            id=str(ULID()),
            user_id=owner_id,
            organization_id=org.id,
            role=OrgRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        await db.flush()

        return org


class AuthHelper:
    """Helper for getting auth tokens in tests."""

    @staticmethod
    async def get_token(db: AsyncSession, user) -> str:
        auth = AuthService(db)
        return auth.create_access_token(user.id, user.email)

    @staticmethod
    def auth_header(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}
