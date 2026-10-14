"""
Ingestion — token-aware chunking.

Splits extracted segments into overlapping token windows so retrieval can
return focused passages that still carry their source location.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
import tiktoken

from app.modules.ingestion.extractors import Segment

logger = structlog.get_logger()

_ENCODING_NAME = "cl100k_base"


@dataclass
class Chunk:
    """A single embeddable passage."""

    index: int
    text: str
    token_count: int
    page_number: int | None = None
    section_heading: str | None = None


def chunk_segments(
    segments: list[Segment],
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """Split segments into overlapping token windows.

    Each output chunk inherits the page/heading of the segment it starts in.
    """
    if chunk_size <= 0 or overlap < 0:
        raise ValueError("Chunk size must be positive and overlap nonnegative")
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)

    encoding = tiktoken.get_encoding(_ENCODING_NAME)
    chunks: list[Chunk] = []

    for segment in segments:
        tokens = encoding.encode(segment.text, disallowed_special=())
        if not tokens:
            continue

        # A token can contain only part of a UTF-8 character. Only split where
        # the next token begins a character, so every quotation is source text.
        token_bytes = [encoding.decode_single_token_bytes(token) for token in tokens]
        boundaries = {0, len(tokens)} | {
            i for i, value in enumerate(token_bytes) if value[0] & 0xC0 != 0x80
        }
        start = 0
        while start < len(tokens):
            end = min(start + chunk_size, len(tokens))
            while end not in boundaries and end > start:
                end -= 1
            if end == start:
                # A single character may require more tokens than a tiny budget.
                end = start + 1
                while end not in boundaries:
                    end += 1
            window = tokens[start:end]
            text = encoding.decode(window, errors="strict").strip()
            next_start = max(start + 1, end - overlap)
            while next_start not in boundaries:
                next_start += 1
            start = len(tokens) if end == len(tokens) else next_start
            if not text:
                continue
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=text,
                    token_count=len(window),
                    page_number=segment.page_number,
                    section_heading=segment.section_heading,
                )
            )

    logger.debug("Chunked document", segments=len(segments), chunks=len(chunks))
    return chunks
