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


def gate_finding(fid: str, severity: int = 4, reach: str = "local", *,
                 source: str = "close-python-design-reviewer", not_met: bool = False,
                 recurring: bool = False) -> dict:
    return {**finding(fid, severity, reach, source=source, recurring=recurring), "not_met": not_met,
            "sites": [f"{fid}.py:1"]}


def not_met(fid: str, severity: int = 2, reach: str = "local") -> dict:
    return gate_finding(fid, severity, reach, source="close-intent-reviewer", not_met=True)


def derive_close(findings=(), *, prior=(), root_causes=(), reach_raised=(), answers=None,
                 rulings=None, unclear=(), ruled=False, model: str | None = "sonnet",
                 file_candidates=()) -> dict:
    return triage.derive_close(findings=list(findings), root_causes=list(root_causes),
                               reach_raised=set(reach_raised), answers=dict(answers or {}),
                               rulings=dict(rulings or {}), unclear=list(unclear),
                               prior=list(prior), ruled=ruled, model=model,
                               file_candidates=list(file_candidates))


def then(*entries: dict) -> list[dict]:
    """Earlier close entries as `derive_close` wrote them."""
    return list(entries)


def sent(entry: dict) -> set[str]:
    return {f["id"] for f in entry["findings"] if f["tier"] in ("patch", "holistic")}


class TestCloseDisposition(unittest.TestCase):
    def test_with_no_ruling_the_rule_decides(self):
        cases = {(3, False, False): "waiting", (1, False, False): "waiting", (4, False, False): "fix",
                 (5, False, False): "fix", (2, True, False): "fix", (3, False, True): "fix"}
        for (severity, unmet, gate), expected in cases.items():
            with self.subTest(severity=severity, not_met=unmet, gate=gate):
                f = {**gate_finding("f", severity, not_met=unmet), "gate": gate}
                self.assertEqual(triage.close_disposition(f, None), expected)

    def test_the_users_ruling_overrides_the_rule(self):
        for ruling in ("fix", "file", "drop"):
            with self.subTest(ruling=ruling):
                self.assertEqual(triage.close_disposition(gate_finding("f", 5), ruling), ruling)


