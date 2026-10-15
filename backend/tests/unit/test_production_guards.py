import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import create_app
from app.modules.identity.service import AuthService
from app.modules.ingestion.extractors import extract_segments
from app.services.llm.client import LLMService


def test_password_suffix_is_significant_and_legacy_hashes_still_work():
    password = "a" * 80
    hashed = AuthService.hash_password(password)
    assert AuthService.verify_password(password, hashed)
    assert not AuthService.verify_password(password + "b", hashed)
    old = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode()
    assert AuthService.verify_password("legacy-password", old)


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_overlap_tokens": 512},
        {"embedding_dimensions": 0},
        {"llm_max_retries": -1},
        {"llm_retry_max_delay": 0},
        {"app_env": "production", "debug": True},
    ],
)
def test_invalid_runtime_settings_fail_early(overrides):
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_backoff_never_exceeds_configured_cap():
    assert all(0 <= LLMService._backoff_delay(10, 1, 2) <= 2 for _ in range(100))


def test_docx_expansion_is_bounded():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"a" * (101 * 1024 * 1024))
    with pytest.raises(ValueError, match="decompressed"):
        extract_segments(data.getvalue(), "docx")


@pytest.mark.parametrize("failure,expected", [(False, 429), (True, 503)])
async def test_rate_limit_blocks_before_auth_and_returns_retry_header(
    monkeypatch, failure, expected
):
    settings = get_settings().model_copy(update={"app_env": "development"})
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    app.state.rate_limiter = SimpleNamespace(
        allow=AsyncMock(side_effect=ConnectionError() if failure else None, return_value=False)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={})
    assert response.status_code == expected
    assert response.headers["Retry-After"] == "60"
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("unresponsive", [False, True])
async def test_redis_readiness_handles_response_timeouts(monkeypatch, unresponsive):
    from app.main import _check_redis

    client = SimpleNamespace(
        ping=AsyncMock(side_effect=TimeoutError() if unresponsive else None, return_value=True),
        aclose=AsyncMock(),
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr("redis.asyncio.Redis.from_url", factory)

    assert await _check_redis() is (not unresponsive)
    assert factory.call_args.kwargs["socket_connect_timeout"] == 2
    assert factory.call_args.kwargs["socket_timeout"] == 2
    client.aclose.assert_awaited_once()
