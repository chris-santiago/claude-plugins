#!/usr/bin/env python3
"""
Tests for triage.py: the tier matrix and the step each review state leads
to, replayed as the round sequences a real run produces.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = (Path(__file__).resolve().parents[1]
               / "skills" / "subagent-driven-development" / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import triage  # noqa: E402


def finding(fid: str, severity: int = 3, reach: str = "local", *, source: str = "task-1-spec-reviewer",
            gate: bool = False, recurring: bool = False, introduced: bool = False) -> dict:
    return {"id": fid, "source": source, "gate": gate, "severity": severity, "reach": reach,
            "rule": f"rule of {fid}", "recurring": recurring, "introduced": introduced}


def derive(findings=(), *, prior=(), root_causes=(), reach_raised=(), answers=None, waived=(),
           ruled=False, undelivered_note=False, model: str | None = "sonnet",
           file_candidates=()) -> dict:
    return triage.derive(findings=list(findings), root_causes=list(root_causes),
                         reach_raised=set(reach_raised), answers=dict(answers or {}),
                         waived=set(waived), prior=list(prior), ruled=ruled,
                         undelivered_note=undelivered_note, model=model,
                         file_candidates=list(file_candidates))


def step(kind: str, findings=(), **extra) -> dict:
    """A prior triage entry, as `derive` would have written it."""
    return {"kind": kind, "findings": [{"id": f["id"], "tier": t, "rule": f["rule"]}
                                       for f, t in findings], **extra}


class TestTiers(unittest.TestCase):
    def test_each_cell_of_the_matrix(self):
        cases = {(1, "local"): "note", (2, "class"): "note", (2, "contract"): "defer",
                 (3, "local"): "patch", (5, "class"): "patch", (3, "contract"): "holistic"}
        for (severity, reach), expected in cases.items():
            with self.subTest(severity=severity, reach=reach):
                self.assertEqual(triage.tier(finding("f", severity, reach), set()), expected)

    def test_flags_never_change_a_tier(self):
        self.assertEqual(triage.tier(finding("f", recurring=True, introduced=True), set()), "patch")

    def test_a_reach_the_coder_raised_is_contract(self):
        self.assertEqual(triage.tier(finding("f"), {"f"}), "holistic")


class TestFirstReview(unittest.TestCase):
    def test_a_local_s3_starts_a_patch_rechecked_by_its_raiser(self):
        entry = derive([finding("a")])
        self.assertEqual((entry["kind"], entry["round"], entry["recheck"]), ("patch", 1, "raising"))
        self.assertEqual([f["id"] for f in entry["findings"]], ["a"])

    def test_only_gate_findings_are_rechecked_by_the_gate(self):
        entry = derive([finding("g", source="task-1-gate", gate=True)])
        self.assertEqual((entry["kind"], entry["recheck"]), ("patch", "gate"))

    def test_a_contract_finding_starts_a_holistic_round_for_every_reviewer(self):
        entry = derive([finding("a"), finding("c", reach="contract")])
        self.assertEqual((entry["kind"], entry["recheck"]), ("holistic", "all"))

    def test_a_lone_root_cause_starts_a_holistic_round(self):
        entry = derive(root_causes=["task-1-python-coder#concerns[ab]"])
        self.assertEqual(entry["kind"], "holistic")

    def test_notes_alone_get_one_polish_with_no_recheck(self):
        entry = derive([finding("n", severity=1)])
        self.assertEqual((entry["kind"], entry["recheck"]), ("polish", "none"))

    def test_notes_ride_along_in_a_fix_round(self):
        entry = derive([finding("a"), finding("n", severity=2)])
        self.assertEqual({f["id"]: f["tier"] for f in entry["findings"]}, {"a": "patch", "n": "note"})

    def test_a_clean_review_is_done(self):
        self.assertEqual(derive()["kind"], "done")

    def test_an_undelivered_note_gets_a_polish(self):
        self.assertEqual(derive(undelivered_note=True)["kind"], "polish")


class TestLaterRounds(unittest.TestCase):
    a, c = finding("a"), finding("c", reach="contract")

    def test_a_local_s3_after_a_patch_gets_a_second_patch(self):
        entry = derive([finding("b", recurring=True)], prior=[step("patch", [(self.a, "patch")])])
        self.assertEqual((entry["kind"], entry["round"]), ("patch", 2))

    def test_a_contract_finding_after_a_patch_goes_holistic(self):
        entry = derive([self.c], prior=[step("patch", [(self.a, "patch")])])
        self.assertEqual((entry["kind"], entry["round"]), ("holistic", 2))

    def test_a_new_local_bug_after_a_holistic_round_gets_a_patch(self):
        entry = derive([finding("b")], prior=[step("holistic", [(self.c, "holistic")])])
        self.assertEqual((entry["kind"], entry["round"]), ("patch", 2))

    def test_open_work_after_two_rounds_escalates(self):
        prior = [step("patch", [(self.a, "patch")]), step("patch", [(self.a, "patch")])]
        entry = derive([self.a], prior=prior)
        self.assertEqual((entry["kind"], entry["recheck"]), ("escalate", "none"))

    def test_an_escalation_without_a_new_ruling_stays_escalated(self):
        prior = [step("patch", [(self.a, "patch")]), step("patch", [(self.a, "patch")]),
                 step("escalate", [(self.a, "patch")])]
        self.assertEqual(derive([self.a], prior=prior)["kind"], "escalate")

    def test_a_ruling_after_escalation_starts_a_ruling_round_over_unwaived_findings(self):
        b = finding("b")
        prior = [step("patch", [(self.a, "patch")]), step("patch", [(self.a, "patch")]),
                 step("escalate", [(self.a, "patch"), (b, "patch")])]
        entry = derive([self.a, b], prior=prior, ruled=True, waived={"b"})
        self.assertEqual((entry["kind"], entry["recheck"]), ("ruling", "raising"))
        self.assertEqual([f["id"] for f in entry["findings"]], ["a"])

    def test_a_ruling_round_that_leaves_open_work_escalates_again(self):
        prior = [step("patch", [(self.a, "patch")]), step("patch", [(self.a, "patch")]),
                 step("escalate", [(self.a, "patch")]), step("ruling", [(self.a, "patch")])]
        self.assertEqual(derive([self.a], prior=prior)["kind"], "escalate")

    def test_a_failed_ruling_round_escalates_even_under_two_fix_rounds(self):
        prior = [step("patch", [(self.a, "patch")]), step("escalate", [(self.a, "patch")]),
                 step("ruling", [(self.a, "patch")])]
        self.assertEqual(derive([self.a], prior=prior)["kind"], "escalate")

    def test_the_ruling_already_acted_on_does_not_start_another_ruling_round(self):
        prior = [step("patch", [(self.a, "patch")]), step("patch", [(self.a, "patch")]),
                 step("escalate", [(self.a, "patch")]), step("ruling", [(self.a, "patch")])]
        self.assertEqual(derive([self.a], prior=prior, ruled=True)["kind"], "escalate")

    def test_a_ruling_round_does_not_count_toward_the_bound(self):
        prior = [step("patch", [(self.a, "patch")]), step("escalate", [(self.a, "patch")])]
        entry = derive([self.a], prior=prior, ruled=True)
        self.assertEqual((entry["kind"], entry["round"]), ("ruling", 1))

    def test_an_override_ruled_after_done_starts_a_ruling_round_the_spec_reviewer_rechecks(self):
        # The user overrode an open behavior choice: nothing is raised, but
        # the coder must implement the ruling and the spec reviewer check it.
        prior = [step("patch", [(self.a, "patch")]), step("done")]
        entry = derive(prior=prior, ruled=True)
        self.assertEqual((entry["kind"], entry["round"], entry["recheck"], entry["findings"]),
                         ("ruling", 1, "spec", []))

    def test_a_ruling_round_with_findings_is_still_rechecked_by_their_raisers(self):
        prior = [step("escalate", [(self.a, "patch")])]
        self.assertEqual(derive([self.a], prior=prior, ruled=True)["recheck"], "raising")

    def test_a_ruling_after_a_fix_round_waits_for_its_recheck(self):
        # A ruling logged mid-round is acted on once triage reaches done or escalate.
        entry = derive([self.a], prior=[step("patch", [(self.a, "patch")])], ruled=True)
        self.assertEqual(entry["kind"], "patch")

    def test_a_failed_recheck_after_an_override_returns_to_the_user(self):
        prior = [step("done"), step("ruling")]
        self.assertEqual(derive([self.a], prior=prior)["kind"], "escalate")

    def test_notes_already_sent_to_a_coder_are_not_open_again(self):
        n = finding("n", severity=1)
        self.assertEqual(derive([n], prior=[step("patch", [(self.a, "patch"), (n, "note")])])["kind"],
                         "done")


class TestContests(unittest.TestCase):
    a = finding("a")

    def test_a_conceded_contest_closes_its_finding(self):
        entry = derive([self.a], prior=[step("patch", [(self.a, "patch")])],
                       answers={"a": "concede"})
        self.assertEqual(entry["kind"], "done")
        self.assertIn("a", entry["settled"])

    def test_a_held_contest_parks_the_task_while_the_rest_proceeds(self):
        b = finding("b")
        entry = derive([self.a, b], prior=[step("patch", [(self.a, "patch"), (b, "patch")])],
                       answers={"a": "hold"})
        self.assertEqual(entry["kind"], "patch")
        self.assertEqual(entry["held"], ["a"])
        done_but_held = derive([self.a], prior=[step("patch", [(self.a, "patch")])],
                               answers={"a": "hold"})
        self.assertEqual(done_but_held["kind"], "escalate")

    def test_a_held_finding_the_reviewer_stopped_raising_is_no_longer_held(self):
        prior = [step("patch", [(self.a, "patch")], held=["a"])]
        entry = derive([], prior=prior)
        self.assertEqual((entry["kind"], entry["held"]), ("done", []))

    def test_settled_findings_carry_forward_into_later_entries(self):
        prior = [step("patch", [(self.a, "patch")], settled=["a"])]
        self.assertIn("a", derive(prior=prior)["settled"])


class TestFiling(unittest.TestCase):
    def test_a_defer_finding_is_filed_once(self):
        d = finding("d", severity=2, reach="contract")
        first = derive([d])
        self.assertEqual([c["id"] for c in first["to_file"]], ["d"])
        again = derive([d], prior=[step("done", [(d, "defer")], filed=first["filed"])])
        self.assertEqual(again["to_file"], [])

    def test_coder_deferrals_are_filed_once(self):
        skip = {"id": "task-1-python-coder#notes_skipped[aa]", "rule": "naming"}
        first = derive(file_candidates=[skip])
        self.assertEqual(first["to_file"], [skip])
        self.assertEqual(derive(prior=[step("done", filed=first["filed"])],
                                file_candidates=[skip])["to_file"], [])


class TestTelemetry(unittest.TestCase):
    def test_counts_against_the_previous_entry(self):
        prev = step("patch", [(finding(i), "patch") for i in "abcde"])
        entry = derive([finding("a", recurring=True), finding("f", introduced=True), finding("g")],
                       prior=[prev], model="opus")
        self.assertEqual((entry["model"], entry["survived"], entry["introduced"], entry["closed"]),
                         ("opus", 1, 1, 4))

    def test_the_first_entry_closes_nothing(self):
        self.assertEqual(derive([finding("a")], model=None)["closed"], 0)


class TestPurity(unittest.TestCase):
    def test_the_module_never_imports_ledger(self):
        source = (SCRIPTS_DIR / "triage.py").read_text(encoding="utf-8")
        self.assertNotIn("import ledger", source)


if __name__ == "__main__":
    unittest.main()
