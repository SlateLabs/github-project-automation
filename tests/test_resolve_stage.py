"""Tests for scripts/resolve_orchestration_stage.py CLI."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from resolve_orchestration_stage import main


def _run_main(*argv: str) -> str:
    """Run main() with patched argv and capture stdout."""
    captured = StringIO()
    with patch("sys.argv", ["prog", *argv]), patch("sys.stdout", captured):
        main()
    return captured.getvalue()


# ---------------------------------------------------------------------------
# manual-stages subcommand
# ---------------------------------------------------------------------------


class TestManualStages:
    def test_lists_manual_stages(self):
        output = _run_main("manual-stages")
        lines = output.strip().splitlines()
        assert len(lines) > 0
        # all entries should be non-empty stage names
        assert all(line.strip() for line in lines)

    def test_known_stages_present(self):
        output = _run_main("manual-stages")
        # At minimum we expect some well-known stage names
        for stage in ("design", "plan", "execution"):
            assert stage in output


# ---------------------------------------------------------------------------
# valid-stages subcommand
# ---------------------------------------------------------------------------


class TestValidStages:
    def test_includes_kickoff(self):
        output = _run_main("valid-stages")
        lines = output.strip().splitlines()
        assert "kickoff" in lines

    def test_superset_of_manual(self):
        manual = set(_run_main("manual-stages").strip().splitlines())
        valid = set(_run_main("valid-stages").strip().splitlines())
        assert manual.issubset(valid)


# ---------------------------------------------------------------------------
# resolve subcommand
# ---------------------------------------------------------------------------


class TestResolve:
    def test_kickoff_returns_json_with_next_stage(self):
        output = _run_main("resolve", "--requested-stage=kickoff")
        result = json.loads(output)
        assert "next_stage" in result

    def test_execution_default(self):
        output = _run_main("resolve", "--requested-stage=execution")
        result = json.loads(output)
        assert "next_stage" in result

    def test_execution_operator_no_progress(self):
        output = _run_main(
            "resolve",
            "--requested-stage=execution",
            "--feedback-source=operator",
            "--feedback-no-progress",
        )
        result = json.loads(output)
        assert "next_stage" in result

    def test_unknown_stage_raises(self):
        with pytest.raises((SystemExit, ValueError)):
            _run_main("resolve", "--requested-stage=nonexistent-stage")


# ---------------------------------------------------------------------------
# reason-codes subcommand
# ---------------------------------------------------------------------------


class TestReasonCodes:
    def test_empty_next_stage(self):
        output = _run_main("reason-codes", "--next-stage=")
        codes = json.loads(output)
        assert isinstance(codes, list)
        assert "stage_gate_passed" in codes

    def test_with_next_stage(self):
        output = _run_main("reason-codes", "--next-stage=clarification")
        codes = json.loads(output)
        assert isinstance(codes, list)
        assert "stage_gate_passed" in codes
        assert "stage_handoff_queued" in codes

    def test_default_next_stage(self):
        output = _run_main("reason-codes")
        codes = json.loads(output)
        assert isinstance(codes, list)
        # With empty default, should only have stage_gate_passed
        assert "stage_gate_passed" in codes
