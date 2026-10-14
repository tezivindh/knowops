"""
Identity module — API router.

Authentication endpoints: register, login, refresh, logout, and user profile.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.dependencies import AppSettings, DbSession
from app.modules.audit.models import AuditAction, AuditOutcome
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.modules.identity.service import AuthService
from app.shared.utils import (
    AppError,
    ConflictError,
    client_ip,
    request_id_of,
    user_agent,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)


# --- Dependencies ---


async def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    """Extract current user from Bearer token.

    A missing or malformed ``Authorization`` header is a 401 (not FastAPI's
    default 403) so clients treat it like any other expired session.
    """
    if credentials is None or not credentials.credentials:
        raise AppError("Not authenticated", "NOT_AUTHENTICATED", 401)
    return await auth.get_current_user(credentials.credentials)


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status.value,
        email_verified=user.email_verified,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _audit_context(request: Request) -> dict[str, Any]:
    return {
        "ip_address": client_ip(request),
        "user_agent": user_agent(request),
        "request_id": request_id_of(request),
    }


# --- Endpoints ---


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
) -> RegisterResponse:
    """Register a new user account."""
    user = await auth.register_user(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
    )
    return RegisterResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    settings: AppSettings,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Authenticate and receive access + refresh tokens."""
    audit = AuditService(auth.db)
    try:
        user = await auth.authenticate_user(request.email, request.password)
    except AppError:
        await audit.log_event(
            action=AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            details=json.dumps({"email": request.email.lower()}),
            **_audit_context(http_request),
        )
        # The failed-login record must survive the error response, which
        # would otherwise roll the session back.
        await auth.db.commit()
        raise

    access_token = auth.create_access_token(user.id, user.email)
    raw_refresh, _ = await auth.create_refresh_token(user.id)

    await audit.log_event(
        action=AuditAction.LOGIN,
        actor_id=user.id,
        **_audit_context(http_request),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshRequest,
    settings: AppSettings,
    auth: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Rotate refresh token and get new access + refresh tokens."""
    try:
        access_token, new_raw_refresh, _ = await auth.rotate_refresh_token(request.refresh_token)
    except AppError as exc:
        if exc.error_code == "TOKEN_REUSE_DETECTED":
            # Persist the family revocation even though the request fails.
            await auth.db.commit()
        raise
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_raw_refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    http_request: Request,
    current_user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Revoke all refresh tokens for the current user."""
    await auth.revoke_all_user_tokens(current_user.id)
    await AuditService(auth.db).log_event(
        action=AuditAction.LOGOUT,
        actor_id=current_user.id,
        **_audit_context(http_request),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Get current authenticated user profile."""
    return _user_response(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    request: UserUpdateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Update current user profile."""
    if request.full_name is not None:
        current_user.full_name = request.full_name
    if request.email is not None:
        new_email = request.email.lower()
        if new_email != current_user.email:
            taken = await db.execute(select(User.id).where(User.email == new_email))
            if taken.scalar_one_or_none() is not None:
                raise ConflictError("That email address is already in use")
            current_user.email = new_email
            current_user.email_verified = False
    await db.flush()
    return _user_response(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Change password and revoke all existing refresh tokens."""
    if not auth.verify_password(request.current_password, current_user.password_hash):
        raise AppError("Current password is incorrect", "INVALID_PASSWORD", 400)
    if request.current_password == request.new_password:
        raise AppError("New password must differ from the current one", "PASSWORD_UNCHANGED", 400)

    current_user.password_hash = auth.hash_password(request.new_password)
    await auth.revoke_all_user_tokens(current_user.id)
    await AuditService(auth.db).log_event(
        action=AuditAction.PASSWORD_CHANGED,
        actor_id=current_user.id,
        **_audit_context(http_request),
    )
