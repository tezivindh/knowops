"""
Ingestion — text extraction.

Converts raw file bytes into ordered text segments, preserving page numbers
(PDF) and section headings (Markdown) so downstream citations can point to
the right place.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

import chardet
import structlog

logger = structlog.get_logger()


@dataclass
class Segment:
    """A contiguous block of extracted text with optional location metadata."""

    text: str
    page_number: int | None = None
    section_heading: str | None = None


def extract_segments(data: bytes, file_type: str) -> list[Segment]:
    """Extract text segments from raw bytes based on file type."""
    ext = file_type.lower().lstrip(".")
    if ext == "pdf":
        return _extract_pdf(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext == "md":
        return _extract_markdown(_decode(data))
    if ext in ("txt", "csv"):
        return _extract_plain(_decode(data))
    raise ValueError(f"Unsupported file type for extraction: .{ext}")


def _decode(data: bytes) -> str:
    """Decode bytes to text, detecting encoding when necessary."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        detected = chardet.detect(data)
        encoding = detected.get("encoding") or "utf-8"
        logger.info("Non-UTF8 document detected", encoding=encoding)
        return data.decode(encoding, errors="replace")


def _extract_pdf(data: bytes) -> list[Segment]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    segments: list[Segment] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(Segment(text=text, page_number=index))
    return segments


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(element: Any) -> str:
    """All text under an element, in order — including text boxes, which
    python-docx's ``Paragraph.text`` skips."""
    parts: list[str] = []
    for node in element.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _extract_docx(data: bytes) -> list[Segment]:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
            raise ValueError("DOCX exceeds the decompressed processing limit")
    doc = DocxDocument(io.BytesIO(data))
    segments: list[Segment] = []
    current_heading: str | None = None
    headings: list[str] = []
    buffer: list[str] = []
    has_body = False

    def flush() -> None:
        nonlocal has_body
        text = "\n".join(buffer).strip()
        # Skip sections that are only a heading with nothing under it.
        if text and has_body:
            segments.append(Segment(text=text, section_heading=current_heading))
        buffer.clear()
        has_body = False

    # Walk the body in reading order so tables stay inside their section.
    for child in doc.element.body.iterchildren():
        if child.tag == f"{_W}p":
            para = Paragraph(child, doc)
            text = _docx_text(child)
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            if style.startswith("heading") or style == "title":
                flush()
                current_heading = text
                headings.append(text)
                buffer.append(text)
            else:
                buffer.append(text)
                has_body = True
        elif child.tag == f"{_W}tbl":
            rows = []
            for row in Table(child, doc).rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = _docx_text(cell._tc)
                    # Merged cells repeat across the row; keep one copy.
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                buffer.append("\n".join(rows))
                has_body = True
    flush()

    # Headers and footers sometimes carry the only text (e.g. a policy number).
    seen: set[str] = set()
    extra: list[str] = []
    for section in doc.sections:
        for part in (section.header, section.footer):
            if part.is_linked_to_previous:
                continue
            text = _docx_text(part._element)
            if text and text not in seen:
                seen.add(text)
                extra.append(text)
    if extra:
        segments.append(Segment(text="\n".join(extra), section_heading="Header and footer"))

    # A document made only of headings still has something worth indexing.
    if not segments and headings:
        segments.append(Segment(text="\n".join(headings)))
    return segments


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _extract_markdown(text: str) -> list[Segment]:
    """Split Markdown into sections keyed by their heading."""
    segments: list[Segment] = []
    current_heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        # A heading with nothing under it carries no answerable content.
        if body and not _HEADING_RE.fullmatch(body):
            segments.append(Segment(text=body, section_heading=current_heading))
        buffer.clear()

    for line in text.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            flush()
            current_heading = match.group(2).strip()
            buffer.append(line.strip())
        else:
            buffer.append(line)
    flush()

    if not segments and text.strip():
        segments.append(Segment(text=text.strip()))
    return segments


def _extract_plain(text: str) -> list[Segment]:
    text = text.strip()
    return [Segment(text=text)] if text else []
