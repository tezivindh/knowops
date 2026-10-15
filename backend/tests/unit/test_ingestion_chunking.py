"""Unit tests for token-aware chunking (ingestion)."""

from app.modules.ingestion.chunking import chunk_segments
from app.modules.ingestion.extractors import Segment


async def test_short_segment_yields_single_chunk():
    segments = [
        Segment(
            text="A short policy sentence.",
            page_number=1,
            section_heading="Intro",
        )
    ]

    chunks = chunk_segments(segments, chunk_size=512, overlap=64)

    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "A short policy sentence."
    assert chunks[0].page_number == 1
    assert chunks[0].section_heading == "Intro"
    assert chunks[0].token_count > 0


async def test_long_segment_splits_into_overlapping_windows():
    text = " ".join(f"word{i}" for i in range(2000))
    segments = [Segment(text=text, page_number=3)]

    chunks = chunk_segments(segments, chunk_size=100, overlap=20)

    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # Every window respects the size bound and keeps its segment metadata.
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.page_number == 3 for c in chunks)


async def test_empty_and_whitespace_segments_are_skipped():
    segments = [Segment(text=""), Segment(text="   "), Segment(text="real content")]

    chunks = chunk_segments(segments)

    assert len(chunks) == 1
    assert chunks[0].text == "real content"


async def test_overlap_larger_than_chunk_size_is_clamped():
    text = " ".join(f"token{i}" for i in range(400))
    segments = [Segment(text=text)]

    # Without clamping this would produce a zero/negative step and hang.
    chunks = chunk_segments(segments, chunk_size=50, overlap=80)

    assert len(chunks) > 1
    assert all(c.token_count <= 50 for c in chunks)


def test_documents_may_contain_literal_tokenizer_control_text():
    text = "An example token is <|endoftext|>; preserve it as ordinary text."
    chunks = chunk_segments([Segment(text=text)])
    assert chunks[0].text == text


def test_multilingual_chunks_preserve_original_characters():
    text = "தமிழ் 日本語 😀 हिन्दी " * 2000
    for size, overlap in [(512, 64), (10, 2), (1, 0)]:
        chunks = chunk_segments([Segment(text=text)], chunk_size=size, overlap=overlap)
        assert all("\ufffd" not in chunk.text and chunk.text in text for chunk in chunks)
        if overlap == 0:
            assert "".join(chunk.text for chunk in chunks) == text.replace(" ", "")
