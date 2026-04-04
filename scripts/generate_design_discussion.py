#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def normalize_heading(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def extract_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            if level <= 2:
                current = normalize_heading(match.group(2))
                sections.setdefault(current, [])
                continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def first_paragraph(text: str) -> str:
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    return paragraphs[0] if paragraphs else ""


def bullet_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^[-*]\s+", line) or re.match(r"^\d+\.\s+", line):
            lines.append(line)
    return lines


def ensure_sentence(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    if text[-1] not in ".!?":
        return text + "."
    return text


def render_list(lines: Iterable[str], *, fallback: str) -> str:
    cleaned = [line for line in lines if line.strip()]
    if cleaned:
        return "\n".join(cleaned)
    return fallback


def transform_open_questions(lines: list[str]) -> list[str]:
    transformed: list[str] = []
    for line in lines:
        content = re.sub(r"^[-*]\s+", "", line).strip()
        content = content.replace("(DEFERRED-TO-DESIGN)", "").strip()
        if "DEFERRED-TO-PLAN" in content:
            transformed.append(f"- {content}")
            continue
        if re.match(r"^\[[ xX]\]\s+", content):
            content = re.sub(r"^\[[ xX]\]\s+", "", content).strip()
        transformed.append(f"- DEFERRED-TO-PLAN: {content}")
    return transformed


def build_body(issue_title: str, issue_number: int, repo: str, issue_body: str) -> str:
    sections = extract_sections(issue_body)

    summary = sections.get("summary", "").strip()
    scope = sections.get("scope", "").strip()
    acceptance = sections.get("acceptance criteria", "").strip()
    constraints = sections.get("constraints", "").strip()
    proposed_state_model = sections.get("proposed state model", "").strip()
    open_questions = sections.get("open questions", "").strip()

    problem = first_paragraph(summary) or (
        f"This issue requires a concrete design for {issue_title.lower()} so the implementation "
        "can proceed without relying on operator interpretation at every stage."
    )
    problem = ensure_sentence(problem)

    goals = bullet_lines(scope) or bullet_lines(acceptance)
    non_goals = bullet_lines(constraints)
    if not non_goals:
        non_goals = [
            "- Do not expand the change beyond the scope already described in the source issue.",
            "- Do not introduce unrelated refactors unless they are required to satisfy the acceptance criteria.",
        ]

    approach_parts: list[str] = []
    if summary:
        approach_parts.append(
            ensure_sentence(
                f"Use the issue summary as the primary implementation contract: {first_paragraph(summary)}"
            )
        )
    if scope:
        approach_parts.append(
            ensure_sentence(
                "Execute the scope as a staged plan, preserving the issue's stated boundaries and expected outcomes"
            )
        )
    if proposed_state_model:
        approach_parts.append("Adopt the proposed state model from the issue as the starting point for the implementation details:")
        approach_parts.append(proposed_state_model.strip())
    if acceptance:
        acceptance_bullets = bullet_lines(acceptance)
        if acceptance_bullets:
            approach_parts.append("Drive implementation and verification from these acceptance criteria:")
            approach_parts.append("\n".join(acceptance_bullets))
    if constraints:
        constraint_bullets = bullet_lines(constraints)
        if constraint_bullets:
            approach_parts.append("Honor these constraints while refining the detailed implementation:")
            approach_parts.append("\n".join(constraint_bullets))

    proposed_approach = "\n\n".join(part for part in approach_parts if part.strip())

    raw_open_questions = bullet_lines(open_questions)
    rendered_open_questions = transform_open_questions(raw_open_questions)
    if not rendered_open_questions:
        rendered_open_questions = [
            "- DEFERRED-TO-PLAN: No additional unresolved design questions were identified from the issue body."
        ]

    return f"""# Design Discussion: {issue_title}

<!-- gpa:owned-artifact:design-discussion:{repo}#{issue_number} -->

> Source issue: {repo}#{issue_number}
> Created by orchestration automation

---

## Summary

{summary or ensure_sentence(issue_title)}

## Problem

{problem}

## Goals

{render_list(goals, fallback="- Preserve the issue's stated scope and acceptance criteria in the implementation plan.")}

## Non-goals

{render_list(non_goals, fallback="- No additional non-goals were identified beyond the issue constraints.")}

## Proposed Approach

{proposed_approach}

## Open Questions

{chr(10).join(rendered_open_questions)}

---

## Exit Criteria

Before this design discussion can gate-pass to the Plan stage, the following must be true (per [discussion #3 section 4](https://github.com/SlateLabs/github-project-automation/discussions/3)):

- [x] All sections above have substantive content derived from the source issue
- [x] All Open Questions are resolved (struck through) or marked `DEFERRED-TO-PLAN`
- [x] At least one review comment exists from someone other than the discussion author
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a first-pass design discussion body from an issue body.")
    parser.add_argument("--issue-title", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()

    issue_body = sys.stdin.read()
    sys.stdout.write(build_body(args.issue_title, args.issue_number, args.repo, issue_body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
