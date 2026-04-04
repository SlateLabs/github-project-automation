from __future__ import annotations

import unittest

from scripts.normalize_design_open_questions import rewrite


class NormalizeDesignOpenQuestionsTests(unittest.TestCase):
    def test_marks_unresolved_questions_as_deferred(self) -> None:
        body = """## Open Questions

- Question 1
- Question 2 (DEFERRED-TO-PLAN)
"""
        rewritten = rewrite(body)
        self.assertIn("- Question 1 (DEFERRED-TO-PLAN)", rewritten)
        self.assertIn("- Question 2 (DEFERRED-TO-PLAN)", rewritten)

    def test_promotes_resolved_block_to_new_heading(self) -> None:
        body = """## Open Questions

- Question 1 (DEFERRED-TO-PLAN)

Resolved in this design:
- Answer 1

## Exit Criteria
"""
        rewritten = rewrite(body)
        self.assertIn("## Resolved in this design", rewritten)
        self.assertNotIn("Resolved in this design:", rewritten)
        self.assertIn("- Answer 1", rewritten)


if __name__ == "__main__":
    unittest.main()
