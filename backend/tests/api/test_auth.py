"""
API tests — Authentication endpoints.

Tests registration, login, token refresh, logout, and profile management.
Includes cross-tenant security tests.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import AuthHelper, OrgFactory, UserFactory


class TestRegistration:
    """Test user registration."""

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "securepassword123",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["full_name"] == "New User"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, db_session):
        # Create existing user
        await UserFactory.create(db_session, email="existing@example.com")

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "existing@example.com",
                "password": "securepassword123",
                "full_name": "Duplicate User",
            },
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_register_weak_password(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "short",
                "full_name": "User",
            },
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-an-email",
                "password": "securepassword123",
                "full_name": "User",
            },
        )
        assert response.status_code == 422


class TestLogin:
    """Test user login and token issuance."""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_session):
        await UserFactory.create(
            db_session, email="login@example.com", password="correctpassword"
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "correctpassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, db_session):
        await UserFactory.create(
            db_session, email="wrongpw@example.com", password="correctpassword"
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpw@example.com", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "somepassword"},
        )
        assert response.status_code == 401


class TestTokenRefresh:
    """Test refresh token rotation and theft detection."""

    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient, db_session):
        await UserFactory.create(db_session, email="refresh@example.com")

        # Login to get tokens
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "refresh@example.com", "password": "testpassword123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New refresh token should be different
        assert data["refresh_token"] != refresh_token

    @pytest.mark.asyncio
    async def test_refresh_reuse_detection(self, client: AsyncClient, db_session):
        """Using a revoked refresh token should kill the entire family."""
        await UserFactory.create(db_session, email="theft@example.com")

        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "theft@example.com", "password": "testpassword123"},
        )
        old_refresh = login_resp.json()["refresh_token"]

        # First refresh (revokes old token)
        await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )

        # Reuse old token (theft detection)
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert response.status_code == 401


class TestProfile:
    """Test user profile endpoints."""

    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, db_session):
        user = await UserFactory.create(db_session, email="me@example.com")
        token = await AuthHelper.get_token(db_session, user)

        response = await client.get(
            "/api/v1/auth/me",
            headers=AuthHelper.auth_header(token),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"

    @pytest.mark.asyncio
    async def test_get_me_no_auth(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_me_invalid_token(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "INVALID_TOKEN"


class TestCrossTenantSecurity:
    """Explicit cross-tenant authorization tests.

    Verifies that users in Org A cannot access Org B resources.
    """

    @pytest.mark.asyncio
    async def test_user_cannot_view_other_org(self, client: AsyncClient, db_session):
        """User in Org A cannot get details of Org B."""
        user_a = await UserFactory.create(db_session, email="user_a@example.com")
        user_b = await UserFactory.create(db_session, email="user_b@example.com")

        await OrgFactory.create(db_session, owner_id=user_a.id, name="Org A")
        org_b = await OrgFactory.create(db_session, owner_id=user_b.id, name="Org B")

        token_a = await AuthHelper.get_token(db_session, user_a)

        # User A tries to access Org B
        response = await client.get(
            f"/api/v1/organizations/{org_b.id}",
            headers=AuthHelper.auth_header(token_a),
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_cannot_list_other_org_members(
        self, client: AsyncClient, db_session
    ):
        """User in Org A cannot list members of Org B."""
        user_a = await UserFactory.create(db_session, email="memb_a@example.com")
        user_b = await UserFactory.create(db_session, email="memb_b@example.com")

        await OrgFactory.create(db_session, owner_id=user_a.id, name="Org A Members")
        org_b = await OrgFactory.create(db_session, owner_id=user_b.id, name="Org B Members")

        token_a = await AuthHelper.get_token(db_session, user_a)

        response = await client.get(
            f"/api/v1/organizations/{org_b.id}/members",
            headers=AuthHelper.auth_header(token_a),
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_user_only_sees_own_orgs(self, client: AsyncClient, db_session):
        """Listing organizations returns only orgs the user belongs to."""
        user_a = await UserFactory.create(db_session, email="list_a@example.com")
        user_b = await UserFactory.create(db_session, email="list_b@example.com")

        org_a = await OrgFactory.create(db_session, owner_id=user_a.id, name="List Org A")
        await OrgFactory.create(db_session, owner_id=user_b.id, name="List Org B")

        token_a = await AuthHelper.get_token(db_session, user_a)

        response = await client.get(
            "/api/v1/organizations",
            headers=AuthHelper.auth_header(token_a),
        )
        assert response.status_code == 200
        orgs = response.json()
        org_ids = [o["id"] for o in orgs]
        assert org_a.id in org_ids
        # Org B should NOT appear
        assert all(o["name"] != "List Org B" for o in orgs)
