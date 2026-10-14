"""
Embeddings Service.

Supports two providers, selected via ``EMBEDDING_PROVIDER``:

- ``local``  (default): a local ONNX model served by ``fastembed``.
  No API key or network required after the model is downloaded once.
- ``openai``: any OpenAI-compatible ``/embeddings`` endpoint.

The service is a lazy singleton: the (potentially large) local model is only
loaded on first use. All methods are synchronous — callers running inside an
async context should wrap calls with ``asyncio.to_thread`` to avoid blocking
the event loop.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastembed import TextEmbedding

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()

_OPENAI_BATCH = 64


class EmbeddingService:
    """Produces embedding vectors for documents and queries."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self.settings.embedding_provider
        self._local_model: TextEmbedding | None = None

    # --- Properties ---

    @property
    def dimensions(self) -> int:
        """Embedding vector length. Must match the Qdrant collection."""
        return self.settings.embedding_dimensions

    @property
    def model_name(self) -> str:
        return self.settings.embedding_model

    @property
    def model_tag(self) -> str:
        """Filesystem/collection-safe tag for the current embedding model."""
        return re.sub(r"[^a-z0-9]+", "_", self.model_name.lower()).strip("_")

    # --- Local (fastembed) ---

    def _get_local_model(self) -> TextEmbedding:
        if self._local_model is None:
            from fastembed import TextEmbedding

            logger.info(
                "Loading local embedding model",
                model=self.settings.embedding_model,
                cache_dir=self.settings.embedding_cache_dir,
            )
            self._local_model = TextEmbedding(
                model_name=self.settings.embedding_model,
                cache_dir=self.settings.embedding_cache_dir,
            )
        return self._local_model

    # --- Public API ---

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document chunks."""
        if not texts:
            return []
        if self.provider == "local":
            model = self._get_local_model()
            return [[float(x) for x in vec] for vec in model.embed(texts)]
        return self._embed_openai(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query.

        Local models distinguish query vs. document encoding, so we use the
        dedicated query path when available.
        """
        if self.provider == "local":
            model = self._get_local_model()
            return [float(x) for x in next(iter(model.query_embed([text])))]
        return self._embed_openai([text])[0]

    # --- OpenAI-compatible provider ---

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        url = self.settings.embedding_base_url.rstrip("/") + "/embeddings"
        vectors: list[list[float]] = []
        # Providers cap inputs per request, so send bounded batches.
        for start in range(0, len(texts), _OPENAI_BATCH):
            batch = texts[start : start + _OPENAI_BATCH]
            response = httpx.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.embedding_api_key}"},
                json={"model": self.settings.embedding_model, "input": batch},
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()["data"]
            data.sort(key=lambda d: d.get("index", 0))
            vectors.extend([float(x) for x in item["embedding"]] for item in data)
        for vec in vectors:
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Embedding provider returned {len(vec)} dimensions; "
                    f"EMBEDDING_DIMENSIONS is {self.dimensions}"
                )
        return vectors


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Factory for the embeddings service (lazy singleton)."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
