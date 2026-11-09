#!/usr/bin/env python3
"""
Tests for store_state.py: the table that tells a resumable run from a
closing, stale, finished or ambiguous store, one row per verdict.

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


def classify(*, has_entries: bool = True, plans=(PLAN,), plan: str | None = PLAN,
             plan_first_index: int | None = 0, completed=(), plan_tasks=(1, 2, 3, 4),
             close_start_index: int | None = None, close_step: str | None = None):
    return store_state.classify(
        has_entries=has_entries, plans=list(plans), plan=plan, plan_first_index=plan_first_index,
        completed={str(t) for t in completed}, plan_tasks=list(plan_tasks),
        close_start_index=close_start_index, close_step=close_step)


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

    def test_a_close_without_a_recorded_plan_is_ambiguous(self):
        verdict, _ = classify(plans=(), plan_first_index=None, close_start_index=5)
        self.assertEqual(verdict, "ambiguous")


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

    def test_an_unknown_task_list_never_reads_as_complete(self):
        verdict, nxt = classify(completed=(1,), plan_tasks=())
        self.assertEqual(verdict, "resume")
        self.assertNotIn("complete", nxt)
        self.assertIn("couldn't read", nxt)

    def test_every_task_complete_points_at_the_whole_change_gate(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4))
        self.assertEqual(verdict, "resume")
        self.assertIn("whole-change gate", nxt)
        self.assertIn("verification", nxt)


class TestClosing(unittest.TestCase):
    def test_a_started_close_not_yet_done_is_closing_and_names_its_step(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4), close_start_index=9, close_step="patch")
        self.assertEqual(verdict, "closing")
        self.assertIn("triage --task close", nxt)
        self.assertIn("patch", nxt)

    def test_a_close_with_no_triage_yet_says_to_dispatch_the_gates(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4), close_start_index=9)
        self.assertEqual(verdict, "closing")
        self.assertIn("gates", nxt)


class TestFinished(unittest.TestCase):
    def test_a_close_that_reached_done_is_finished(self):
        verdict, nxt = classify(completed=(1, 2, 3, 4), close_start_index=9, close_step="done")
        self.assertEqual(verdict, "finished")
        self.assertIn("clear", nxt)

    def test_a_close_from_before_the_plan_was_recorded_is_finished(self):
        verdict, _ = classify(plans=("plans/old-plan.md", PLAN), plan_first_index=12,
                              completed=(1, 2, 3), close_start_index=9, close_step="patch")
        self.assertEqual(verdict, "finished")


class TestRetired(unittest.TestCase):
    def test_there_is_no_remediation_verdict(self):
        self.assertNotIn("remediation", store_state.Verdict.__args__)


if __name__ == "__main__":
    unittest.main()
