"""
Shared utilities: pagination, error responses, and common types.
"""

from datetime import UTC, datetime
from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, Field

T = TypeVar("T")


# --- Pagination ---


class PaginationParams(BaseModel):
    """Query parameters for paginated endpoints."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response envelope."""

    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int


def paginate(items: list[T], total: int, params: PaginationParams) -> PaginatedResponse[T]:
    """Build a paginated response."""
    pages = max(1, (total + params.per_page - 1) // params.per_page)
    return PaginatedResponse(
        items=items,
        total=total,
        page=params.page,
        per_page=params.per_page,
        pages=pages,
    )


# --- Error Responses ---


class ErrorResponse(BaseModel):
    """Standard error response body."""

    detail: str
    error_code: str
    request_id: str | None = None


class AppError(Exception):
    """Application-level error with HTTP status code and error code."""

    def __init__(
        self,
        detail: str,
        error_code: str = "APP_ERROR",
        status_code: int = 400,
    ) -> None:
        self.detail = detail
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource", identifier: str = "") -> None:
        detail = f"{resource} not found" + (f": {identifier}" if identifier else "")
        super().__init__(detail=detail, error_code="NOT_FOUND", status_code=404)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Access denied") -> None:
        super().__init__(detail=detail, error_code="FORBIDDEN", status_code=403)


class ConflictError(AppError):
    def __init__(self, detail: str = "Resource conflict") -> None:
        super().__init__(detail=detail, error_code="CONFLICT", status_code=409)


# --- Timestamps ---


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(UTC)


# --- Requests ---


def request_id_of(request: Request) -> str:
    """The sanitized request ID assigned by the request-ID middleware."""
    return getattr(request.state, "request_id", None) or "unknown"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    agent = request.headers.get("user-agent")
    return agent[:500] if agent else None


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input matches literally (use escape='\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
