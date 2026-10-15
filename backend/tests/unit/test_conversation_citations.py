"""Unit tests for citation-marker parsing and renumbering (conversations)."""

from app.modules.conversations.service import (
    _referenced_indexes,
    _renumber_citations,
    _strip_citations,
)


async def test_ascii_brackets_are_parsed_in_order():
    assert _referenced_indexes("See [1] and then [2].", 3) == [1, 2]


async def test_fullwidth_brackets_are_parsed():
    # Models (e.g. gpt-oss) sometimes emit CJK full-width brackets.
    assert _referenced_indexes("据【2】和【1】。", 3) == [2, 1]


async def test_grouped_markers_are_parsed():
    assert _referenced_indexes("Both agree [3, 1].", 3) == [3, 1]


async def test_duplicates_and_out_of_range_are_ignored():
    assert _referenced_indexes("[1][1][9]", 2) == [1]


async def test_no_markers_means_no_citations():
    # Attaching an uncited source would present unverified provenance.
    assert _referenced_indexes("An answer with no markers.", 3) == []


async def test_no_sources_means_no_citations():
    assert _referenced_indexes("anything [1]", 0) == []


async def test_renumbering_matches_stored_citation_order():
    answer = "Leave is 20 days [3]. Carry-over is capped [1, 3]. Bogus [9]."
    referenced = _referenced_indexes(answer, 3)
    mapping = {source: i for i, source in enumerate(referenced, start=1)}
    assert _renumber_citations(answer, mapping) == (
        "Leave is 20 days [1]. Carry-over is capped [2][1]. Bogus."
    )


async def test_fullwidth_markers_are_normalised():
    assert _renumber_citations("据【2】。", {2: 1}) == "据[1]。"


async def test_strip_citations_for_history():
    assert _strip_citations("Twenty days [1]. Capped [2][3].") == "Twenty days. Capped."