class TestCloseSteps(unittest.TestCase):
    def test_blocking_findings_go_to_a_fix_and_the_rest_wait_carried(self):
        findings = [gate_finding("d3", 3), gate_finding("m", 3, source="close-mutation-tester"),
                    not_met("n"), gate_finding("d4", 4)]
        entry = derive_close(findings)
        self.assertEqual((entry["kind"], entry["round"], entry["recheck"]), ("patch", 1, "raising"))
        self.assertEqual(sent(entry), {"n", "d4"})
        self.assertEqual({f["id"] for f in entry["carried"]}, {"d3", "m"})
        self.assertEqual((entry["waiting"], entry["to_file"]), (["d3", "m"], []))

    def test_a_contract_finding_starts_a_holistic_round(self):
        self.assertEqual(derive_close([gate_finding("c", 4, "contract")])["kind"], "holistic")

    def test_only_waiting_findings_go_straight_to_decide(self):
        entry = derive_close([gate_finding("a", 3), gate_finding("b", 1)])
        self.assertEqual((entry["kind"], entry["round"], entry["waiting"]), ("decide", 0, ["a", "b"]))

    def test_a_clean_close_is_done(self):
        self.assertEqual(derive_close()["kind"], "done")

    def test_file_and_drop_rulings_settle_and_done_files_only_the_file_ones(self):
        a, b = gate_finding("a", 3), gate_finding("b", 2)
        first = derive_close([a, b])
        entry = derive_close([a, b], prior=then(first), rulings={"a": "file", "b": "drop"}, ruled=True)
        self.assertEqual(entry["kind"], "done")
        self.assertEqual([c["id"] for c in entry["to_file"]], ["a"])
        self.assertEqual(entry["to_file"][0]["finding"]["source"], "close-python-design-reviewer")

    def test_a_fix_ruling_on_a_waiting_finding_starts_a_ruling_round(self):
        a = gate_finding("a", 3)
        decide = derive_close([a])
        entry = derive_close([a], prior=then(decide), rulings={"a": "fix"}, ruled=True)
        self.assertEqual((entry["kind"], sent(entry)), ("ruling", {"a"}))

    def test_a_carried_finding_survives_a_narrow_recheck_that_drops_it(self):
        a, s4 = gate_finding("a", 3), gate_finding("s4", 4)
        patch = derive_close([a, s4])
        entry = derive_close([], prior=then(patch))
        self.assertEqual((entry["kind"], entry["waiting"]), ("decide", ["a"]))

    def test_a_sent_finding_the_gate_stops_raising_is_fixed(self):
        a = gate_finding("a", 3)
        decide = derive_close([a])
        ruling = derive_close([a], prior=then(decide), rulings={"a": "fix"}, ruled=True)
        entry = derive_close([], prior=then(decide, ruling), rulings={"a": "fix"})
        self.assertEqual(entry["kind"], "done")

    def test_the_latest_ruling_wins(self):
        a = gate_finding("a", 3)
        decide = derive_close([a])
        entry = derive_close([a], prior=then(decide), rulings={"a": "file"}, ruled=True)
        self.assertEqual(entry["kind"], "done")

    def test_blocking_work_after_two_fix_rounds_escalates_and_a_file_ruling_finishes(self):
        a = gate_finding("a", 4)
        first = derive_close([a])
        second = derive_close([a], prior=then(first))
        third = derive_close([a], prior=then(first, second))
        self.assertEqual([first["kind"], second["kind"], third["kind"]], ["patch", "patch", "escalate"])
        entry = derive_close([a], prior=then(first, second, third), rulings={"a": "file"}, ruled=True)
        self.assertEqual((entry["kind"], [c["id"] for c in entry["to_file"]]), ("done", ["a"]))

    def test_a_fix_ruling_after_escalation_is_a_ruling_round_and_a_failed_one_escalates(self):
        a = gate_finding("a", 4)
        prior = then({**derive_close([a]), "kind": "escalate"})
        ruling = derive_close([a], prior=prior, rulings={"a": "fix"}, ruled=True)
        self.assertEqual(ruling["kind"], "ruling")
        self.assertEqual(derive_close([a], prior=[*prior, ruling], rulings={"a": "fix"})["kind"],
                         "escalate")

    def test_a_held_contest_escalates_until_the_user_rules(self):
        a = gate_finding("a", 4)
        patch = derive_close([a])
        held = derive_close([a], prior=then(patch), answers={"a": "hold"})
        self.assertEqual((held["kind"], held["held"]), ("escalate", ["a"]))
        dropped = derive_close([a], prior=then(patch, held), answers={"a": "hold"},
                               rulings={"a": "drop"}, ruled=True)
        self.assertEqual(dropped["kind"], "done")

    def test_an_open_cant_tell_clarifies_first_and_never_hides_the_step_before(self):
        a = gate_finding("a", 4)
        entry = derive_close([a], unclear=["close-intent-reviewer#statements[3]"])
        self.assertEqual((entry["kind"], entry["round"], entry["recheck"]), ("clarify", 0, "intent"))
        ruling = {**derive_close([a]), "kind": "ruling"}
        after = derive_close([a], prior=then(ruling, entry))
        self.assertEqual(after["kind"], "escalate")

    def test_the_coders_deferrals_are_carried_and_filed_at_done(self):
        skip = {"id": "close-python-coder#sites_outside[aa]", "rule": "naming", "text": "outside site"}
        first = derive_close([gate_finding("a", 3)], file_candidates=[skip])
        self.assertEqual(first["to_file"], [])
        entry = derive_close([], prior=then(first), rulings={"a": "drop"}, ruled=True)
        self.assertEqual(entry["to_file"], [skip])

    def test_done_is_final(self):
        done = derive_close()
        entry = derive_close([gate_finding("a", 4)], prior=then(done), rulings={"a": "fix"}, ruled=True)
        self.assertEqual((entry["kind"], entry["to_file"]), ("done", []))

    def test_a_ruling_on_an_unknown_id_is_reported(self):
        entry = derive_close([gate_finding("a", 3)], rulings={"nope": "fix"})
        self.assertEqual(entry["unmatched"], ["nope"])

    def test_a_root_cause_starts_a_holistic_round(self):
        self.assertEqual(derive_close(root_causes=["close-python-coder#concerns[aa]"])["kind"],
                         "holistic")


class TestPurity(unittest.TestCase):
    def test_the_module_never_imports_ledger(self):
        source = (SCRIPTS_DIR / "triage.py").read_text(encoding="utf-8")
        self.assertNotIn("import ledger", source)


if __name__ == "__main__":
    unittest.main()
