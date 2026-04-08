"""Tests for gateway.commands — operator command parsing."""

from __future__ import annotations

import pytest

from gateway.commands import parse_operator_command


class TestParseOperatorCommand:

    def test_feedback_command_extracts_body(self):
        result = parse_operator_command("gpa:feedback please fix the tests")
        assert result == ("execution", "please fix the tests")

    def test_feedback_command_strips_leading_whitespace(self):
        result = parse_operator_command("  gpa:feedback fix it")
        assert result == ("execution", "fix it")

    def test_feedback_command_empty_body(self):
        result = parse_operator_command("gpa:feedback")
        assert result == ("execution", "")

    def test_approve_command(self):
        result = parse_operator_command("gpa:approve")
        assert result == ("merge", "")

    def test_approve_ignores_trailing_text(self):
        result = parse_operator_command("gpa:approve looks good")
        assert result == ("merge", "")

    def test_case_insensitive(self):
        result = parse_operator_command("GPA:FEEDBACK do this")
        assert result == ("execution", "do this")

    def test_non_command_returns_none(self):
        assert parse_operator_command("just a normal comment") is None

    def test_empty_string_returns_none(self):
        assert parse_operator_command("") is None

    def test_partial_prefix_returns_none(self):
        assert parse_operator_command("gpa:unknown stuff") is None
