"""
KnowOps application configuration.

Pydantic Settings for type-safe, environment-driven configuration.
All secrets and service URLs are loaded from environment variables.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "KnowOps"
    app_env: Literal["development", "testing", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    database_echo: bool = False
    secret_key: str = Field(min_length=32)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    auth_requests_per_minute: int = Field(default=20, ge=1, le=10000)
    write_requests_per_minute: int = Field(default=120, ge=1, le=10000)

    # --- JWT ---
    jwt_secret_key: str = Field(min_length=32)
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"

    # --- PostgreSQL ---
    database_url: str = "postgresql+asyncpg://knowops:knowops@localhost:5432/knowops"
    test_database_url: str = "postgresql+asyncpg://knowops:knowops@localhost:5432/knowops_test"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_queue: str = "celery"

    # --- MinIO ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "knowops"
    minio_secret_key: str = "knowops123"
    minio_bucket: str = "knowops-documents"
    minio_use_ssl: bool = False

    # --- Qdrant ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None

    # --- LLM ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_primary_model: str = "openai/gpt-oss-120b"
    llm_fallback_model: str = "openai/gpt-oss-20b"
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 30.0
    llm_request_timeout: int = 60

    # --- Embeddings ---
    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_cache_dir: str | None = None

    # --- Chunking & Retrieval ---
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    retrieval_top_k: int = 6
    retrieval_score_threshold: float = 0.2
    chat_history_limit: int = 10

    # --- Knowledge quality ---
    stale_document_days: int = 180
    conflict_similarity_threshold: float = 0.78
    conflict_max_pairs: int = 12

    # --- Upload ---
    max_upload_size_mb: int = 50
    allowed_file_types: str = "pdf,docx,txt,md,csv"

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if (
            self.chunk_size_tokens <= 0
            or not 0 <= self.chunk_overlap_tokens < self.chunk_size_tokens
        ):
            raise ValueError("Chunk overlap must be nonnegative and smaller than chunk size")
        if (
            min(
                self.embedding_dimensions,
                self.max_upload_size_mb,
                self.retrieval_top_k,
                self.llm_request_timeout,
                self.jwt_access_token_expire_minutes,
                self.jwt_refresh_token_expire_days,
            )
            <= 0
        ):
            raise ValueError("Dimensions, limits, timeouts and token lifetimes must be positive")
        if not 0 <= self.llm_max_retries <= 10:
            raise ValueError("LLM retries must be between zero and ten")
        if not 0 <= self.llm_retry_base_delay <= self.llm_retry_max_delay <= 120:
            raise ValueError("Invalid LLM backoff bounds")
        if self.app_env == "production":
            if self.debug or "*" in self.cors_origins:
                raise ValueError("Production requires DEBUG=false and explicit CORS origins")
            if self.secret_key == self.jwt_secret_key or any(
                key.startswith(("change-me", "test-"))
                for key in (self.secret_key, self.jwt_secret_key)
            ):
                raise ValueError("Production requires distinct non-placeholder secrets")
            if self.minio_secret_key == "knowops123":
                raise ValueError("Production requires private storage credentials")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_extensions(self) -> list[str]:
        return [ext.strip().lower() for ext in self.allowed_file_types.split(",")]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_database_url(self) -> str:
        return self.test_database_url if self.is_testing else self.database_url


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
