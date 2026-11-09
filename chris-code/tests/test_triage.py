#!/usr/bin/env python3
"""
Tests for triage.py: a finding's first state, what a re-check changes, and
the step each set of finding states leads to, replayed as the round
sequences a real task or close produces.

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

SPEC = "task-1-spec-reviewer"
DESIGN = "close-python-design-reviewer"
INTENT = "close-intent-reviewer"


def finding(fid: str, severity: int = 3, reach: str = "local", *, source: str = SPEC,
            gate: bool = False, not_met: bool = False, recurring: bool = False,
            introduced: bool = False) -> dict:
    return {"id": fid, "source": source, "gate": gate, "severity": severity, "reach": reach,
            "rule": f"rule of {fid}", "sites": [f"{fid}.py:1"], "not_met": not_met,
            "recurring": recurring, "introduced": introduced}


class Loop:
    """A scope's findings and steps, driven as ledger.py drives triage: each
    review rewrites the records it names (their versions change), triage
    observes them, takes the step, and a sent or held finding records the
    digest it was sent or held at."""

    def __init__(self, close: bool = False):
        self.close = close
        self.states: dict[str, dict] = {}
        self.prior: list[dict] = []
        self.versions: dict[str, str] = {}

    def review(self, *raised: dict, answers=None, rewrote=None, root_causes=(), unclear=(),
               override=False, undelivered_note=False) -> dict:
        sources = rewrote if rewrote is not None else {f["source"] for f in raised} or {SPEC}
        for source in sources:
            self.versions[source] = self.versions.get(source, "") + "'"
        self.observed = triage.observe(self.states, list(raised), dict(answers or {}),
                                       self.versions, self.close)
        self.states = triage.apply(self.states, self.observed)
        entry = triage.step(self.states, close=self.close, prior=self.prior,
                            root_causes=list(root_causes), reach_raised=set(),
                            unclear=list(unclear), override=override,
                            undelivered_note=undelivered_note)
        changes = entry.pop("changes")
        self.states = triage.apply(self.states, changes)
        for change in [*self.observed, *changes]:
            if change["state"] in ("sent", "held"):
                self.states[change["id"]]["seen"] = self.versions.get(
                    self.states[change["id"]]["data"]["source"])
        self.prior.append(entry)
        return entry

    def rule(self, fid: str, verb: str) -> None:
        self.states[fid].update(state={"fix": "fix", "file": "filed", "drop": "dropped"}[verb],
                                by="user")

    def state(self, fid: str) -> str:
        return self.states[fid]["state"]


def sent(entry: dict) -> list[str]:
    return [f["id"] for f in entry["findings"] if f["tier"] in ("patch", "holistic")]


class TestTiersAndFirstStates(unittest.TestCase):
    def test_each_cell_of_the_task_matrix(self):
        cases = {(1, "local"): "note", (2, "class"): "note", (2, "contract"): "defer",
                 (3, "local"): "patch", (5, "class"): "patch", (3, "contract"): "holistic"}
        for (severity, reach), expected in cases.items():
            with self.subTest(severity=severity, reach=reach):
                self.assertEqual(triage.tier(finding("f", severity, reach), set()), expected)

    def test_a_reach_the_coder_raised_is_contract(self):
        self.assertEqual(triage.tier(finding("f"), {"f"}), "holistic")

    def test_first_states_in_a_task(self):
        for (severity, reach), expected in {(2, "local"): "note", (2, "contract"): "filed",
                                            (3, "local"): "fix", (4, "contract"): "fix"}.items():
            with self.subTest(severity=severity, reach=reach):
                self.assertEqual(triage.first_state(finding("f", severity, reach), close=False),
                                 expected)

    def test_first_states_at_the_close(self):
        cases = {"s3": (finding("a", 3), "waiting"), "s1": (finding("a", 1), "waiting"),
                 "s4": (finding("a", 4), "fix"), "not-met": (finding("a", 2, not_met=True), "fix"),
                 "gate": (finding("a", 3, gate=True), "fix")}
        for label, (f, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(triage.first_state(f, close=True), expected)


class TestTaskRounds(unittest.TestCase):
    def test_a_local_s3_starts_a_patch_rechecked_by_its_raiser(self):
        entry = Loop().review(finding("a"))
        self.assertEqual((entry["kind"], entry["round"], entry["recheck"], sent(entry)),
                         ("patch", 1, "raising", ["a"]))

    def test_only_gate_findings_are_rechecked_by_the_gate(self):
        entry = Loop().review(finding("g", source="task-1-gate", gate=True))
        self.assertEqual(entry["recheck"], "gate")

    def test_a_contract_finding_starts_a_holistic_round_for_every_reviewer(self):
        entry = Loop().review(finding("a", 3, "contract"))
        self.assertEqual((entry["kind"], entry["recheck"]), ("holistic", "all"))

    def test_a_lone_root_cause_starts_a_holistic_round(self):
        self.assertEqual(Loop().review(root_causes=["c"])["kind"], "holistic")

    def test_notes_alone_get_one_polish_and_never_reopen(self):
        loop = Loop()
        entry = loop.review(finding("n", 1))
        self.assertEqual((entry["kind"], entry["recheck"]), ("polish", "none"))
        self.assertEqual(loop.state("n"), "noted")
        self.assertEqual(loop.review(finding("n", 1))["kind"], "done")

    def test_notes_ride_along_in_a_fix_round(self):
        entry = Loop().review(finding("a"), finding("n", 1))
        self.assertEqual({f["id"]: f["tier"] for f in entry["findings"]}, {"a": "patch", "n": "note"})

    def test_an_s2_contract_finding_is_filed_and_needs_no_round(self):
        loop = Loop()
        self.assertEqual(loop.review(finding("d", 2, "contract"))["kind"], "done")
        self.assertEqual(loop.state("d"), "filed")

    def test_a_clean_review_is_done_and_an_undelivered_note_polishes(self):
        self.assertEqual(Loop().review()["kind"], "done")
        self.assertEqual(Loop().review(undelivered_note=True)["kind"], "polish")

    def test_a_sent_finding_its_reviewer_no_longer_raises_is_fixed(self):
        loop = Loop()
        loop.review(finding("a"))
        self.assertEqual(loop.review()["kind"], "done")
        self.assertEqual(loop.state("a"), "fixed")

    def test_a_sent_finding_still_raised_after_the_recheck_goes_round_again(self):
        loop = Loop()
        loop.review(finding("a"))
        entry = loop.review(finding("a"))
        self.assertEqual((entry["kind"], entry["round"], sent(entry)), ("patch", 2, ["a"]))
        self.assertEqual([c["state"] for c in loop.observed], ["fix"])

    def test_a_contract_finding_after_a_patch_goes_holistic(self):
        loop = Loop()
        loop.review(finding("a"))
        self.assertEqual(loop.review(finding("b", 3, "contract"))["kind"], "holistic")

    def test_a_reviewer_that_hasnt_rechecked_leaves_a_sent_finding_sent(self):
        loop = Loop()
        loop.review(finding("a"))
        loop.review(finding("a"), rewrote=set())
        self.assertEqual(loop.observed, [])

    def test_open_work_after_two_rounds_waits_for_the_user_who_rules_it(self):
        loop = Loop()
        loop.review(finding("a"))
        loop.review(finding("a"))
        entry = loop.review(finding("a"))
        self.assertEqual((entry["kind"], entry["waiting"]), ("escalate", ["a"]))
        self.assertEqual(loop.review(finding("a"), rewrote=set())["kind"], "escalate")
        loop.rule("a", "fix")
        ruling = loop.review(finding("a"), rewrote=set())
        self.assertEqual((ruling["kind"], sent(ruling), ruling["round"]), ("ruling", ["a"], 2))
        again = loop.review(finding("a"))
        self.assertEqual((again["kind"], again["waiting"]), ("escalate", ["a"]))

    def test_a_fix_ruling_after_a_failed_ruling_round_starts_another(self):
        loop = Loop()
        for _ in range(3):
            loop.review(finding("a"))
        loop.rule("a", "fix")
        loop.review(finding("a"), rewrote=set())
        self.assertEqual(loop.review(finding("a"))["kind"], "escalate")
        loop.rule("a", "fix")
        again = loop.review(finding("a"), rewrote=set())
        self.assertEqual((again["kind"], sent(again)), ("ruling", ["a"]))

    def test_past_the_cap_a_ruled_finding_is_sent_and_the_others_wait(self):
        loop = Loop()
        for _ in range(3):
            loop.review(finding("a"), finding("b"))
        loop.rule("a", "fix")
        loop.review(finding("a"), finding("b"), rewrote=set())
        loop.rule("b", "fix")
        ruling = loop.review(finding("a"), finding("b"))
        self.assertEqual((ruling["kind"], sent(ruling), ruling["waiting"]), ("ruling", ["b"], ["a"]))

    def test_a_file_or_drop_ruling_settles_without_a_round(self):
        for verb, state in (("file", "filed"), ("drop", "dropped")):
            with self.subTest(verb=verb):
                loop = Loop()
                for _ in range(3):
                    loop.review(finding("a"))
                loop.rule("a", verb)
                entry = loop.review(finding("a"), rewrote=set())
                self.assertEqual((entry["kind"], entry["settled"]), ("done", ["a"]))
                self.assertEqual(loop.state("a"), state)

    def test_an_override_after_done_is_a_ruling_round_the_spec_reviewer_rechecks(self):
        loop = Loop()
        loop.review()
        entry = loop.review(rewrote=set(), override=True)
        self.assertEqual((entry["kind"], entry["recheck"], entry["findings"]),
                         ("ruling", "spec", []))


class TestContests(unittest.TestCase):
    def contested(self, verdict: str) -> Loop:
        loop = Loop()
        loop.review(finding("a"))
        loop.review(finding("a"), answers={"a": verdict})
        return loop

    def test_a_conceded_contest_fixes_the_finding(self):
        loop = self.contested("concede")
        self.assertEqual((loop.state("a"), loop.prior[-1]["kind"]), ("fixed", "done"))

    def test_a_held_contest_waits_for_the_user_and_survives_later_rechecks(self):
        loop = self.contested("hold")
        self.assertEqual((loop.prior[-1]["kind"], loop.prior[-1]["held"]), ("escalate", ["a"]))
        loop.review(rewrote={SPEC})
        self.assertEqual(loop.state("a"), "held")

    def test_the_user_rules_a_held_finding_fix_and_it_is_sent_again(self):
        loop = self.contested("hold")
        loop.rule("a", "fix")
        self.assertEqual(sent(loop.review(finding("a"), rewrote=set())), ["a"])

    def test_a_stale_hold_never_re_holds_a_finding_sent_again(self):
        loop = self.contested("hold")
        loop.rule("a", "fix")
        loop.review(finding("a"), answers={"a": "hold"}, rewrote=set())
        self.assertEqual(loop.state("a"), "sent")
        loop.review(finding("a"), answers={"a": "hold"}, rewrote=set())
        self.assertEqual((loop.observed, loop.state("a")), ([], "sent"))

    def test_a_held_finding_its_reviewer_later_concedes_is_fixed(self):
        loop = self.contested("hold")
        loop.review(finding("a"), answers={"a": "concede"})
        self.assertEqual(loop.state("a"), "fixed")


class TestClose(unittest.TestCase):
    def test_blocking_findings_go_to_a_fix_and_the_rest_wait(self):
        loop = Loop(close=True)
        entry = loop.review(finding("s3", 3, source=DESIGN), finding("n", 2, source=INTENT, not_met=True),
                            finding("s4", 4, source=DESIGN))
        self.assertEqual((entry["kind"], entry["recheck"], sorted(sent(entry)), entry["waiting"]),
                         ("patch", "raising", ["n", "s4"], ["s3"]))

    def test_only_waiting_findings_go_straight_to_decide(self):
        entry = Loop(close=True).review(finding("a", 3, source=DESIGN))
        self.assertEqual((entry["kind"], entry["waiting"], entry["round"]), ("decide", ["a"], 0))

    def test_a_waiting_finding_a_narrow_recheck_omits_keeps_waiting(self):
        loop = Loop(close=True)
        loop.review(finding("s3", 3, source=DESIGN), finding("s4", 4, source=DESIGN))
        entry = loop.review(rewrote={DESIGN})
        self.assertEqual((entry["kind"], entry["waiting"]), ("decide", ["s3"]))
        self.assertEqual(loop.state("s4"), "fixed")

    def test_a_sent_finding_ruled_file_stays_filed_when_its_gate_omits_it(self):
        loop = Loop(close=True)
        a, b = finding("a", 4, source=DESIGN), finding("b", 4, source=DESIGN)
        for _ in range(3):
            loop.review(a, b)
        loop.rule("a", "fix")
        loop.rule("b", "file")
        ruling = loop.review(a, b, rewrote=set())
        self.assertEqual(sent(ruling), ["a"])
        entry = loop.review(rewrote={DESIGN})
        self.assertEqual((entry["kind"], loop.state("a"), loop.state("b")), ("done", "fixed", "filed"))

    def test_spent_rounds_put_the_open_findings_to_the_user_in_one_decide(self):
        loop = Loop(close=True)
        a, b = finding("a", 4, source=DESIGN), finding("b", 4, source=DESIGN)
        loop.review(a, b)
        loop.review(a, b)
        entry = loop.review(a, b)
        self.assertEqual((entry["kind"], entry["waiting"]), ("decide", ["a", "b"]))

    def test_a_file_ruling_starts_no_round_even_with_other_findings_waiting(self):
        loop = Loop(close=True)
        a, b = finding("a", 4, source=DESIGN), finding("b", 4, source=DESIGN)
        for _ in range(3):
            loop.review(a, b)
        loop.rule("a", "file")
        entry = loop.review(a, b, rewrote=set())
        self.assertEqual((entry["kind"], entry["waiting"]), ("decide", ["b"]))

    def test_an_open_cant_tell_clarifies_first_and_never_hides_the_step_before(self):
        loop = Loop(close=True)
        a = finding("a", 4, source=DESIGN)
        for _ in range(3):
            loop.review(a)
        loop.rule("a", "fix")
        self.assertEqual(loop.review(a, rewrote=set(), unclear=["s1"])["kind"], "clarify")
        self.assertEqual(loop.review(a, rewrote=set())["kind"], "ruling")

    def test_a_finished_close_is_final(self):
        loop = Loop(close=True)
        loop.review()
        self.assertEqual(loop.review(finding("a", 4, source=DESIGN))["kind"], "done")


class TestAwaiting(unittest.TestCase):
    def test_a_round_waits_on_each_named_record_not_rewritten_since(self):
        awaited = {DESIGN: "d1", INTENT: "i1", "close-gate": None}
        self.assertEqual(triage.awaiting(awaited, {DESIGN: "d2", INTENT: "i1"}),
                         ["close-gate", INTENT])
        self.assertEqual(triage.awaiting(awaited, {DESIGN: "d2", INTENT: "i2", "close-gate": "g"}),
                         [])


class TestPurity(unittest.TestCase):
    def test_the_module_never_imports_ledger(self):
        source = (SCRIPTS_DIR / "triage.py").read_text(encoding="utf-8")
        self.assertNotIn("import ledger", source)


if __name__ == "__main__":
    unittest.main()
