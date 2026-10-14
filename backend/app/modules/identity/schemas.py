"""
Identity module — Pydantic schemas.

Request/response models for authentication and user management.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

# --- Registration ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: FullName


class RegisterResponse(BaseModel):
    id: str
    email: str
    full_name: str
    created_at: datetime


# --- Login ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


# --- User ---

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    status: str
    email_verified: bool
    created_at: datetime
    updated_at: datetime


class UserUpdateRequest(BaseModel):
    full_name: FullName | None = None
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
