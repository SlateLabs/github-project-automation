from __future__ import annotations

import textwrap
import unittest

from scripts.generate_design_discussion import build_body


class GenerateDesignDiscussionTests(unittest.TestCase):
    def test_builds_substantive_discussion_from_issue(self) -> None:
        issue_body = textwrap.dedent(
            """\
            ## Summary

            Design and implement the operator-in-the-loop end-to-end orchestration model.

            ## Scope

            - Define the canonical state machine
            - Define the deployment contract required before operator review begins

            ## Acceptance Criteria

            - The system can produce a review-ready implementation
            - Operator approval is machine-detectable

            ## Constraints

            - Keep the GitHub Project Status field coarse

            ## Proposed State Model

            ### Coarse project statuses

            - Backlog
            - Ready

            ## Open Questions

            - What is the smallest acceptable deployed target? (DEFERRED-TO-DESIGN)
            """
        )

        body = build_body(
            "Design and implement the operator-in-the-loop end-to-end orchestration model",
            33,
            "SlateLabs/github-project-automation",
            issue_body,
        )

        self.assertIn("## Summary", body)
        self.assertIn("Define the canonical state machine", body)
        self.assertIn("## Proposed Approach", body)
        self.assertIn("### Coarse project statuses", body)
        self.assertIn("DEFERRED-TO-PLAN", body)
        self.assertNotIn("Question 1", body)
        self.assertNotIn("Goal 1", body)


if __name__ == "__main__":
    unittest.main()
