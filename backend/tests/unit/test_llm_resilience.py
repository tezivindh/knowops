"""Controlled provider failures exercise the real retry/fallback implementation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from app.services.llm.client import (
    LLMQuotaError,
    LLMRequestError,
    LLMService,
    LLMUnavailableError,
)


def provider_error(status, code=None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.invalid"))
    return APIStatusError("provider failure", response=response, body={"code": code})


def service(monkeypatch, effects):
    instance = LLMService()
    instance.settings = instance.settings.model_copy(
        update={
            "llm_max_retries": 1,
            "llm_retry_base_delay": 0,
            "llm_retry_max_delay": 0,
        }
    )
    create = AsyncMock(side_effect=effects)
    instance.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    return instance, create


def success():
    return SimpleNamespace(
        usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )


async def test_server_failure_exhausts_primary_then_uses_fallback(monkeypatch):
    instance, create = service(monkeypatch, [provider_error(503), provider_error(503), success()])
    result = await instance.chat_completion([{"role": "user", "content": "test"}])
    assert result["metrics"].fallback_used
    assert [call.kwargs["model"] for call in create.call_args_list] == [
        instance.settings.llm_primary_model,
        instance.settings.llm_primary_model,
        instance.settings.llm_fallback_model,
    ]


@pytest.mark.parametrize("status", [400, 401, 403, 422])
async def test_invalid_requests_and_auth_are_not_retried(monkeypatch, status):
    instance, create = service(monkeypatch, [provider_error(status)])
    with pytest.raises(LLMRequestError):
        await instance.chat_completion([])
    assert create.await_count == 1


async def test_exhausted_quota_is_not_retried(monkeypatch):
    instance, create = service(monkeypatch, [provider_error(429, "insufficient_quota")])
    with pytest.raises(LLMQuotaError):
        await instance.chat_completion([])
    assert create.await_count == 1


async def test_transient_rate_limit_retries(monkeypatch):
    instance, create = service(monkeypatch, [provider_error(429), success()])
    assert (await instance.chat_completion([]))["content"] == "ok"
    assert create.await_count == 2


async def test_connection_failure_is_bounded(monkeypatch):
    error = APIConnectionError(request=httpx.Request("POST", "https://provider.invalid"))
    instance, create = service(monkeypatch, [error] * 4)
    with pytest.raises(LLMUnavailableError):
        await instance.chat_completion([])
    assert create.await_count == 4
