from __future__ import annotations

from gateway.stage_map import OPERATOR_COMMANDS


def parse_operator_command(body: str) -> tuple[str, str] | None:
    trimmed = body.lstrip()
    lowered = trimmed.lower()
    for prefix, stage in OPERATOR_COMMANDS.items():
        if lowered.startswith(prefix):
            feedback = trimmed[len(prefix):].strip() if stage == "execution" else ""
            return (stage, feedback)
    return None
