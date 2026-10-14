"""
Identity module — Authentication service.

Handles password hashing, JWT creation/verification,
refresh token rotation with family-based theft detection.
"""

import hashlib
import uuid
from datetime import timedelta
from typing import Any

import bcrypt
import jwt
from jwt import InvalidTokenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.config import get_settings
from app.modules.identity.models import RefreshToken, User, UserStatus
from app.shared.utils import AppError, utcnow


class AuthService:
    """Handles authentication, token management, and password operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    # --- Password ---

    @staticmethod
    def hash_password(password: str) -> str:
        pwd_bytes = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
        return "bcrypt-sha256$" + bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        if hashed_password.startswith("bcrypt-sha256$"):
            hashed_password = hashed_password.removeprefix("bcrypt-sha256$")
            pwd_bytes = hashlib.sha256(plain_password.encode("utf-8")).hexdigest().encode("ascii")
        else:
            pwd_bytes = plain_password.encode("utf-8")[:72]  # Existing bcrypt accounts.
        try:
            return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
        except Exception:
            return False

    # --- JWT Access Tokens (stateless) ---

    def create_access_token(
        self, user_id: str, email: str, extra_claims: dict[str, Any] | None = None
    ) -> str:
        """Create a short-lived access token (15 min default)."""
        expire = utcnow() + timedelta(minutes=self.settings.jwt_access_token_expire_minutes)
        payload = {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "iat": utcnow(),
            "type": "access",
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(
            payload,
            self.settings.jwt_secret_key,
            algorithm=self.settings.jwt_algorithm,
        )

    def verify_access_token(self, token: str) -> dict[str, Any]:
        """Verify and decode an access token. Raises on invalid/expired."""
        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret_key,
                algorithms=[self.settings.jwt_algorithm],
                options={"require": ["exp", "iat", "sub", "type"]},
            )
            if payload.get("type") != "access":
                raise AppError("Invalid token type", "INVALID_TOKEN", 401)
            return payload
        except InvalidTokenError as e:
            raise AppError(f"Invalid or expired token: {e}", "INVALID_TOKEN", 401) from e

    # --- Refresh Tokens (stored, rotatable, revocable) ---

    @staticmethod
    def _hash_refresh_token(token: str) -> str:
        """SHA-256 hash of raw refresh token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_refresh_token(
        self, user_id: str, token_family: str | None = None
    ) -> tuple[str, RefreshToken]:
        """Create a new refresh token. Returns (raw_token, db_record)."""
        raw_token = str(uuid.uuid4())
        family = token_family or str(uuid.uuid4())
        expires_at = utcnow() + timedelta(days=self.settings.jwt_refresh_token_expire_days)

        refresh = RefreshToken(
            id=str(ULID()),
            user_id=user_id,
            token_hash=self._hash_refresh_token(raw_token),
            token_family=family,
            expires_at=expires_at,
        )
        self.db.add(refresh)
        await self.db.flush()
        return raw_token, refresh

    async def rotate_refresh_token(self, raw_token: str) -> tuple[str, str, RefreshToken]:
        """Rotate a refresh token: revoke old, issue new in same family.

        Returns (new_access_token, new_raw_refresh_token, new_refresh_record).
        Implements theft detection: reuse of revoked token kills entire family.
        """
        token_hash = self._hash_refresh_token(raw_token)

        # Find the token
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            raise AppError("Invalid refresh token", "INVALID_REFRESH_TOKEN", 401)

        # Theft detection: if token is already revoked, kill entire family
        if existing.is_revoked:
            await self._revoke_token_family(existing.token_family)
            raise AppError(
                "Refresh token reuse detected — all sessions revoked",
                "TOKEN_REUSE_DETECTED",
                401,
            )

        # Check expiry
        if existing.expires_at < utcnow():
            raise AppError("Refresh token expired", "REFRESH_TOKEN_EXPIRED", 401)

        # Load user
        user_result = await self.db.execute(select(User).where(User.id == existing.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or user.status != UserStatus.ACTIVE:
            raise AppError("User not found or inactive", "USER_INACTIVE", 401)

        # Revoke old token
        existing.revoked_at = utcnow()

        # Issue new refresh token in same family
        new_raw, new_record = await self.create_refresh_token(
            user_id=user.id, token_family=existing.token_family
        )

        # Issue new access token
        access_token = self.create_access_token(user.id, user.email)

        return access_token, new_raw, new_record

    async def _revoke_token_family(self, token_family: str) -> None:
        """Revoke all tokens in a family (theft detection response)."""
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_family == token_family,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all refresh tokens for a user (logout all, password change)."""
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )

    # --- User Registration ---

    async def register_user(self, email: str, password: str, full_name: str) -> User:
        """Register a new user. Raises on duplicate email."""
        # Check for existing email
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        if result.scalar_one_or_none():
            raise AppError("Email already registered", "EMAIL_EXISTS", 409)

        user = User(
            id=str(ULID()),
            email=email.lower(),
            full_name=full_name,
            password_hash=self.hash_password(password),
        )
        self.db.add(user)
        await self.db.flush()

        return user

    # --- User Login ---

    async def authenticate_user(self, email: str, password: str) -> User:
        """Verify credentials and return user. Raises on failure."""
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()

        if user is None or not self.verify_password(password, user.password_hash):
            raise AppError("Invalid email or password", "INVALID_CREDENTIALS", 401)

        if user.status != UserStatus.ACTIVE:
            raise AppError("Account is not active", "ACCOUNT_INACTIVE", 403)

        if not user.password_hash.startswith("bcrypt-sha256$"):
            user.password_hash = self.hash_password(password)
        return user

    # --- Get Current User ---

    async def get_current_user(self, token: str) -> User:
        """Extract and validate user from access token."""
        payload = self.verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise AppError("Invalid token payload", "INVALID_TOKEN", 401)

        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user is None:
            raise AppError("User not found", "USER_NOT_FOUND", 401)
        if user.status != UserStatus.ACTIVE:
            raise AppError("Account is not active", "ACCOUNT_INACTIVE", 403)

        return user
