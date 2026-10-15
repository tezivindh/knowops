"""Unit tests for the version diff."""

from app.modules.versioning.service import diff_texts


async def test_identical_texts_have_no_hunks():
    hunks, added, removed, unchanged, truncated = diff_texts("a\nb\n", "a\nb\n")
    assert hunks == [] and added == removed == 0 and unchanged == 2 and not truncated


async def test_changed_line_is_reported_with_context_and_line_numbers():
    base = "Intro\nLeave: 20 days\nOutro"
    target = "Intro\nLeave: 25 days\nOutro\nNew rule"
    hunks, added, removed, _, _ = diff_texts(base, target)
    assert (added, removed) == (2, 1)
    kinds = [(line.kind, line.text) for line in hunks[0].lines]
    assert ("removed", "Leave: 20 days") in kinds
    assert ("added", "Leave: 25 days") in kinds
    assert ("added", "New rule") in kinds
    removed_line = next(line for line in hunks[0].lines if line.kind == "removed")
    assert removed_line.base_line == 2 and removed_line.target_line is None


async def test_blank_lines_are_ignored():
    hunks, *_ = diff_texts("a\n\n\nb", "a\nb")
    assert hunks == []
