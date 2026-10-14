"""
LLM Service — OpenAI-compatible client for Groq.

Implements the fallback strategy from the technical spec:
- Primary model (gpt-oss-120b) with retry + exponential backoff
- Fallback model (gpt-oss-20b) with fresh retry budget
- Non-retryable error detection (4xx except 429)
- Per-request token budget enforcement
- Comprehensive logging of all LLM calls
"""

import random
import time
from dataclasses import dataclass
from typing import Any, cast

import structlog
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.config import get_settings
from app.shared.utils import AppError

logger = structlog.get_logger()


@dataclass
class LLMCallMetrics:
    """Metrics for a single LLM call."""

    model: str = ""
    latency_ms: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    status: str = "pending"
    fallback_used: bool = False
    error: str | None = None


NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class LLMService:
    """Manages LLM interactions with retry and fallback logic."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_base_url,
            timeout=float(self.settings.llm_request_timeout),
            max_retries=0,  # We handle retries ourselves
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request with automatic retry and fallback.

        Returns dict with keys: content, model, metrics
        """
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        # Try primary model
        metrics = LLMCallMetrics(model=self.settings.llm_primary_model)
        result = await self._try_model(
            model=self.settings.llm_primary_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            metrics=metrics,
        )

        if result is not None:
            return result

        # Primary failed — try fallback
        logger.warning(
            "Primary LLM failed, switching to fallback",
            primary_model=self.settings.llm_primary_model,
            fallback_model=self.settings.llm_fallback_model,
        )
        metrics = LLMCallMetrics(
            model=self.settings.llm_fallback_model,
            fallback_used=True,
        )
        result = await self._try_model(
            model=self.settings.llm_fallback_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            metrics=metrics,
        )

        if result is not None:
            return result

        # Both failed
        logger.error("Both LLM models failed")
        raise LLMUnavailableError("LLM service is temporarily unavailable. Please try again later.")

    async def _try_model(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        metrics: LLMCallMetrics,
    ) -> dict[str, Any] | None:
        """Try a model with retries. Returns result dict or None on failure."""
        max_retries = self.settings.llm_max_retries
        base_delay = self.settings.llm_retry_base_delay
        max_delay = self.settings.llm_retry_max_delay

        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=cast(list[ChatCompletionMessageParam], messages),
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                elapsed_ms = (time.monotonic() - start) * 1000
                metrics.latency_ms = elapsed_ms
                metrics.tokens_in = response.usage.prompt_tokens if response.usage else 0
                metrics.tokens_out = response.usage.completion_tokens if response.usage else 0
                metrics.status = "success"

                self._log_call(metrics)

                return {
                    "content": response.choices[0].message.content,
                    "model": model,
                    "metrics": metrics,
                }

            except APIStatusError as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                metrics.latency_ms = elapsed_ms
                metrics.error = type(e).__name__

                if e.status_code == 429 and getattr(e, "code", None) in {
                    "insufficient_quota",
                    "billing_hard_limit_reached",
                    "quota_exceeded",
                }:
                    metrics.status = "quota_exhausted"
                    self._log_call(metrics)
                    raise LLMQuotaError("The provider quota is exhausted", status_code=429) from e

                if e.status_code in NON_RETRYABLE_STATUS_CODES:
                    metrics.status = "non_retryable_error"
                    self._log_call(metrics)
                    raise LLMRequestError(
                        "The model provider rejected the request",
                        status_code=e.status_code,
                    ) from e

                if e.status_code in RETRYABLE_STATUS_CODES:
                    metrics.status = f"retry_{attempt + 1}"
                    self._log_call(metrics)

                    if attempt < max_retries:
                        delay = self._backoff_delay(attempt, base_delay, max_delay)
                        logger.info(
                            "Retrying LLM call",
                            model=model,
                            attempt=attempt + 1,
                            delay_s=delay,
                            status_code=e.status_code,
                        )
                        import asyncio

                        await asyncio.sleep(delay)
                        continue

                return None

            except (APIConnectionError, APITimeoutError) as e:
                elapsed_ms = (time.monotonic() - start) * 1000
                metrics.latency_ms = elapsed_ms
                metrics.error = type(e).__name__
                metrics.status = f"retry_{attempt + 1}"
                self._log_call(metrics)

                if attempt < max_retries:
                    delay = self._backoff_delay(attempt, base_delay, max_delay)
                    logger.info(
                        "Retrying LLM call after connection error",
                        model=model,
                        attempt=attempt + 1,
                        delay_s=delay,
                    )
                    import asyncio

                    await asyncio.sleep(delay)
                    continue

                return None

        return None

    @staticmethod
    def _backoff_delay(attempt: int, base: float, maximum: float) -> float:
        """Exponential backoff with ±25% jitter."""
        delay = min(base * (2**attempt), maximum)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return float(min(maximum, max(0.0, delay + jitter)))

    @staticmethod
    def _log_call(metrics: LLMCallMetrics) -> None:
        logger.info(
            "LLM call",
            model=metrics.model,
            latency_ms=round(metrics.latency_ms, 1),
            tokens_in=metrics.tokens_in,
            tokens_out=metrics.tokens_out,
            status=metrics.status,
            fallback_used=metrics.fallback_used,
            error=metrics.error,
        )


class LLMUnavailableError(Exception):
    """Both primary and fallback LLM models are unavailable."""

    pass


class LLMRequestError(Exception):
    """Non-retryable LLM request error (bad request, auth failure, etc.)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


class LLMQuotaError(LLMRequestError):
    """Account quota requires operator action rather than repeated requests."""


def get_llm_service() -> LLMService:
    """Factory for LLM service."""
    return LLMService()


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Extract the first JSON object from a model reply.

    Models sometimes wrap JSON in prose or Markdown fences, so this scans for
    the first balanced ``{...}`` that parses. Raises ``ValueError`` if none.
    """
    import json

    if not text:
        raise ValueError("Empty model response")
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Model response did not contain a JSON object")


def llm_app_error(exc: Exception) -> AppError:
    """Translate an LLM failure into a user-facing ``AppError``.

    Provider error bodies (which can include request details) are logged by
    ``LLMService`` and never shown to end users.
    """
    from app.shared.utils import AppError

    if isinstance(exc, LLMQuotaError):
        return AppError(
            "The AI provider quota is exhausted. Contact an administrator.",
            "LLM_QUOTA_EXHAUSTED",
            503,
        )
    if isinstance(exc, LLMRequestError) and exc.status_code in (401, 403):
        return AppError(
            "The AI engine rejected KnowOps' credentials. An administrator needs to "
            "check the LLM_API_KEY setting.",
            "LLM_NOT_CONFIGURED",
            502,
        )
    if isinstance(exc, LLMRequestError):
        return AppError(
            "The AI engine couldn't process this request. Try rephrasing or shortening it.",
            "LLM_REQUEST_ERROR",
            502,
        )
    return AppError(
        "The AI engine is temporarily unavailable. Please try again in a moment.",
        "LLM_UNAVAILABLE",
        503,
    )
