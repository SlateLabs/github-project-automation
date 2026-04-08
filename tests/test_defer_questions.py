"""Tests for scripts/defer_open_questions.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from defer_open_questions import rewrite


class TestRewriteBasic:
    def test_empty_input_returns_empty(self):
        assert rewrite("") == ""

    def test_no_open_questions_section_unchanged(self):
        body = "## Summary\n- item one\n- item two"
        assert rewrite(body) == body

    def test_question_items_get_deferred_tag(self):
        body = "## Open Questions\n- How should we handle auth?\n- What about caching?\n"
        result = rewrite(body)
        assert "(DEFERRED-TO-DESIGN)" in result
        assert "How should we handle auth? (DEFERRED-TO-DESIGN)" in result
        assert "What about caching? (DEFERRED-TO-DESIGN)" in result


class TestRewriteAlreadyDeferred:
    def test_already_deferred_not_double_tagged(self):
        body = "## Open Questions\n- How should we handle auth? (DEFERRED-TO-DESIGN)\n"
        result = rewrite(body)
        # Should appear exactly once
        count = result.count("DEFERRED-TO-DESIGN")
        assert count == 1

    def test_mixed_deferred_and_undeferred(self):
        body = (
            "## Open Questions\n"
            "- Already deferred (DEFERRED-TO-DESIGN)\n"
            "- Not yet deferred\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert lines[1] == "- Already deferred (DEFERRED-TO-DESIGN)"
        assert lines[2] == "- Not yet deferred (DEFERRED-TO-DESIGN)"


class TestRewriteStruckThrough:
    def test_struck_through_items_not_tagged(self):
        body = "## Open Questions\n- ~~This was resolved~~\n"
        result = rewrite(body)
        assert "DEFERRED-TO-DESIGN" not in result

    def test_struck_through_mixed_with_active(self):
        body = (
            "## Open Questions\n"
            "- ~~Resolved question~~\n"
            "- Active question\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert "DEFERRED-TO-DESIGN" not in lines[1]
        assert "DEFERRED-TO-DESIGN" in lines[2]


class TestRewriteSectionBoundary:
    def test_content_outside_section_untouched(self):
        body = (
            "## Summary\n"
            "- This should not be tagged\n"
            "## Open Questions\n"
            "- Tag this one\n"
            "## Next Section\n"
            "- Do not tag this\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        # Summary item untouched
        assert lines[1] == "- This should not be tagged"
        # Open Questions item tagged
        assert "DEFERRED-TO-DESIGN" in lines[3]
        # Next Section item untouched
        assert lines[5] == "- Do not tag this"

    def test_section_ends_at_next_heading(self):
        body = (
            "## Open Questions\n"
            "- Question A\n"
            "## Implementation\n"
            "- Step 1\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert "DEFERRED-TO-DESIGN" in lines[1]
        assert "DEFERRED-TO-DESIGN" not in lines[3]

    def test_h1_heading_ends_section(self):
        body = (
            "## Open Questions\n"
            "- Question A\n"
            "# Top Level Heading\n"
            "- Not a question\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert "DEFERRED-TO-DESIGN" in lines[1]
        assert "DEFERRED-TO-DESIGN" not in lines[3]


class TestRewriteListStyles:
    def test_asterisk_list_items(self):
        body = "## Open Questions\n* Question with asterisk\n"
        result = rewrite(body)
        assert "Question with asterisk (DEFERRED-TO-DESIGN)" in result

    def test_indented_items(self):
        body = "## Open Questions\n  - Indented question\n"
        result = rewrite(body)
        assert "Indented question (DEFERRED-TO-DESIGN)" in result

    def test_empty_list_item_not_tagged(self):
        body = "## Open Questions\n- \n- Real question\n"
        result = rewrite(body)
        lines = result.splitlines()
        # Empty item stays as-is
        assert lines[1] == "- "
        assert "DEFERRED-TO-DESIGN" in lines[2]


class TestRewriteNonListContent:
    def test_paragraph_inside_section_untouched(self):
        body = (
            "## Open Questions\n"
            "Some introductory paragraph.\n"
            "- Question item\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert lines[1] == "Some introductory paragraph."
        assert "DEFERRED-TO-DESIGN" in lines[2]

    def test_multiple_open_questions_sections(self):
        """Only the first Open Questions heading triggers the section."""
        body = (
            "## Open Questions\n"
            "- Q1\n"
            "## Other\n"
            "- Not Q\n"
            "## Open Questions\n"
            "- Q2\n"
        )
        result = rewrite(body)
        lines = result.splitlines()
        assert "DEFERRED-TO-DESIGN" in lines[1]  # Q1 tagged
        assert "DEFERRED-TO-DESIGN" not in lines[3]  # Not Q untouched
        assert "DEFERRED-TO-DESIGN" in lines[5]  # Q2 tagged (second section also matches)
