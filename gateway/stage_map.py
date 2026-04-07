from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_STAGE_MAP_PATH = Path(__file__).resolve().parent.parent / "config" / "orchestration-stage-map.json"
_STAGE_MAP = json.loads(_STAGE_MAP_PATH.read_text())

REQUESTED_STAGE = "kickoff"
DISPATCH_EVENT_TYPE = "orchestration-start"
DISPATCH_RETRY_BACKOFFS = (1.0, 4.0, 16.0)
OPERATOR_COMMANDS: dict[str, str] = _STAGE_MAP["operator_commands"]
MANUAL_STAGES: tuple[str, ...] = tuple(_STAGE_MAP["manual_stages"])


def resolve_next_stage(
    *,
    requested_stage: str,
    feedback_source: str = "",
    feedback_no_progress: bool = False,
    review_disposition: str = "",
    review_next_stage: str = "",
) -> dict[str, str]:
    progression: dict[str, Any] = _STAGE_MAP["auto_progression"]
    if requested_stage == "execution":
        if feedback_source == "operator" and feedback_no_progress:
            return progression["execution"]["operator_feedback_no_progress"]
        return progression["execution"]["default"]

    if requested_stage == "agent-review":
        if review_next_stage:
            allowed = progression["agent-review"]["allowed_next_stages"]
            if review_next_stage not in allowed:
                raise ValueError(f"Unknown review_next_stage '{review_next_stage}'")
            return {
                "next_stage": review_next_stage,
                "target_status": allowed[review_next_stage],
            }
        mapping = progression["agent-review"]["default_disposition"]
        if review_disposition not in mapping:
            raise ValueError(f"Unknown or missing review disposition '{review_disposition}'")
        return mapping[review_disposition]

    if requested_stage not in progression:
        raise ValueError(f"Unknown requested_stage '{requested_stage}'")
    return progression[requested_stage]


def default_reason_codes(next_stage: str) -> list[str]:
    codes = ["stage_gate_passed"]
    if next_stage:
        codes.append("stage_handoff_queued")
    return codes
