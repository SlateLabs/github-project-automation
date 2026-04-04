#!/usr/bin/env python3
"""Rewrite issue-body open questions to DEFERRED-TO-DESIGN when unresolved."""

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

        out_line = line
        if in_open_questions:
            match = QUESTION_RE.match(line)
            if match:
                prefix, content = match.groups()
                text = content.strip()
                if text and "DEFERRED-TO-DESIGN" not in text and "~~" not in text:
                    out_line = f"{prefix}{text} (DEFERRED-TO-DESIGN)"

        out.append(out_line)

    return "\n".join(out)


def main() -> int:
    body = sys.stdin.read()
    sys.stdout.write(rewrite(body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
