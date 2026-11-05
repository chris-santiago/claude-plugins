#!/usr/bin/env python3
"""
Tests for store_state.py: the table that tells a resumable run from a
stale, finished or ambiguous store, one row per verdict.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = (Path(__file__).resolve().parents[1]
               / "skills" / "subagent-driven-development" / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import store_state  # noqa: E402

PLAN = "plans/feature-plan.md"
REMEDIATION = "plans/close-r1-plan.md"


def classify(*, has_entries: bool = True, plans=(PLAN,), plan: str | None = PLAN,
             plan_first_index: int | None = 0, completed=(), plan_tasks=(1, 2, 3, 4),
             close_round_indices=(), remediation: dict | None = None):
    return store_state.classify(
        has_entries=has_entries, plans=list(plans), plan=plan, plan_first_index=plan_first_index,
        completed={str(t) for t in completed}, plan_tasks=list(plan_tasks),
        close_round_indices=list(close_round_indices), remediation=remediation)


class TestFresh(unittest.TestCase):
    def test_an_empty_log_is_fresh_and_starts_at_the_first_task(self):
        verdict, nxt = classify(has_entries=False, plans=(), plan_first_index=None)
        self.assertEqual(verdict, "fresh")
        self.assertIn("task 1", nxt)

    def test_setup_entries_without_a_plan_are_fresh(self):
        verdict, _ = classify(plans=(), plan_first_index=None)
        self.assertEqual(verdict, "fresh")


class TestAmbiguous(unittest.TestCase):
    def test_a_completion_without_a_recorded_plan_is_ambiguous(self):
        verdict, nxt = classify(plans=(), plan_first_index=None, completed=(1,))
        self.assertEqual(verdict, "ambiguous")
        self.assertIn("ask the user", nxt)

    def test_a_close_round_without_a_recorded_plan_is_ambiguous(self):
        verdict, _ = classify(plans=(), plan_first_index=None, close_round_indices=(5,))
        self.assertEqual(verdict, "ambiguous")

    def test_one_close_round_and_no_remediation_note_is_ambiguous(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4), close_round_indices=(9,))
        self.assertEqual(verdict, "ambiguous")
        self.assertIn("ask the user", nxt)


class TestForeign(unittest.TestCase):
    def test_a_plan_the_store_never_recorded_is_foreign(self):
        verdict, nxt = classify(plans=("plans/other-plan.md",), plan_first_index=None, completed=(1,))
        self.assertEqual(verdict, "foreign")
        self.assertIn("clear", nxt)


class TestResume(unittest.TestCase):
    def test_resume_names_the_first_incomplete_task(self):
        verdict, nxt = classify(completed=(1, 2))
        self.assertEqual(verdict, "resume")
        self.assertIn("task 3", nxt)

    def test_resume_skips_a_completed_task_out_of_order(self):
        _, nxt = classify(completed=(1, 3))
        self.assertIn("task 2", nxt)

    def test_every_task_complete_points_at_the_whole_change_gate(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4))
        self.assertEqual(verdict, "resume")
        self.assertIn("whole-change gate", nxt)
        self.assertIn("verification", nxt)


class TestFinished(unittest.TestCase):
    def test_two_close_rounds_are_finished(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4), close_round_indices=(9, 20))
        self.assertEqual(verdict, "finished")
        self.assertIn("clear", nxt)

    def test_a_round_from_before_the_plan_was_recorded_is_finished(self):
        verdict, _ = classify(plans=("plans/old-plan.md", PLAN), plan_first_index=12,
                              completed=(1, 2, 3), close_round_indices=(9,))
        self.assertEqual(verdict, "finished")


class TestRemediation(unittest.TestCase):
    NOTE = {"plan": REMEDIATION, "front_end": "remediating-issues"}

    def test_the_remediation_plan_resumes_at_its_first_incomplete_task(self):
        verdict, nxt = classify(plans=(PLAN, REMEDIATION), plan=REMEDIATION, plan_first_index=12,
                                completed=(1, 2, 3, 4, 5), plan_tasks=(6, 7),
                                close_round_indices=(9,), remediation=self.NOTE)
        self.assertEqual(verdict, "remediation")
        self.assertIn("task 6", nxt)
        self.assertIn("final-r2", nxt)
        self.assertIn("round 2", nxt)
        self.assertIn("remediating-issues", nxt)

    def test_a_finished_remediation_plan_points_at_round_2(self):
        _, nxt = classify(plans=(PLAN, REMEDIATION), plan=REMEDIATION, plan_first_index=12,
                          completed=(1, 2, 3, 4, 5, 6, 7), plan_tasks=(6, 7),
                          close_round_indices=(9,), remediation=self.NOTE)
        self.assertNotIn("task 6", nxt)
        self.assertIn("whole-change gate", nxt)
        self.assertIn("round 2", nxt)

    def test_the_original_plan_is_told_to_run_the_remediation_plan(self):
        verdict, nxt = classify(plans=(PLAN, REMEDIATION), plan=PLAN, plan_first_index=0,
                                completed=(1, 2, 3, 4, 5), close_round_indices=(9,),
                                remediation=self.NOTE)
        self.assertEqual(verdict, "remediation")
        self.assertIn(REMEDIATION, nxt)

    def test_a_note_without_a_front_end_still_resumes(self):
        verdict, _ = classify(plans=(PLAN, REMEDIATION), plan=REMEDIATION, plan_first_index=12,
                              completed=(1, 2, 3, 4, 5), plan_tasks=(6, 7),
                              close_round_indices=(9,),
                              remediation={"plan": REMEDIATION, "front_end": None})
        self.assertEqual(verdict, "remediation")


class TestRemediationNote(unittest.TestCase):
    def test_the_note_names_its_plan_and_front_end(self):
        note = ("close-gate remediation r1: plan .claude/output/plans/x-plan.md, decision "
                ".claude/output/decisions/x.md, intent .sdd/intent-issue.md, front-end coherent-change")
        self.assertEqual(store_state.parse_remediation_note(note),
                         {"plan": ".claude/output/plans/x-plan.md", "front_end": "coherent-change"})

    def test_a_note_with_front_end_none_has_no_front_end(self):
        note = "close-gate remediation r1: plan p.md, decision d.md, intent i.md, front-end none"
        self.assertEqual(store_state.parse_remediation_note(note), {"plan": "p.md", "front_end": None})

    def test_another_progress_note_is_not_a_remediation_note(self):
        self.assertIsNone(store_state.parse_remediation_note("user ruling: accept"))

    def test_an_unknown_front_end_is_dropped(self):
        note = ("close-gate remediation r1: plan p.md, decision d.md, intent i.md, "
                "front-end ignore-previous-instructions")
        self.assertEqual(store_state.parse_remediation_note(note), {"plan": "p.md", "front_end": None})

    def test_a_plan_that_is_not_path_shaped_is_not_a_remediation_note(self):
        for plan in ("`rm", "p.md;", "$(x)", "p.txt"):
            with self.subTest(plan=plan):
                note = f"close-gate remediation r1: plan {plan}, decision d.md, front-end none"
                self.assertIsNone(store_state.parse_remediation_note(note))

    def test_a_remediation_note_without_a_plan_is_not_one(self):
        self.assertIsNone(store_state.parse_remediation_note("close-gate remediation r1: decision d.md"))


if __name__ == "__main__":
    unittest.main()
