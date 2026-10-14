"""
Versioning — compare two versions of a document.

Both files are re-extracted from object storage with the same extractor used
for ingestion, then diffed line by line. An optional LLM summary describes the
substantive changes in plain language.
"""

from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentVersion, PermissionLevel
from app.modules.documents.service import DocumentService
from app.modules.ingestion.extractors import extract_segments
from app.services.llm.client import (
    LLMRequestError,
    LLMUnavailableError,
    get_llm_service,
    llm_app_error,
)
from app.shared.utils import AppError

# Bounds keep the diff fast and the response small for very large files.
MAX_LINES = 5000
MAX_HUNKS = 200
CONTEXT_LINES = 2


@dataclass
class DiffLine:
    kind: str  # "context" | "added" | "removed"
    text: str
    base_line: int | None = None
    target_line: int | None = None


@dataclass
class Hunk:
    base_start: int
    target_start: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class Comparison:
    document: Document
    base: DocumentVersion
    target: DocumentVersion
    hunks: list[Hunk]
    added: int
    removed: int
    unchanged: int
    truncated: bool
    base_text: str
    target_text: str


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def diff_texts(base: str, target: str) -> tuple[list[Hunk], int, int, int, bool]:
    """Line diff with context, returning (hunks, added, removed, unchanged, truncated)."""
    base_lines, target_lines = _lines(base), _lines(target)
    truncated = len(base_lines) > MAX_LINES or len(target_lines) > MAX_LINES
    base_lines, target_lines = base_lines[:MAX_LINES], target_lines[:MAX_LINES]

    matcher = difflib.SequenceMatcher(a=base_lines, b=target_lines, autojunk=False)
    added = removed = unchanged = 0
    hunks: list[Hunk] = []
    for group in matcher.get_grouped_opcodes(CONTEXT_LINES):
        if len(hunks) >= MAX_HUNKS:
            truncated = True
            break
        first = group[0]
        hunk = Hunk(base_start=first[1] + 1, target_start=first[3] + 1)
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for offset, line in enumerate(base_lines[i1:i2]):
                    hunk.lines.append(DiffLine("context", line, i1 + offset + 1, j1 + offset + 1))
                continue
            if tag in ("replace", "delete"):
                for offset, line in enumerate(base_lines[i1:i2]):
                    hunk.lines.append(DiffLine("removed", line, base_line=i1 + offset + 1))
            if tag in ("replace", "insert"):
                for offset, line in enumerate(target_lines[j1:j2]):
                    hunk.lines.append(DiffLine("added", line, target_line=j1 + offset + 1))
        hunks.append(hunk)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return hunks, added, removed, unchanged, truncated


class VersioningService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.documents = DocumentService(db)

    async def _text(self, document: Document, version: DocumentVersion) -> str:
        data = await asyncio.to_thread(self.documents.storage.download_file, version.object_key)
        try:
            segments = await asyncio.to_thread(extract_segments, data, document.file_type)
        except Exception as exc:
            raise AppError(
                f"Could not read version {version.version_number}: {exc}",
                "EXTRACTION_FAILED",
                422,
            ) from exc
        return "\n\n".join(s.text for s in segments)

    async def compare(
        self,
        org_id: str,
        doc_id: str,
        user_id: str,
        base_id: str | None,
        target_id: str | None,
    ) -> Comparison:
        """Compare ``base`` → ``target``.

        Defaults: target is the newest version, base is the one before it.
        """
        document = await self.documents._get_document(doc_id, org_id)
        await self.documents._check_permission(user_id, document, PermissionLevel.VIEW)
        _, versions = await self.documents.list_versions(doc_id, org_id, user_id)
        by_id = {v.id: v for v in versions}  # newest first

        target = by_id.get(target_id) if target_id else (versions[0] if versions else None)
        if target is None:
            raise AppError("Unknown target version", "VERSION_NOT_FOUND", 404)
        if base_id:
            base = by_id.get(base_id)
        else:
            older = [v for v in versions if v.version_number < target.version_number]
            base = older[0] if older else None
        if base is None:
            raise AppError(
                "This document has only one version, so there is nothing to compare yet.",
                "NOTHING_TO_COMPARE",
                400,
            )
        if base.id == target.id:
            raise AppError("Choose two different versions", "SAME_VERSION", 400)

        base_text, target_text = await asyncio.gather(
            self._text(document, base), self._text(document, target)
        )
        hunks, added, removed, unchanged, truncated = diff_texts(base_text, target_text)
        return Comparison(
            document=document,
            base=base,
            target=target,
            hunks=hunks,
            added=added,
            removed=removed,
            unchanged=unchanged,
            truncated=truncated,
            base_text=base_text,
            target_text=target_text,
        )

    async def summarize(self, comparison: Comparison) -> str:
        """Plain-language summary of what changed between the two versions."""
        if not comparison.hunks:
            return "The two versions contain the same text."
        changes: list[str] = []
        budget = 12_000
        for hunk in comparison.hunks:
            for line in hunk.lines:
                if line.kind == "context":
                    continue
                entry = f"{'+' if line.kind == 'added' else '-'} {line.text}"
                budget -= len(entry)
                if budget < 0:
                    break
                changes.append(entry)
        prompt = (
            f"Document: {comparison.document.title}\n"
            f"Changes from version {comparison.base.version_number} to "
            f"version {comparison.target.version_number} "
            "(lines starting with - were removed, + were added):\n\n" + "\n".join(changes)
        )
        try:
            result = await get_llm_service().chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.1,
                system_prompt=(
                    "Summarise the substantive changes between two versions of a company "
                    "document for a busy employee. Use 3-6 short Markdown bullet points. "
                    "Name concrete values that changed (numbers, dates, names, rules). "
                    "Ignore formatting-only and whitespace changes. Do not speculate."
                ),
            )
        except (LLMUnavailableError, LLMRequestError) as exc:
            raise llm_app_error(exc) from exc
        summary = (result.get("content") or "").strip()
        if not summary:
            raise AppError("The AI engine returned an empty summary.", "LLM_EMPTY_RESPONSE", 502)
        return summary
