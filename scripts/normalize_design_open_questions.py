#!/usr/bin/env python3
"""Normalize design-discussion open questions for downstream gates."""

from __future__ import annotations

import re
import sys


HEADING_RE = re.compile(r"^#{1,2}\s+")
OPEN_QUESTIONS_RE = re.compile(r"^#{1,2}\s+Open Questions\b")
QUESTION_RE = re.compile(r"^(\s*[-*]\s+)(.*)$")


def rewrite(body: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    in_open_questions = False

    for line in lines:
        if OPEN_QUESTIONS_RE.match(line):
            in_open_questions = True
            out.append(line)
            continue

        if in_open_questions and HEADING_RE.match(line):
            in_open_questions = False

        if in_open_questions and line.strip() == "Resolved in this design:":
            out.append("## Resolved in this design")
            in_open_questions = False
            continue

        out_line = line
        if in_open_questions:
            match = QUESTION_RE.match(line)
            if match:
                prefix, content = match.groups()
                text = content.strip()
                if text and "DEFERRED-TO-PLAN" not in text and "~~" not in text:
                    out_line = f"{prefix}{text} (DEFERRED-TO-PLAN)"

        out.append(out_line)

    return "\n".join(out)


def main() -> int:
    sys.stdout.write(rewrite(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
