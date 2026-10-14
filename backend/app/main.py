"""
FastAPI application factory.

Creates the application with middleware, routers, exception handlers,
and startup/shutdown lifecycle events.
"""

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import RequestResponseEndpoint

# Register all ORM models on import so metadata is complete for any entrypoint.
from app import models as _models  # noqa: E402,F401
from app.config import Settings, get_settings
from app.shared.utils import request_id_of

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifecycle: startup and shutdown."""
    settings = get_settings()
    logger.info(
        "Starting KnowOps",
        environment=settings.app_env,
        debug=settings.debug,
    )
    yield
    await app.state.rate_limiter.close()
    logger.info("Shutting down KnowOps")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="AI Knowledge & Operations Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )

    from app.middleware.rate_limit import RateLimiter

    app.state.rate_limiter = RateLimiter(settings.redis_url)

    # --- Middleware ---
    _configure_middleware(app, settings)

    # --- Routers ---
    from app.middleware.metrics import MetricsMiddleware

    registry = CollectorRegistry()
    app.add_middleware(MetricsMiddleware, registry=registry)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    _register_routers(app)

    # --- Exception handlers ---
    _register_exception_handlers(app)

    return app


def _configure_middleware(app: FastAPI, settings: Settings) -> None:
    """Register middleware stack."""

    # Request ID middleware. A client-supplied ID is only trusted when it is a
    # short, plain token; anything else is replaced so it can be safely logged
    # and stored in the audit trail (``audit_events.request_id`` is 36 chars).
    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _REQUEST_ID_RE.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            category = (
                "auth"
                if request.url.path
                in {
                    "/api/v1/auth/login",
                    "/api/v1/auth/register",
                    "/api/v1/auth/refresh",
                    "/api/v1/auth/change-password",
                }
                else "write"
            )
            if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not settings.is_testing:
                try:
                    allowed = await request.app.state.rate_limiter.allow(
                        request.client.host if request.client else "unknown",
                        category,
                        settings.auth_requests_per_minute
                        if category == "auth"
                        else settings.write_requests_per_minute,
                    )
                    code, detail = (429, "Request limit exceeded. Try again in a minute.")
                except Exception:
                    allowed = False
                    code, detail = (503, "Request protection is temporarily unavailable.")
                if not allowed:
                    return JSONResponse(
                        status_code=code,
                        headers={
                            "Retry-After": "60",
                            "X-Request-ID": request_id,
                            "Cache-Control": "no-store",
                        },
                        content={
                            "detail": detail,
                            "error_code": "RATE_LIMITED"
                            if code == 429
                            else "RATE_LIMIT_UNAVAILABLE",
                            "request_id": request_id,
                        },
                    )
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )


_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,36}")


def _register_routers(app: FastAPI) -> None:
    """Mount API routers."""
    from app.modules.actions.router import router as actions_router
    from app.modules.conversations.router import router as conversations_router
    from app.modules.documents.router import router as documents_router
    from app.modules.identity.router import router as identity_router
    from app.modules.knowledge_quality.router import router as knowledge_router
    from app.modules.organizations.router import router as organizations_router
    from app.modules.versioning.router import router as versioning_router

    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(organizations_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(versioning_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(actions_router, prefix="/api/v1")

    # Health check — no auth required
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "healthy", "service": "knowops"}

    @app.get("/ready", tags=["health"])
    async def readiness_check() -> JSONResponse:
        """Report connectivity to every backing service; 503 if any is down."""
        checks = dict(
            zip(
                ("database", "redis", "qdrant", "storage"),
                await asyncio.gather(
                    _check_database(), _check_redis(), _check_qdrant(), _check_storage()
                ),
                strict=True,
            )
        )
        ready = all(checks.values())
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "ready" if ready else "degraded", "checks": checks},
        )


async def _check_database() -> bool:
    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
    )
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


async def _check_qdrant() -> bool:
    from app.services.vector.client import get_vector_service

    return await get_vector_service().health_check()


async def _check_storage() -> bool:
    from app.services.storage.client import StorageService

    def probe() -> bool:
        storage = StorageService()
        return storage.client.bucket_exists(storage.bucket)

    try:
        return await asyncio.wait_for(asyncio.to_thread(probe), timeout=3)
    except Exception:
        return False


def _register_exception_handlers(app: FastAPI) -> None:
    """Global exception handlers for consistent error responses."""
    from app.shared.utils import AppError

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "error_code": exc.error_code,
                "request_id": request_id_of(request),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Flatten pydantic's error list into one readable sentence so clients
        # can always render ``detail`` as a string; keep the raw list too.
        messages = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query"))
            messages.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": "; ".join(messages) or "Invalid request",
                "error_code": "VALIDATION_ERROR",
                "errors": jsonable_errors(exc),
                "request_id": request_id_of(request),
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        # Unique-constraint races that slipped past the service-level checks.
        logger.warning("Integrity error", error_type=type(exc.orig).__name__, path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "This conflicts with an existing record.",
                "error_code": "CONFLICT",
                "request_id": request_id_of(request),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_of(request)
        logger.exception(
            "Unhandled exception",
            error_type=type(exc).__name__,
            request_id=request_id,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal error occurred.",
                "error_code": "INTERNAL_ERROR",
                "request_id": request_id,
            },
        )


def jsonable_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    from fastapi.encoders import jsonable_encoder

    return [
        {k: v for k, v in err.items() if k in ("loc", "msg", "type")}
        for err in jsonable_encoder(exc.errors())
    ]


# Create the default app instance
app = create_app()
