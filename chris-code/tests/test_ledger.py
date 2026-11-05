#!/usr/bin/env python3
"""
Tests for ledger.py (spec Sec 9 acceptance criteria 3-7, plus one test per
loud-failure case the design requires ledger.py to surface rather than
silently render around).

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = (Path(__file__).resolve().parents[1]
               / "skills" / "subagent-driven-development" / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import ledger  # noqa: E402

LEDGER_PY = SCRIPTS_DIR / "ledger.py"


def _coder(**overrides) -> dict:
    data = {
        "schema": 2, "agent": "python-coder", "role": "coder", "task": 1,
        "status": "done", "changed_files": [], "tests": {},
        "new_shared_symbols": [], "duplication_pending": [],
        "concerns": [], "report": "", "cycle": 1, "model": "sonnet",
    }
    data.update(overrides)
    return data


def _finding(**overrides) -> dict:
    """A tagged reviewer finding: S3 local at a.py:1 unless overridden."""
    data = {"severity": 3, "reach": "local", "rule": "size must be positive",
            "sites": ["a.py:1"], "claim": "size=0 is accepted"}
    data.update(overrides)
    return data


def _quality_reviewer(**overrides) -> dict:
    data = {
        "schema": 2, "agent": "python-quality-reviewer", "role": "quality-reviewer",
        "task": 1, "status": "approved", "findings": [],
        "recurring": [], "introduced_by_fix": [],
    }
    data.update(overrides)
    return data


def _spec_reviewer(**overrides) -> dict:
    data = {
        "schema": 2, "agent": "spec-reviewer", "role": "spec-reviewer",
        "task": 1, "status": "compliant", "issues": [], "cannot_verify": [],
        "recurring": [], "introduced_by_fix": [],
    }
    data.update(overrides)
    return data


def _review_lite(**overrides) -> dict:
    data = {
        "schema": 2, "agent": "python-review-lite", "role": "review-lite",
        "task": 1, "status": "clean", "cycle": 1, "findings": [],
        "linter": {"ran": True, "name": "ruff", "passed": True},
    }
    data.update(overrides)
    return data


def _triaged(store: Path, task: int | str = 1, kind: str = "patch") -> None:
    """Log a fix-kind triage entry with nothing sent, so a later snapshot
    starts a routed fix (for tests about something other than routing)."""
    ledger._append_progress(store, {"type": "triage", "task": task, "kind": kind,
                                    "recheck": "raising", "findings": []})


_FIX_FIELDS = {"diagnosis": {"root_cause": "r", "end_state": "e", "resolves_cluster": "c"}, "hunk_map": [], "consumers_checked": []}


def _baseline(store: Path, task: int | str = 3) -> str:
    """The fix baseline triage took for the scope's latest fix step."""
    return [e for e in ledger.load_progress_log(store)
            if e.get("type") == "snapshot" and e.get("task") == task][-1]["tree"]


def _completable(store: Path, task: int | str) -> None:
    """Make `task` ready to complete for tests about something else: a done
    triage entry and a passing gate (a store outside git skips the blob
    match)."""
    ledger.ensure_store(store)
    _triaged(store, task, kind="done")
    prefix = ledger.scope_prefix(ledger.load_progress_log(store), task)
    _write(store, f"{prefix}-gate.json", {
        "schema": 2, "agent": "ledger", "role": "gate", "task": task, "status": "pass",
        "tree": "t", "files": [], "commands": [], "findings": [], "recurring": [],
        "introduced_by_fix": []})


def _write(store: Path, name: str, data: dict) -> Path:
    path = store / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _entry_id(stem: str, field_name: str, entry: dict | str) -> str:
    """The real id `open`/`resolve` compute for an entry-level open item —
    content-derived (spec Sec 6, amended 2026-08-27), so tests must
    compute it the same way ledger.py does rather than assume a fixed,
    positional shape."""
    return f"{stem}#{field_name}[{ledger._entry_digest(entry)}]"


def _dup_id(stem: str, entry: dict) -> str:
    return _entry_id(stem, "duplication_pending", entry)


def _cv_id(stem: str, entry: dict) -> str:
    return _entry_id(stem, "cannot_verify", entry)


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name)


# --- validate_record ---

class TestValidateRecord(LedgerTestCase):
    def test_valid_coder_record_passes(self):
        ledger.validate_record(_coder())  # no raise

    def test_not_a_dict_raises(self):
        with self.assertRaises(ledger.RecordError):
            ledger.validate_record(["not", "a", "dict"])

    def test_missing_envelope_field_raises_naming_field(self):
        data = _coder()
        del data["task"]
        with self.assertRaisesRegex(ledger.RecordError, "task"):
            ledger.validate_record(data)

    def test_unknown_schema_raises(self):
        with self.assertRaisesRegex(ledger.RecordError, "schema"):
            ledger.validate_record(_coder(schema=99))

    def test_unknown_role_raises_naming_allowed_set(self):
        data = _coder(role="not-a-real-role")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(data)
        message = str(ctx.exception)
        self.assertIn("role", message)
        self.assertIn("not-a-real-role", message)  # offending value
        for allowed in ledger.VALID_ROLES:  # allowed set
            self.assertIn(allowed, message)

    def test_unhashable_role_raises_record_error_not_type_error(self):
        # An unhashable role (e.g. a list) must not crash the
        # `role not in VALID_ROLES` set-membership test with a bare
        # TypeError; it must raise RecordError like any other bad role.
        with self.assertRaises(ledger.RecordError):
            ledger.validate_record(_coder(role=["not", "hashable"]))

    def test_unhashable_status_raises_record_error_not_type_error(self):
        with self.assertRaises(ledger.RecordError):
            ledger.validate_record(_coder(status=["not", "hashable"]))

    def test_out_of_enum_status_raises_visible_error(self):
        # Failure case: a typo'd "Blocked" status must surface as a
        # visible, corrective error naming the value and allowed set.
        with self.assertRaisesRegex(ledger.RecordError, "Blocked"):
            ledger.validate_record(_coder(status="Blocked"))

    def test_missing_decision_field_raises(self):
        data = _coder()
        del data["duplication_pending"]
        with self.assertRaisesRegex(ledger.RecordError, "duplication_pending"):
            ledger.validate_record(data)

    def test_decision_field_wrong_type_raises_loud_not_silent(self):
        # Failure case: type garbage in a decision-driving field must fail
        # loudly, never be silently coerced or skipped.
        with self.assertRaisesRegex(ledger.RecordError, "duplication_pending"):
            ledger.validate_record(_coder(duplication_pending="not-a-list"))

    def test_decision_field_non_dict_entry_raises_loud_not_silent(self):
        # A non-dict new_shared_symbols entry must fail loudly at
        # validation, not be silently dropped by list_shapes downstream.
        with self.assertRaisesRegex(ledger.RecordError, "new_shared_symbols"):
            ledger.validate_record(_coder(new_shared_symbols=["garbage-string"]))

    def test_informational_field_unvalidated(self):
        # `concerns` is informational; any shape is accepted (spec Sec 7
        # amendment scopes required-ness to decision-driving fields only).
        ledger.validate_record(_coder(concerns="not-a-list-but-fine"))

    def test_spec_reviewer_missing_cannot_verify_raises(self):
        data = _spec_reviewer()
        del data["cannot_verify"]
        with self.assertRaisesRegex(ledger.RecordError, "cannot_verify"):
            ledger.validate_record(data)


# --- load_records / per-record isolation ---

class TestFixLoopFields(LedgerTestCase):
    """Coder self-derived cycle + diagnosis-from-cycle-2, and the reviewer
    recurring signal (fix-loop amendments, 2026-08-28)."""

    def _diagnosis(self, **overrides):
        d = {"root_cause": "validator missing on the discretizing path",
             "end_state": "all threshold inputs validated at construction",
             "resolves_cluster": "both findings trace to the same absent guard"}
        d.update(overrides)
        return d

    def test_cycle_1_needs_no_diagnosis(self):
        ledger.validate_record(_coder(cycle=1))  # no raise

    def test_coder_record_without_cycle_raises(self):
        # The fix-mode checks key off `cycle`; a record that omitted it
        # would skip every one of them.
        record = _coder()
        del record["cycle"]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(record)
        self.assertIn("cycle", str(ctx.exception))

    def test_cycle_2_without_diagnosis_raises_naming_the_field(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2))
        self.assertIn("diagnosis", str(ctx.exception))
        self.assertIn("cycle 2", str(ctx.exception))

    def test_blocked_or_needs_context_at_cycle_2_needs_no_diagnosis(self):
        # A coder that stops mid-fix hasn't fixed anything yet, so it has
        # no cause to state; demanding one forces an invented diagnosis.
        for status in ("blocked", "needs_context"):
            ledger.validate_record(_coder(cycle=2, status=status))  # no raise

    def test_done_with_concerns_at_cycle_2_still_needs_a_diagnosis(self):
        with self.assertRaises(ledger.RecordError):
            ledger.validate_record(_coder(cycle=2, status="done_with_concerns"))

    def _fix(self, **overrides):
        """A complete cycle-2+ fix record's fix-mode fields."""
        fields = {
            "diagnosis": self._diagnosis(),
            "hunk_map": [{"site": "a.py:10-14", "implements": "quality S3: missing guard"}],
            "consumers_checked": [{"symbol": "a.build", "consumers": ["b.py:3"],
                                   "verified": "b.py passes the new arg"}],
        }
        fields.update(overrides)
        return fields

    def test_cycle_2_with_complete_fix_fields_passes(self):
        ledger.validate_record(_coder(cycle=2, **self._fix()))

    def test_fix_without_hunk_map_raises_naming_it(self):
        # Every hunk of a fix must name what it implements; an unmapped
        # hunk is where fix-introduced issues come from.
        fields = self._fix()
        del fields["hunk_map"]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **fields))
        self.assertIn("hunk_map", str(ctx.exception))

    def test_fix_without_consumers_checked_raises_naming_it(self):
        fields = self._fix()
        del fields["consumers_checked"]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **fields))
        self.assertIn("consumers_checked", str(ctx.exception))

    def test_empty_consumers_checked_is_a_real_answer(self):
        # A fix that changed no symbol's signature or behavior has nothing
        # to check; an explicit empty list says so.
        ledger.validate_record(_coder(cycle=2, **self._fix(consumers_checked=[])))

    def test_hunk_map_entry_missing_implements_raises_naming_it(self):
        bad = [{"site": "a.py:10-14"}]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **self._fix(hunk_map=bad)))
        self.assertIn("hunk_map[0].implements", str(ctx.exception))

    def test_consumers_checked_consumers_must_be_a_list(self):
        bad = [{"symbol": "a.build", "consumers": "b.py:3", "verified": "ok"}]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **self._fix(consumers_checked=bad)))
        self.assertIn("consumers_checked[0].consumers", str(ctx.exception))

    def test_cycle_1_needs_no_fix_fields(self):
        ledger.validate_record(_coder(cycle=1))  # no raise

    def test_absent_introduced_by_fix_still_validates(self):
        # Records written before 0.6.0 lack the field; a mid-run plugin
        # upgrade must not turn every earlier reviewer record malformed.
        record = _spec_reviewer()
        del record["introduced_by_fix"]
        ledger.validate_record(record)  # no raise

    def test_quality_reviewer_introduced_by_fix_is_validated_when_present(self):
        quality = {"schema": 2, "agent": "python-quality-reviewer",
                   "role": "quality-reviewer", "task": 1, "status": "approved",
                   "findings": [], "recurring": [],
                   "introduced_by_fix": ["a.py:1"]}
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(quality)
        self.assertIn("introduced_by_fix", str(ctx.exception))

    def test_consumers_checked_entry_without_verified_raises(self):
        bad = [{"symbol": "a.build", "consumers": ["b.py:3"]}]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **self._fix(consumers_checked=bad)))
        self.assertIn("consumers_checked[0].verified", str(ctx.exception))

    def test_present_introduced_by_fix_must_be_a_list_of_objects(self):
        for bad in ("a.py:1", ["a.py:1"]):
            with self.assertRaises(ledger.RecordError, msg=repr(bad)) as ctx:
                ledger.validate_record(_spec_reviewer(introduced_by_fix=bad))
            self.assertIn("introduced_by_fix", str(ctx.exception))

    def test_an_empty_hunk_map_is_refused_when_the_fix_claims_a_hunk(self):
        sweep = {"findings": ["f"], "rule": "r", "rows": [{"site": "a.py:1", "hunk": "a.py:1"}],
                 "searched": {"command": "rg r", "result": "1 match"}}
        for claim in ({"sweeps": [sweep]}, {"decision_rows": [{"choice": 0, "case": 0, "hunk": "a.py:1"}]}):
            with self.subTest(claim=list(claim)), self.assertRaises(ledger.RecordError) as ctx:
                ledger.validate_record(_coder(cycle=2, **self._fix(hunk_map=[], **claim)))
            self.assertIn("hunk_map", str(ctx.exception))

    def test_a_round_that_changed_nothing_may_have_an_empty_hunk_map(self):
        # Every finding sent was contested, or a polish found nothing to change.
        ledger.validate_record(_coder(cycle=2, **self._fix(
            hunk_map=[], contested=[{"finding": "f", "reason": "wrong", "evidence": "a.py:1 guards it"}])))

    def test_introduced_by_fix_never_becomes_an_open_item(self):
        # Like recurring, it's a failed-fix signal riding on findings,
        # not separate work.
        record = _spec_reviewer(
            status="issues", issues=[_finding(sites=["a.py:12"])],
            introduced_by_fix=[{"site": "a.py:12", "why": "fix dropped the None guard"}])
        _write(self.store, "task-1-spec-reviewer.json", record)
        items = ledger.compute_open_items(ledger.load_records(self.store), set())
        self.assertEqual([i.kind for i in items], ["status"])

    def test_diagnosis_missing_a_key_raises_naming_it(self):
        bad = self._diagnosis()
        del bad["end_state"]
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, diagnosis=bad))
        self.assertIn("diagnosis.end_state", str(ctx.exception))

    def test_diagnosis_blank_value_raises(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(
                _coder(cycle=3, diagnosis=self._diagnosis(root_cause="   ")))
        self.assertIn("diagnosis.root_cause", str(ctx.exception))

    def test_non_integer_cycle_raises(self):
        for bad in ("2", 0, -1, True):
            with self.assertRaises(ledger.RecordError, msg=repr(bad)):
                ledger.validate_record(_coder(cycle=bad))

    def test_reviewer_cycle_is_informational_not_validated(self):
        # Only the coder's cycle drives a conditional requirement; a
        # reviewer's cycle stays unvalidated like every informational field.
        ledger.validate_record(_spec_reviewer(cycle=2))  # no raise

    def test_recurring_required_on_spec_and_quality_reviewers(self):
        quality = {"schema": 2, "agent": "python-quality-reviewer",
                   "role": "quality-reviewer", "task": 1, "status": "approved",
                   "findings": [], "recurring": [], "introduced_by_fix": []}
        for record in (_spec_reviewer(), quality):
            record = dict(record)
            del record["recurring"]
            with self.assertRaises(ledger.RecordError, msg=record["role"]) as ctx:
                ledger.validate_record(record)
            self.assertIn("recurring", str(ctx.exception))

    def test_recurring_entries_must_be_objects(self):
        with self.assertRaises(ledger.RecordError):
            ledger.validate_record(_spec_reviewer(recurring=["site:1"]))

    def test_recurring_never_becomes_an_open_item(self):
        # recurring is a signal riding on findings, not separate work:
        # it must stay out of `open` (same rule as new_shared_symbols).
        record = _spec_reviewer(
            status="issues", issues=[_finding(sites=["a.py:10"])],
            recurring=[{"site": "a.py:10", "why": "same class as cycle 1"}])
        _write(self.store, "task-1-spec-reviewer.json", record)
        items = ledger.compute_open_items(ledger.load_records(self.store), set())
        self.assertEqual([i.kind for i in items], ["status"])


class TestCoderEvidence(LedgerTestCase):
    """A coder's sweeps, tests-first entries, open choices, contests and
    test changes each carry the evidence a reviewer or `check` relies on."""

    def assertRejects(self, data: dict, *fragments: str) -> None:
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(data)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    @staticmethod
    def _sweep(**overrides) -> dict:
        sweep = {"findings": ["task-1-spec-reviewer#issues[1a2b3c4d]"],
                 "rule": "size must be positive",
                 "rows": [{"site": "a.py:40", "hunk": "a.py:38-44"},
                          {"site": "c.py:12", "already_correct": "guards size at c.py:10"}],
                 "searched": {"command": "rg -n 'size' src/", "result": "2 matches: a.py:40, c.py:12"},
                 "sites_outside": []}
        sweep.update(overrides)
        return sweep

    def test_a_sweep_with_a_search_or_an_inspected_list_passes(self):
        ledger.validate_record(_coder(sweeps=[self._sweep()]))
        inspected = self._sweep(inspected=[{"target": "callers of make_grid",
                                            "found_by": "consumers search"}])
        del inspected["searched"]
        ledger.validate_record(_coder(sweeps=[inspected]))

    def test_a_sweep_without_search_evidence_is_refused(self):
        bare = self._sweep()
        del bare["searched"]
        self.assertRejects(_coder(sweeps=[bare]), "sweeps[0]")
        self.assertRejects(_coder(sweeps=[self._sweep(searched={"command": "rg x", "result": " "})]),
                           "sweeps[0].searched.result")

    def test_a_row_with_neither_hunk_nor_already_correct_is_refused(self):
        self.assertRejects(_coder(sweeps=[self._sweep(rows=[{"site": "a.py:40"}])]),
                           "sweeps[0].rows[0]")

    def test_tests_first_takes_a_failing_run_or_a_listed_n_a(self):
        ledger.validate_record(_coder(tests_first=[
            {"finding": "f1", "test": "tests/test_a.py::test_zero",
             "command": "pytest tests/test_a.py::test_zero", "failed_output": "AssertionError"},
            {"finding": "f2", "n/a": "structural", "reason": "dedupes two helpers"},
            {"finding": "f3", "n/a": "existing", "reason": "the gate's failing test",
             "test": "tests/test_a.py::test_round_trip"}]))

    def test_tests_first_n_a_outside_the_list_or_existing_without_a_test_is_refused(self):
        self.assertRejects(_coder(tests_first=[{"finding": "f", "n/a": "trivial", "reason": "r"}]),
                           "tests_first[0]")
        self.assertRejects(_coder(tests_first=[{"finding": "f", "n/a": "existing", "reason": "r"}]),
                           "tests_first[0].test")

    def test_an_open_choice_cites_a_precedent_or_says_why_there_is_none(self):
        ledger.validate_record(_coder(open=[
            {"question": "size=None?", "choice": "ValueError", "precedent": "src/grid.py:31"},
            {"question": "empty data?", "choice": "[]", "no_precedent": "no other loader reads lists"}]))
        self.assertRejects(_coder(open=[{"question": "size=None?", "choice": "ValueError"}]),
                           "open[0]")

    def test_a_contest_needs_a_listed_reason_and_evidence(self):
        ledger.validate_record(_coder(contested=[
            {"finding": "f", "reason": "plan-conflict", "evidence": "Cases: row 2 says return []"}]))
        self.assertRejects(_coder(contested=[{"finding": "f", "reason": "disagree", "evidence": "e"}]),
                           "contested[0].reason")

    def test_a_test_change_needs_a_listed_kind_and_a_reason(self):
        ledger.validate_record(_coder(test_changes=[
            {"kind": "changed", "test": "tests/test_a.py::test_scale", "old": "assert scale == 2",
             "new": "assert scale == 3", "reason": "the brief's row 3 sets 3"}]))
        self.assertRejects(_coder(test_changes=[
            {"kind": "edited", "test": "t", "old": "o", "new": "n", "reason": "r"}]), "test_changes[0].kind")
        self.assertRejects(_coder(test_changes=[
            {"kind": "deleted", "test": "t", "old": "o", "new": "", "reason": ""}]), "test_changes[0].reason")

    def test_a_root_cause_concern_starts_with_the_path_it_names(self):
        ledger.validate_record(_coder(concerns=["root cause: src/cache.py:12 evicts before write"]))
        self.assertRejects(_coder(concerns=["root cause: the cache evicts early"]), "root cause")

    def test_an_empty_consumers_list_carries_the_search_that_found_none(self):
        fix = {"diagnosis": {"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
               "hunk_map": [{"site": "a.py:10-14", "implements": "the guard"}],
               "consumers_checked": [
                   {"symbol": "a.build", "consumers": [], "verified": "no callers",
                    "searched": {"command": "rg -n 'build(' src/", "result": "0 matches"}}]}
        ledger.validate_record(_coder(cycle=2, **fix))
        fix["consumers_checked"][0].pop("searched")
        self.assertRejects(_coder(cycle=2, **fix), "consumers_checked[0]")


class TestDecisionCases(unittest.TestCase):
    """A holistic decision gives every case a site and a test, names its
    couplings as cases, and records the premise it rests on."""

    def assertRejects(self, data: dict, *fragments: str) -> None:
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(data)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_a_complete_fix_choice_passes(self):
        ledger.validate_record(_decision(["x"], choices=[_fix_choice(
            ["x"], couplings=[{"site": "a.py:1", "effect": "reads the padded value"}])]))

    def test_a_case_without_a_test_is_refused(self):
        case = {"case": "k", "site": "a.py:1", "today": "t", "under_fix": "u", "result": "fixed"}
        self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"], cases=[case])]),
                           "choices[0].cases[0].test")

    def test_a_coupling_no_case_covers_is_refused(self):
        self.assertRejects(_decision(["x"], choices=[_fix_choice(
            ["x"], couplings=[{"site": "b.py:12", "effect": "reads the padded value"}])]),
            "b.py:12")

    def test_a_fix_choice_without_a_premise_is_refused(self):
        choice = _fix_choice(["x"])
        del choice["premise"]
        self.assertRejects(_decision(["x"], choices=[choice]), "choices[0].premise")


class TestFindingTags(LedgerTestCase):
    """Schema 2: every reviewer finding is tagged, and the record's status
    and flags agree with its findings."""

    def assertRejects(self, data: dict, *fragments: str) -> None:
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(data)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_a_schema_1_record_is_refused_with_the_migration_message(self):
        self.assertRejects(_coder(schema=1), "earlier chris-code release", "ledger.py clear")

    def test_tagged_findings_pass_for_every_reviewer_role(self):
        ledger.validate_record(_spec_reviewer(status="issues", issues=[_finding()]))
        ledger.validate_record(_quality_reviewer(status="issues", findings=[_finding()]))
        ledger.validate_record(_review_lite(status="block", findings=[_finding(reach="class")]))

    def test_a_finding_written_without_reach_is_refused_naming_it(self):
        finding = _finding()
        del finding["reach"]
        self.assertRejects(_quality_reviewer(status="issues", findings=[finding]),
                           "findings[0].reach")

    def test_a_severity_outside_one_to_five_is_refused(self):
        for severity in (0, 6):
            with self.subTest(severity=severity):
                self.assertRejects(_quality_reviewer(findings=[_finding(severity=severity)]),
                                   "findings[0].severity")

    def test_a_malformed_site_is_refused_naming_it(self):
        for site in ("a.py:9-5", "a.py:"):
            with self.subTest(site=site):
                self.assertRejects(_review_lite(findings=[_finding(sites=[site])]), site)
        self.assertRejects(_review_lite(findings=[_finding(sites=[])]), "findings[0].sites")

    def test_a_line_range_and_a_bare_path_are_sites(self):
        ledger.validate_record(_review_lite(findings=[_finding(sites=["a.py:88-91", "b.py"])]))

    def test_a_named_case_below_severity_3_is_refused(self):
        self.assertRejects(_spec_reviewer(issues=[_finding(severity=2, case="size=0 -> ValueError")]),
                           "size=0 -> ValueError")
        ledger.validate_record(_spec_reviewer(
            status="issues", issues=[_finding(case="size=0 -> ValueError")]))

    def test_status_must_agree_with_whether_any_finding_is_serious(self):
        ledger.validate_record(_spec_reviewer(status="compliant",
                                              issues=[_finding(severity=2)]))
        self.assertRejects(_spec_reviewer(status="issues", issues=[_finding(severity=2)]),
                           "status")
        self.assertRejects(_quality_reviewer(status="approved", findings=[_finding()]), "status")

    def test_a_flag_must_point_at_a_site_some_finding_names(self):
        ledger.validate_record(_spec_reviewer(
            status="issues", issues=[_finding(sites=["a.py:40"])],
            recurring=[{"site": "a.py:40", "why": "same rule as c1"}]))
        self.assertRejects(_spec_reviewer(
            status="issues", issues=[_finding(sites=["a.py:40"])],
            introduced_by_fix=[{"site": "b.py:3", "why": "w"}]), "b.py:3")

    def test_contest_answers_need_a_verdict_and_a_reason(self):
        ledger.validate_record(_quality_reviewer(contests=[
            {"finding": "x#findings[1]", "verdict": "concede", "reason": "the guard exists at :10"}]))
        self.assertRejects(_quality_reviewer(contests=[
            {"finding": "x#findings[1]", "verdict": "maybe", "reason": "r"}]), "contests[0].verdict")
        self.assertRejects(_quality_reviewer(contests=[
            {"finding": "x#findings[1]", "verdict": "hold", "reason": ""}]), "contests[0].reason")

    def test_a_reopening_finding_names_what_it_reopens(self):
        ledger.validate_record(_quality_reviewer(
            status="issues", findings=[_finding(reopens="x#findings[1]")]))


class TestLoadRecords(LedgerTestCase):
    def test_missing_store_dir_is_empty_not_error(self):
        self.assertEqual(ledger.load_records(self.store / "nope"), [])

    def test_valid_record_loads_ok(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        [rec] = ledger.load_records(self.store)
        self.assertTrue(rec.ok)
        self.assertEqual(rec.data["status"], "done")

    def test_missing_field_or_unparseable_appears_malformed_query_never_crashes(self):
        # Acceptance criterion 5.
        _write(self.store, "task-1-bad.json", {"schema": 2})
        (self.store / "task-2-bad.json").write_text("{not json", encoding="utf-8")
        records = ledger.load_records(self.store)  # must not raise
        self.assertEqual(len(records), 2)
        self.assertTrue(all(not r.ok for r in records))

    def test_undecodable_bytes_surface_as_malformed_not_crash(self):
        # Failure case: a 0xFF undecodable file must be loud (a malformed
        # record with an error message), not a crash of the whole query.
        (self.store / "task-1-bad.json").write_bytes(b"\xff\xfe not utf-8")
        [rec] = ledger.load_records(self.store)
        self.assertFalse(rec.ok)
        self.assertTrue(rec.error)

    def test_one_bad_record_does_not_hide_sibling_records(self):
        # Per-record isolation: a malformed file must not hide others.
        _write(self.store, "task-1-python-coder.json", _coder())
        (self.store / "task-2-bad.json").write_text("not json at all", encoding="utf-8")
        records = ledger.load_records(self.store)
        stems_ok = {r.stem for r in records if r.ok}
        stems_bad = {r.stem for r in records if not r.ok}
        self.assertEqual(stems_ok, {"task-1-python-coder"})
        self.assertEqual(stems_bad, {"task-2-bad"})

    def test_unhashable_role_surfaces_malformed_not_crash(self):
        _write(self.store, "task-1-bad.json", _coder(role=["not", "hashable"]))
        [rec] = ledger.load_records(self.store)
        self.assertFalse(rec.ok)


# --- compute_open_items ---

class TestComputeOpenItems(LedgerTestCase):
    def test_duplication_pending_open_then_resolved(self):
        # Acceptance criterion 3.
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry]))
        item_id = _dup_id("task-1-python-coder", entry)
        records = ledger.load_records(self.store)
        items = ledger.compute_open_items(records, resolved_ids=set())
        self.assertEqual([i.id for i in items], [item_id])

        items = ledger.compute_open_items(records, {item_id})
        self.assertEqual(items, [])

    def test_cannot_verify_entries_open_until_each_resolved(self):
        # Acceptance criterion 4.
        entry_1 = {"requirement": "r1", "why": "w1", "should_check": "sc1"}
        entry_2 = {"requirement": "r2", "why": "w2", "should_check": "sc2"}
        _write(self.store, "task-1-spec-reviewer.json", _spec_reviewer(
            status="issues", issues=[_finding()], cannot_verify=[entry_1, entry_2]))
        id_1 = _cv_id("task-1-spec-reviewer", entry_1)
        id_2 = _cv_id("task-1-spec-reviewer", entry_2)
        records = ledger.load_records(self.store)
        ids = {i.id for i in ledger.compute_open_items(records, resolved_ids=set())
               if i.kind == "cannot_verify"}
        self.assertEqual(ids, {id_1, id_2})

        remaining = {i.id for i in ledger.compute_open_items(records, resolved_ids={id_1})
                     if i.kind == "cannot_verify"}
        self.assertEqual(remaining, {id_2})

    def test_cannot_verify_summary_includes_should_check(self):
        # should_check must appear in the rendered summary alongside
        # requirement/why — an orchestrator reading `open` needs to see
        # what to check, not just what's unverified and why.
        _write(self.store, "task-1-spec-reviewer.json", _spec_reviewer(
            status="issues", issues=[_finding()],
            cannot_verify=[{"requirement": "r1", "why": "w1", "should_check": "run the tests"}]))
        [item] = [i for i in ledger.compute_open_items(ledger.load_records(self.store),
                                                         resolved_ids=set())
                  if i.kind == "cannot_verify"]
        self.assertIn("run the tests", item.summary)

    def test_stray_field_on_unvalidated_role_yields_no_items(self):
        # Open-item extraction is keyed off the same per-role table
        # validate_record uses (DECISION_LIST_FIELDS): a spec-reviewer
        # record's duplication_pending is never validated (only
        # cannot_verify is, for that role), so a stray duplication_pending
        # key must not drive an open item either — reading an unvalidated
        # field would let unchecked data reach a decision surface.
        data = _spec_reviewer(status="issues", issues=[_finding()], cannot_verify=[])
        data["duplication_pending"] = [
            {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]
        _write(self.store, "task-1-spec-reviewer.json", data)
        records = ledger.load_records(self.store)
        self.assertTrue(records[0].ok)  # the stray key doesn't fail validation
        items = ledger.compute_open_items(records, resolved_ids=set())
        kinds = {i.kind for i in items}
        self.assertNotIn("duplication_pending", kinds)
        self.assertEqual(kinds, {"status"})

    def test_identical_entries_within_a_record_dedupe_to_one_item(self):
        # Two duplication_pending entries with identical content hash to
        # the same content-derived id — they're one claim, not two, so
        # they must produce one printed line and resolve with one
        # `resolve` call, not a silently-doubled report.
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[entry, dict(entry)]))
        records = ledger.load_records(self.store)
        items = ledger.compute_open_items(records, resolved_ids=set())
        self.assertEqual([i.id for i in items], [_dup_id("task-1-python-coder", entry)])

    def test_malformed_record_appears_open_query_never_crashes(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        (self.store / "task-2-bad.json").write_text("not json", encoding="utf-8")
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual([i.kind for i in items], ["malformed"])

    def test_status_and_malformed_resolutions_do_not_suppress(self):
        # Whole-record items (status, malformed) are not resolvable; a
        # resolution against #status/#malformed must not hide a later,
        # different problem recorded at the same stem.
        _write(self.store, "task-1-python-coder.json", _coder(status="blocked"))
        (self.store / "task-2-bad.json").write_text("not json", encoding="utf-8")
        records = ledger.load_records(self.store)
        resolved = {"task-1-python-coder#status", "task-2-bad#malformed"}
        items = ledger.compute_open_items(records, resolved)
        kinds = {i.kind for i in items}
        self.assertEqual(kinds, {"status", "malformed"})

    def test_coder_needs_context_status_is_open(self):
        # CODER_OPEN_STATUSES has two members (blocked, needs_context);
        # existing coverage only exercised "blocked" — pin the other one
        # discriminately so a mutant that drops needs_context from the
        # open set (or swaps it for another status) is caught.
        _write(self.store, "task-1-python-coder.json", _coder(status="needs_context"))
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual([i.id for i in items], ["task-1-python-coder#status"])

    def test_review_lite_block_status_is_open(self):
        # review-lite had zero record-level tests: pin each of its three
        # statuses discriminately (block/escalate open, clean not) so a
        # mutant touching REVIEWER_OPEN_STATUSES or the review-lite branch
        # of is_open_status is caught here, not just via a coder record.
        _write(self.store, "task-1-python-review-lite.json", _review_lite(status="block"))
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual([i.id for i in items], ["task-1-python-review-lite#status"])

    def test_review_lite_escalate_status_is_open(self):
        _write(self.store, "task-1-python-review-lite.json", _review_lite(status="escalate"))
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual([i.id for i in items], ["task-1-python-review-lite#status"])

    def test_review_lite_clean_status_is_not_open(self):
        _write(self.store, "task-1-python-review-lite.json", _review_lite(status="clean"))
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual(items, [])

    def test_additive_same_role_pair_coexists(self):
        # Acceptance criterion 7: two same-role agents on one task produce
        # two distinct record files with no collision.
        _write(self.store, "task-1-python-quality-reviewer.json",
               _quality_reviewer(status="issues", findings=[_finding()]))
        _write(self.store, "task-1-pytorch-quality-reviewer.json",
               _quality_reviewer(agent="pytorch-quality-reviewer", status="issues",
                                 findings=[_finding()]))
        records = ledger.load_records(self.store)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r.ok for r in records))
        ids = {i.id for i in ledger.compute_open_items(records, resolved_ids=set())}
        self.assertEqual(ids, {"task-1-python-quality-reviewer#status",
                                "task-1-pytorch-quality-reviewer#status"})

    def test_render_crash_in_one_record_does_not_hide_siblings(self):
        # Per-record isolation must cover open-item *construction*, not
        # just load-time validation. sites=[1, 2] passes validate_record
        # (an informational sub-field) but crashes str.join inside
        # _describe_duplication. That must become one loud item naming the
        # offending file, not a bare TypeError that kills every other
        # record's items too — and (see TestCmdCheck below) this same
        # record must now fail `check`, since `check` exercises the same
        # item-construction path `open` uses.
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": [1, 2], "wants_owner": "b.py", "why": "x"}]))
        _write(self.store, "task-2-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "y"}]))
        records = ledger.load_records(self.store)
        self.assertTrue(all(r.ok for r in records))  # both pass validation

        items = ledger.compute_open_items(records, resolved_ids=set())  # must not raise

        sibling_items = [i for i in items if i.source == "task-2-python-coder"]
        self.assertEqual(len(sibling_items), 1)
        self.assertEqual(sibling_items[0].kind, "duplication_pending")

        crashed_items = [i for i in items if i.source == "task-1-python-coder"]
        self.assertEqual(len(crashed_items), 1)
        self.assertEqual(crashed_items[0].kind, "malformed")
        self.assertTrue(crashed_items[0].summary)  # names the error


# --- list_shapes / render_shapes ---

class TestShapes(LedgerTestCase):
    def test_shapes_lists_every_new_shared_symbol(self):
        # Acceptance criterion 6.
        _write(self.store, "task-1-python-coder.json", _coder(
            new_shared_symbols=[{"symbol": "foo", "path": "a.py", "why": "shared"}]))
        [shape] = ledger.list_shapes(ledger.load_records(self.store))
        self.assertEqual(shape.symbol, "foo")

    def test_role_filter_ignores_new_shared_symbols_on_non_coder_record(self):
        # list_shapes filters by role == "coder" explicitly; a
        # spec-reviewer record carrying a stray new_shared_symbols field
        # (informational and unvalidated for that role) must not surface
        # as a shape — a mutant weakening the role check to "any role" or
        # dropping it entirely is caught here.
        data = _spec_reviewer(status="compliant")
        data["new_shared_symbols"] = [{"symbol": "foo", "path": "a.py", "why": "shared"}]
        _write(self.store, "task-1-spec-reviewer.json", data)
        records = ledger.load_records(self.store)
        self.assertTrue(records[0].ok)  # the stray key doesn't fail validation
        self.assertEqual(ledger.list_shapes(records), [])

    def test_shapes_never_appear_in_open(self):
        # A record whose only content is a new_shared_symbols entry has no
        # duplication_pending/cannot_verify/open-status — its shape must
        # not leak into `open` as any kind of item.
        _write(self.store, "task-1-python-coder.json", _coder(
            new_shared_symbols=[{"symbol": "foo", "path": "a.py", "why": "shared"}]))
        records = ledger.load_records(self.store)
        items = ledger.compute_open_items(records, resolved_ids=set())
        self.assertEqual(items, [])

    def test_non_dict_shape_entry_fails_loud_not_silently_dropped(self):
        # A non-dict new_shared_symbols entry must not be silently skipped
        # by list_shapes: validate_record rejects it, so the whole record
        # is malformed (loud), visible as an open item, and contributes no
        # shapes.
        _write(self.store, "task-1-python-coder.json", _coder(
            new_shared_symbols=["not-a-dict"]))
        records = ledger.load_records(self.store)
        self.assertEqual(ledger.list_shapes(records), [])
        kinds = [i.kind for i in ledger.compute_open_items(records, resolved_ids=set())]
        self.assertEqual(kinds, ["malformed"])

    def test_render_shapes_empty_placeholder(self):
        self.assertEqual(ledger.render_shapes([]), "(none recorded yet)")

    def test_render_shapes_non_empty_lists_symbol_path_why_source(self):
        shapes = [ledger.Shape("foo", "a.py", "shared helper", "task-1-python-coder")]
        rendered = ledger.render_shapes(shapes)
        self.assertIn("foo", rendered)
        self.assertIn("a.py", rendered)
        self.assertIn("shared helper", rendered)
        self.assertIn("task-1-python-coder", rendered)


# --- render_store_markdown / cmd_read ---

class TestRenderStoreMarkdown(LedgerTestCase):
    def test_mixed_valid_malformed_and_progress_log(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        (self.store / "task-2-bad.json").write_text("not json", encoding="utf-8")
        progress = self.store / ledger.PROGRESS_FILENAME
        progress.write_text(
            '{"type": "progress", "task": 1, "note": "did the thing"}\n'
            '{"type": "resolution", "resolves": '
            '"task-1-python-coder#duplication_pending[0]", "note": "hoisted"}\n',
            encoding="utf-8")

        records = ledger.load_records(self.store)
        log = ledger.load_progress_log(self.store)
        rendered = ledger.render_store_markdown(records, log)

        self.assertIn("task-1-python-coder", rendered)
        self.assertIn('"status": "done"', rendered)  # valid record's payload dumped as JSON
        self.assertIn("task-2-bad", rendered)
        self.assertIn("MALFORMED", rendered)
        self.assertIn("did the thing", rendered)
        self.assertIn("hoisted", rendered)

    def test_complete_entries_render_distinctly_from_progress(self):
        log = [
            {"type": "progress", "task": 5, "note": "still working"},
            {"type": "complete", "task": 5, "note": "shipped"},
        ]
        rendered = ledger.render_store_markdown([], log)
        self.assertIn("still working", rendered)
        self.assertIn("shipped", rendered)
        # The complete line is visually distinguishable from a plain
        # progress line — not just present, but tagged as complete.
        complete_line = next(ln for ln in rendered.splitlines() if "shipped" in ln)
        progress_line = next(ln for ln in rendered.splitlines() if "still working" in ln)
        self.assertNotEqual(complete_line, progress_line)
        self.assertIn("COMPLETE", complete_line)
        self.assertNotIn("COMPLETE", progress_line)

    def test_cmd_read_prints_rendered_markdown(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_read(self.store)
        output = buf.getvalue()
        self.assertIn("# SDD Ledger", output)
        self.assertIn("task-1-python-coder", output)


# --- progress.jsonl ---

class TestProgressLog(LedgerTestCase):
    def test_append_guards_missing_trailing_newline(self):
        # Appending to a file whose last line lacks a trailing newline
        # must not merge with that line.
        progress = self.store / ledger.PROGRESS_FILENAME
        self.store.mkdir(exist_ok=True)
        progress.write_text('{"type": "progress", "task": 1, "note": "first"}',
                             encoding="utf-8")
        ledger._append_jsonl(progress, {"type": "progress", "task": 2, "note": "second"})
        lines = progress.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["note"], "first")
        self.assertEqual(json.loads(lines[1])["note"], "second")

    def test_non_object_progress_line_raises_naming_the_line(self):
        # Loud failure, not skip-with-warning (user ruling 2026-08-27): this
        # log feeds resolve's already-resolved gate, so a silently dropped
        # resolution line would silently re-open an item.
        self.store.mkdir(exist_ok=True)
        progress = self.store / ledger.PROGRESS_FILENAME
        progress.write_text(
            '{"type": "progress", "task": 1, "note": "ok"}\n["not", "an", "object"]\n',
            encoding="utf-8")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.load_progress_log(self.store)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("not a JSON object", str(ctx.exception))

    def test_unparseable_progress_line_raises_naming_the_line(self):
        self.store.mkdir(exist_ok=True)
        progress = self.store / ledger.PROGRESS_FILENAME
        progress.write_text(
            '{"type": "progress", "task": 1, "note": "ok"}\nnot json at all\n',
            encoding="utf-8")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.load_progress_log(self.store)
        self.assertIn("line 2", str(ctx.exception))

    def test_resolutions_from_log_ignores_non_string_resolves(self):
        log = [{"type": "resolution", "resolves": ["not", "a", "string"]}]
        self.assertEqual(ledger.resolutions_from_log(log), {})

    def test_resolutions_from_log_maps_id_to_note(self):
        log = [{"type": "resolution", "resolves": "task-1-python-coder#status",
                "note": "hoisted"}]
        self.assertEqual(ledger.resolutions_from_log(log),
                          {"task-1-python-coder#status": "hoisted"})


# --- typed completion (spec Sec 6, amended 2026-08-27) ---

class TestCompletion(LedgerTestCase):
    def test_completed_task_ids_lists_only_complete_type_entries(self):
        log = [
            {"type": "progress", "task": 1, "note": "still going"},
            {"type": "complete", "task": 2, "note": "shipped"},
            {"type": "resolution", "resolves": "x#status", "note": ""},
        ]
        self.assertEqual(ledger.completed_task_ids(log), ["2"])

    def test_completed_task_ids_dedupes_preserving_first_seen_order(self):
        log = [
            {"type": "complete", "task": 3, "note": "first note"},
            {"type": "complete", "task": 1, "note": "first note"},
            {"type": "complete", "task": 3, "note": "re-marked"},
        ]
        self.assertEqual(ledger.completed_task_ids(log), ["3", "1"])

    def test_cmd_append_writes_a_typed_complete_entry(self):
        _completable(self.store, 5)
        ledger.cmd_append(self.store, "complete", 5, "shipped")
        log = ledger.load_progress_log(self.store)
        self.assertEqual(log[-1], {"type": "complete", "task": 5, "note": "shipped"})
        # append routes creation through ensure_store, so a store born from
        # an append (not store-dir) is still self-ignoring.
        self.assertEqual((self.store / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_cmd_completed_prints_one_task_id_per_line(self):
        for task in (2, 5):
            _completable(self.store, task)
        ledger.cmd_append(self.store, "complete", 2, "shipped")
        ledger.cmd_append(self.store, "complete", 5, "also shipped")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_completed(self.store)
        self.assertEqual(buf.getvalue().splitlines(), ["2", "5"])

    def test_cmd_completed_prints_nothing_on_empty_store(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_completed(self.store)
        self.assertEqual(buf.getvalue(), "")


# --- close-gate rounds (batched close remediation, 2026-10-04) ---

class TestCloseRounds(LedgerTestCase):
    def test_close_rounds_counts_only_close_round_entries(self):
        log = [
            {"type": "complete", "task": 1, "note": "shipped"},
            {"type": "close_round", "round": 1, "note": "first close"},
            {"type": "resolution", "resolves": "x#status", "note": ""},
        ]
        self.assertEqual(ledger.close_rounds(log), 1)

    def test_first_and_second_rounds_print_their_number_and_append_typed_entries(self):
        for expected, head in ((1, "aaa1111"), (2, "bbb2222")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ledger.cmd_close_round(self.store, f"round {expected}", head, expect=expected)
            self.assertEqual(buf.getvalue().strip(), str(expected))
        log = ledger.load_progress_log(self.store)
        # Each round records the HEAD it reviewed, so round 2 can name the
        # remediation range (round-1 head..HEAD) without memory.
        self.assertEqual(log, [
            {"type": "close_round", "round": 1, "head": "aaa1111", "note": "round 1"},
            {"type": "close_round", "round": 2, "head": "bbb2222", "note": "round 2"},
        ])

    def test_round_past_the_cap_raises_and_appends_nothing(self):
        # The cap is the escalation trigger: a third close round must not
        # start silently — round 2's findings go to the user instead.
        for n in range(ledger.CLOSE_ROUND_CAP):
            with contextlib.redirect_stdout(io.StringIO()):
                ledger.cmd_close_round(self.store, f"round {n + 1}", "abc1234", expect=n + 1)
        before = ledger.load_progress_log(self.store)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_close_round(self.store, "one more", "abc1234",
                                   expect=ledger.CLOSE_ROUND_CAP + 1)
        message = str(ctx.exception)
        self.assertIn(f"cap ({ledger.CLOSE_ROUND_CAP})", message)
        self.assertIn("escalate", message)
        # The error must not read as an invitation to bypass the cap.
        self.assertIn("never clear", message)
        self.assertEqual(ledger.load_progress_log(self.store), before)

    def test_expect_mismatch_raises_and_appends_nothing(self):
        # A fresh close expects round 1; a store left by an earlier run
        # would otherwise silently start it at round 2.
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_close_round(self.store, "old run", "abc1234", expect=1)
        before = ledger.load_progress_log(self.store)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_close_round(self.store, "new feature", "def5678", expect=1)
        message = str(ctx.exception)
        self.assertIn("expected round 1", message)
        self.assertIn("clear", message)
        self.assertEqual(ledger.load_progress_log(self.store), before)

    def _two_rounds(self):
        for n in (1, 2):
            with contextlib.redirect_stdout(io.StringIO()):
                ledger.cmd_close_round(self.store, "plan.md", "abc1234", expect=n)

    def test_expect_one_on_a_capped_store_says_finish_or_escalate_not_resume(self):
        # "Resume round 1, then --expect 2" would point at a command that
        # then fails; with both rounds used, the only moves are finishing
        # round 2's triage and escalating — or clearing an unrelated run.
        self._two_rounds()
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_close_round(self.store, "plan.md", "def5678", expect=1)
        message = str(ctx.exception)
        self.assertIn("both rounds", message)
        self.assertIn("escalate", message)
        self.assertNotIn("--expect 2", message)

    def test_repeated_expect_two_past_the_cap_gets_the_escalation_message(self):
        self._two_rounds()
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_close_round(self.store, "plan.md", "def5678", expect=2)
        self.assertIn(f"cap ({ledger.CLOSE_ROUND_CAP})", str(ctx.exception))
        self.assertIn("escalate", str(ctx.exception))

    def test_expect_two_on_an_empty_store_raises(self):
        # Round 2 only follows a round 1 of the same run.
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_close_round(self.store, "orphan", "abc1234", expect=2)
        self.assertIn("expected round 2", str(ctx.exception))

    def test_clear_resets_the_round_count(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_close_round(self.store, "round 1", "abc1234", expect=1)
        ledger.cmd_clear(self.store)
        self.assertEqual(ledger.close_rounds(ledger.load_progress_log(self.store)), 0)

    def test_close_round_entries_render_in_read(self):
        log = [{"type": "close_round", "round": 2, "note": "after remediation"}]
        rendered = ledger.render_store_markdown([], log)
        line = next(ln for ln in rendered.splitlines() if "after remediation" in ln)
        self.assertIn("close round 2", line)
        self.assertNotIn("unknown entry", rendered)


# --- store-dir (spec Sec 6, amended 2026-08-27) ---

class TestCmdStoreDir(LedgerTestCase):
    def test_prints_the_resolved_store_dir(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_store_dir(self.store)
        self.assertEqual(buf.getvalue().strip(), str(self.store))

    def test_creates_the_store_and_seeds_its_gitignore(self):
        # store-dir is the session's first ledger call, and record-writing
        # agents use the Write tool afterward — so this is the one
        # guaranteed spot to seed the self-ignoring .gitignore.
        store = self.store / "fresh"
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_store_dir(store)
        self.assertTrue(store.is_dir())
        self.assertEqual((store / ".gitignore").read_text(encoding="utf-8"), "*\n")


# --- resolve (write path) ---

class TestCmdResolve(LedgerTestCase):
    def test_succeeds_for_currently_open_item(self):
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry]))
        ledger.cmd_resolve(self.store, _dup_id("task-1-python-coder", entry), "note")
        log = ledger.load_progress_log(self.store)
        self.assertEqual(len(log), 1)
        # resolve routes creation through ensure_store too, so it seeds the
        # self-ignoring .gitignore on a store that lacks one.
        self.assertEqual((self.store / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_unknown_id_raises_naming_currently_open_resolvable_ids(self):
        # A resolve matching nothing is not a silent no-op.
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry]))
        real_id = _dup_id("task-1-python-coder", entry)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, "task-1-python-coder#duplication_pending[deadbeef]", "")
        message = str(ctx.exception)
        self.assertIn("matches no open resolvable item", message)
        self.assertIn(real_id, message)
        # A never-was-open id gets no whole-record explanation — that
        # suffix is reserved for ids that are real but non-resolvable.
        self.assertNotIn("not resolvable", message)

    def test_non_resolvable_kind_id_raises_naming_whole_record_rule(self):
        # #status is a whole-record item — never resolvable, even though
        # it's a real, currently-open id; the error must name the rule so
        # an orchestrator pasting this id straight from `open` learns why
        # it doesn't work, instead of just "not found".
        _write(self.store, "task-1-python-coder.json", _coder(status="blocked"))
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, "task-1-python-coder#status", "")
        message = str(ctx.exception)
        self.assertIn("matches no open resolvable item", message)
        self.assertIn("not resolvable", message)
        self.assertIn("clear when the record is rewritten", message)

    def test_already_resolved_raises_naming_prior_note(self):
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry]))
        resolve_id = _dup_id("task-1-python-coder", entry)
        ledger.cmd_resolve(self.store, resolve_id, "first note")

        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, resolve_id, "second note")
        message = str(ctx.exception)
        self.assertIn("already resolved", message)
        self.assertIn("first note", message)


# --- _entry_digest canonicalization (independent of the function under
# test: expected hex is hardcoded, not recomputed via ledger._entry_digest
# itself) ---

class TestEntryDigestCanonicalization(unittest.TestCase):
    def test_digest_matches_a_known_literal_hex_value(self):
        # Pinned externally: sha1('{"sites":["a.py:1"],"wants_owner":
        # "b.py","why":"x"}').hexdigest()[:8], computed independently of
        # _entry_digest's own implementation, so a mutant that changes the
        # hash algorithm, the digest length, or the separators/sort_keys
        # canonicalization is caught by a value mismatch, not just a
        # shape/type check.
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        self.assertEqual(ledger._entry_digest(entry), "ea29e8b1")

    def test_digest_is_independent_of_key_order(self):
        entry_a = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        entry_b = {"why": "x", "sites": ["a.py:1"], "wants_owner": "b.py"}
        self.assertEqual(ledger._entry_digest(entry_a), ledger._entry_digest(entry_b))
        self.assertEqual(ledger._entry_digest(entry_b), "ea29e8b1")


# --- content-derived resolution ids (spec Sec 6, amended 2026-08-27) ---

class TestContentDerivedResolutionIds(LedgerTestCase):
    def test_rewritten_entry_at_same_position_gets_a_new_id_and_stays_open(self):
        # A resolution id names *what an entry says*, not *where it sits*.
        # Resolving entry A at duplication_pending[0], then rewriting the
        # same record (last-write-wins on re-review) with a different
        # entry B at that same position, must not suppress B — B is a new
        # problem and must still show as open under its own, different id.
        entry_a = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "hoist a"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry_a]))
        id_a = _dup_id("task-1-python-coder", entry_a)
        ledger.cmd_resolve(self.store, id_a, "hoisted a")

        entry_b = {"sites": ["c.py:9"], "wants_owner": "d.py", "why": "hoist b"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry_b]))
        id_b = _dup_id("task-1-python-coder", entry_b)
        self.assertNotEqual(id_a, id_b)

        records = ledger.load_records(self.store)
        resolved = set(ledger.resolutions_from_log(ledger.load_progress_log(self.store)))
        items = ledger.compute_open_items(records, resolved)
        self.assertEqual([i.id for i in items], [id_b])


# --- clear ---

class TestClear(LedgerTestCase):
    def test_clear_deletes_by_naming_convention_leaves_unrelated_files(self):
        # clear is a deterministic naming-convention match (task-*-* /
        # final-*), independent of content validity — a malformed
        # record-attempt is clearable, an unrelated notes.json is not.
        valid = _write(self.store, "task-1-python-coder.json", _coder())
        malformed = self.store / "task-2-python-coder.json"
        malformed.write_text("not json at all", encoding="utf-8")
        final_record = _write(self.store, "final-python-coder.json", _coder(task="final"))
        unrelated = self.store / "notes.json"
        unrelated.write_text("not a record", encoding="utf-8")
        progress = self.store / ledger.PROGRESS_FILENAME
        progress.write_text('{"type": "progress", "task": 1, "note": "x"}\n', encoding="utf-8")

        ledger.cmd_clear(self.store)

        self.assertFalse(valid.exists())
        self.assertFalse(malformed.exists())  # malformed record-attempt is clearable
        self.assertFalse(final_record.exists())
        self.assertFalse(progress.exists())
        self.assertTrue(unrelated.exists())  # unrelated *.json is never touched

    def test_clear_deletes_gate_reports_and_handoff_files(self):
        # Gate reviewers re-run at the same report path and read it as
        # their prior verdict, so a report surviving `clear` would anchor
        # an unrelated run's reviewer on stale findings.
        names = ["design-review-python-design-reviewer.md", "intent-recheck.md", "intent-issue.md",
                 "mutation-review.md", "task-3-brief.md", "task-3-report.md",
                 "task-3-decision-c2.md", "review-whole-change.diff"]
        for name in names:
            (self.store / name).write_text("x", encoding="utf-8")
        keep = self.store / "notes.md"
        keep.write_text("user notes", encoding="utf-8")

        ledger.cmd_clear(self.store)

        for name in names:
            self.assertFalse((self.store / name).exists(), name)
        self.assertTrue(keep.exists())


# --- check (write-time gate) ---

class TestCmdCheck(LedgerTestCase):
    def test_valid_record_returns_silently(self):
        path = _write(self.store, "task-1-python-coder.json", _coder())
        ledger.cmd_check(str(path))  # no raise

    def test_invalid_record_raises_naming_field_value_and_allowed_set(self):
        # spec Sec 6: check's error names the offending field, the
        # offending value, and the allowed set — not just the field.
        path = _write(self.store, "task-1-python-coder.json", _coder(status="Blocked"))
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_check(str(path))
        message = str(ctx.exception)
        self.assertIn("status", message)
        self.assertIn("Blocked", message)  # offending value
        for allowed in ledger.STATUS_ENUMS["coder"]:  # allowed set
            self.assertIn(allowed, message)

    def test_unhashable_role_raises_record_error_not_type_error(self):
        # `check` must never traceback. A record with an unhashable role
        # (e.g. a list, valid JSON but the wrong shape) must raise a
        # corrective RecordError, not crash the `role not in VALID_ROLES`
        # membership test with a bare TypeError.
        path = _write(self.store, "task-1-python-coder.json",
                       _coder(role=["not", "hashable"]))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(path))

    def test_missing_file_raises(self):
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(self.store / "nope.json"))


class TestCoderModel(LedgerTestCase):
    """Coders run on sonnet; opus only under the user's logged ruling for
    the task. A coder that refused its model changed nothing, so its
    needs_context record passes on any model."""

    def _check(self, **overrides) -> None:
        ledger.cmd_check(str(_write(self.store, "task-1-python-coder.json", _coder(**overrides))))

    def assertRefused(self, fragment: str, **overrides) -> None:
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(**overrides)
        self.assertIn(fragment, str(ctx.exception))

    def test_a_sonnet_coder_passes(self):
        self._check()

    def test_check_requires_the_model_but_an_older_record_still_loads(self):
        data = _coder()
        del data["model"]
        path = _write(self.store, "task-1-python-coder.json", data)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_check(str(path))
        self.assertIn("model", str(ctx.exception))
        (rec,) = ledger.load_records(self.store)
        self.assertTrue(rec.ok)

    def test_an_opus_coder_needs_the_users_ruling_for_its_task(self):
        self.assertRefused(ledger.OPUS_RULING_PREFIX, model="opus")
        ledger.cmd_append(self.store, "progress", 2, "user ruling: opus coder for task 2")
        ledger.cmd_append(self.store, "progress", 1, "user ruling: fix it")
        self.assertRefused(ledger.OPUS_RULING_PREFIX, model="opus")
        ledger.cmd_append(self.store, "progress", 1, "User ruling: opus coder, the fix stalled")
        self._check(model="opus")

    def test_no_ruling_admits_a_model_other_than_sonnet_or_opus(self):
        ledger.cmd_append(self.store, "progress", 1, "user ruling: opus coder")
        self.assertRefused("sonnet", model="haiku")

    def test_the_model_is_read_by_family_not_spelling(self):
        for spelling in ("Sonnet 5.5", "claude-sonnet-5-5", " SONNET "):
            self._check(model=spelling)
        self.assertRefused("sonnet", model="claude-opus-5-5")
        ledger.cmd_append(self.store, "progress", 1, "user ruling: opus coder")
        self._check(model="Opus 5.5")

    def test_a_coder_that_refused_its_model_passes_on_any_model(self):
        self._check(model="opus", status="needs_context")
        self._check(model="haiku", status="blocked")

    def test_stats_shows_each_coders_model(self):
        ledger.ensure_store(self.store)  # history is kept only inside a store
        self._check()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_stats(self.store)
        self.assertRegex(out.getvalue(), r"python-coder\s+c1\s+done\s+findings=0\s+model=sonnet")

    def test_invalid_json_raises(self):
        path = self.store / "task-1-bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(path))

    def test_undecodable_bytes_raise_loud(self):
        path = self.store / "task-1-bad.json"
        path.write_bytes(b"\xff\xfe not utf-8")
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(path))

    def test_record_that_crashes_open_rendering_fails_check(self):
        # check exercises the same item-construction path `open` uses
        # (spec Sec 6): sites=[1, 2] passes validate_record (an
        # informational sub-field) but crashes str.join inside
        # _describe_duplication when rendered as an open item — so a
        # record this shape must fail check, not pass it and only blow up
        # later at query time (see TestComputeOpenItems's sibling test for
        # the `open`-side isolation this complements).
        path = _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": [1, 2], "wants_owner": "b.py", "why": "x"}]))
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_check(str(path))
        self.assertIn("duplication_pending", str(ctx.exception))

    def test_bare_filename_resolves_against_store(self):
        # --store must never be accepted-and-ignored for `check`: a bare
        # record filename (no path separator) resolves against it.
        _write(self.store, "task-1-python-coder.json", _coder())
        ledger.cmd_check("task-1-python-coder.json", str(self.store))  # no raise

    def test_bare_filename_without_store_uses_default_store_dir(self):
        # A path containing a separator never touches the store at all,
        # so it needs no store/git dependency; confirm the reverse holds
        # too — a genuinely bare filename does resolve through
        # get_store_dir, which raises outside a git repo with no --store.
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError):
                ledger.cmd_check("task-1-python-coder.json")


# --- get_store_dir ---

class TestGetStoreDir(unittest.TestCase):
    def test_override_bypasses_git(self):
        with mock.patch("subprocess.check_output") as check_output:
            result = ledger.get_store_dir("/some/explicit/dir")
        check_output.assert_not_called()
        self.assertEqual(result, Path("/some/explicit/dir").resolve())

    def test_default_is_dot_sdd_at_repo_toplevel(self):
        # --show-toplevel resolves per-worktree, so each linked worktree
        # gets its own in-tree store; the derivation must never touch
        # --git-path (paths under .git/ are off-limits to tooling).
        with mock.patch("subprocess.check_output",
                        return_value=b"/repo/top\n") as check_output:
            result = ledger.get_store_dir()
        self.assertIn("--show-toplevel", check_output.call_args[0][0])
        self.assertEqual(result, (Path("/repo/top") / ".sdd").resolve())

    def test_no_override_outside_git_raises_runtime_error(self):
        # Library entry points raise instead of calling sys.exit, so
        # task_brief.py (or a test) can catch this itself.
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError):
                ledger.get_store_dir()


# --- ensure_store ---

class TestEnsureStore(LedgerTestCase):
    def test_creates_directory_and_self_ignoring_gitignore(self):
        store = self.store / "nested" / "sdd"
        result = ledger.ensure_store(store)
        self.assertEqual(result, store)
        self.assertTrue(store.is_dir())
        self.assertEqual((store / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_never_overwrites_an_existing_gitignore(self):
        store = self.store / "sdd"
        store.mkdir()
        (store / ".gitignore").write_text("!keep-me\n", encoding="utf-8")
        ledger.ensure_store(store)
        self.assertEqual((store / ".gitignore").read_text(encoding="utf-8"), "!keep-me\n")


# --- constant-table consistency ---

class TestTableConsistency(unittest.TestCase):
    """The role/field/kind tables encode one contract across several
    module-level constants; these pin the cross-table relationships so a
    future enum edit that breaks one silently is caught here, not as a
    KeyError inside `check`."""

    def test_decision_list_fields_name_only_valid_roles(self):
        self.assertLessEqual(set(ledger.DECISION_LIST_FIELDS), ledger.VALID_ROLES)

    def test_every_resolvable_kind_is_reachable_from_some_role(self):
        # A resolvable kind no DECISION_LIST_FIELDS entry names could never
        # produce an open item, so `resolve` could never match it.
        reachable = {f for fields in ledger.DECISION_LIST_FIELDS.values() for f in fields}
        reachable.add(ledger.ESCALATION_KIND)  # a decision's escalate choices
        self.assertLessEqual(ledger.RESOLVABLE_KINDS, reachable)

    def test_open_status_sets_are_subsets_of_their_role_enums(self):
        self.assertLessEqual(ledger.CODER_OPEN_STATUSES, ledger.STATUS_ENUMS["coder"])
        reviewer_statuses = set()
        for role, statuses in ledger.STATUS_ENUMS.items():
            if role != "coder":
                reviewer_statuses |= statuses
        self.assertLessEqual(ledger.REVIEWER_OPEN_STATUSES, reviewer_statuses)

    def test_derived_tables_track_their_sources(self):
        # Tautological today (both are derived), but pins the derivation
        # itself: reverting either to a hand-written literal that then
        # drifts fails here first.
        self.assertEqual(ledger.VALID_ROLES, frozenset(ledger.STATUS_ENUMS))
        self.assertEqual(ledger.RESOLVABLE_KINDS,
                         frozenset(ledger._FIELD_DESCRIBERS) | {ledger.ESCALATION_KIND})


# --- fix baseline: snapshot / diff-since (2026-10-06) ---

class GitRepoTestCase(unittest.TestCase):
    """A throwaway repo with one committed file, a.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                    ["git", "config", "user.name", "t"]):
            subprocess.run(cmd, cwd=self.repo, check=True)
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True)

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True,
                              capture_output=True, text=True).stdout


class TestFixBaseline(GitRepoTestCase):
    """Coders never commit before review passes, so a fix's edits land in
    the same working tree as the uncommitted cycle-1 work. A tree
    snapshot taken before the fix is the only way to see the fix alone."""

    def test_diff_since_shows_only_the_fix_including_new_files(self):
        # Cycle-1 work: uncommitted edit plus a new untracked file.
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "cycle1.py").write_text("c1 = True\n", encoding="utf-8")
        baseline = ledger.snapshot_tree(self.repo)
        # The fix: another edit and a new file of its own.
        (self.repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        (self.repo / "fix.py").write_text("f = True\n", encoding="utf-8")

        diff = ledger.diff_since(self.repo, baseline)

        self.assertIn("-x = 2", diff)
        self.assertIn("+x = 3", diff)
        self.assertIn("fix.py", diff)
        self.assertNotIn("cycle1.py", diff)  # cycle-1 work is in the baseline
        self.assertNotIn("-x = 1", diff)

    def test_same_size_edit_in_the_index_write_second_is_captured(self):
        # Git trusts a cached stat only for entries older than the index
        # file; an entry whose mtime equals the index's is "racily clean"
        # and re-read by content. A throwaway index copy that takes a fresh
        # mtime loses that protection and misses a same-size edit made in
        # that second. Setup: a real (not size-0 smudged) stat entry, an
        # index mtime equal to the file's, and stat checks that see only
        # size and mtime, so content is the only signal left.
        self._git("config", "core.trustctime", "false")
        self._git("config", "core.checkStat", "minimal")
        a = self.repo / "a.py"
        old = a.stat().st_mtime_ns - 10 * 10**9
        os.utime(a, ns=(old, old))
        self._git("update-index", "--really-refresh")
        index = self.repo / ".git" / "index"
        os.utime(index, ns=(old, old))
        a.write_text("x = 7\n", encoding="utf-8")  # same size as "x = 1\n"
        os.utime(a, ns=(old, old))
        tree = ledger.snapshot_tree(self.repo)
        self.assertEqual(self._git("cat-file", "-p", f"{tree}:a.py"), "x = 7\n")

    def test_diff_since_limited_to_paths_excludes_a_parallel_tasks_edits(self):
        # Tasks in one SDD stage share the working tree; a fix's diff must
        # not show the other task's concurrent work.
        (self.repo / "mine.py").write_text("m = 1\n", encoding="utf-8")
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "mine.py").write_text("m = 2\n", encoding="utf-8")
        (self.repo / "theirs.py").write_text("t = 1\n", encoding="utf-8")
        diff = ledger.diff_since(self.repo, baseline, ["mine.py"])
        self.assertIn("+m = 2", diff)
        self.assertNotIn("theirs.py", diff)

    def test_diff_since_rejects_an_option_shaped_tree(self):
        with self.assertRaises(ledger.RecordError):
            ledger.diff_since(self.repo, "--output=pwned", [])
        self.assertFalse((self.repo / "pwned").exists())

    def test_diff_since_survives_non_utf8_content(self):
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "a.py").write_bytes(b"caf\xe9\n")
        diff = ledger.diff_since(self.repo, baseline)
        self.assertIn("a.py", diff)

    def test_diff_since_ignores_textconv(self):
        (self.repo / ".gitattributes").write_text("*.py diff=up\n", encoding="utf-8")
        self._git("config", "diff.up.textconv", "tr a-z A-Z <")
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "a.py").write_text("x = 5\n", encoding="utf-8")
        diff = ledger.diff_since(self.repo, baseline)
        self.assertIn("+x = 5", diff)
        self.assertNotIn("X = 5", diff)

    def test_submodule_paths_found_from_a_subdirectory(self):
        head = self._git("rev-parse", "HEAD").strip()
        self._git("update-index", "--add", "--cacheinfo", f"160000,{head},mod")
        sub = self.repo / "sub"
        sub.mkdir()
        self.assertEqual(ledger.submodule_paths(sub), ["mod"])

    def test_snapshot_entries_render_in_read(self):
        log = [{"type": "snapshot", "task": 4, "label": "pre-fix c2", "tree": "abc123"}]
        rendered = ledger.render_store_markdown([], log)
        line = next(ln for ln in rendered.splitlines() if "abc123" in ln)
        self.assertIn("pre-fix c2", line)
        self.assertNotIn("unknown entry", rendered)

    def test_snapshot_leaves_the_real_index_and_tree_untouched(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "new.py").write_text("n = 1\n", encoding="utf-8")
        before = self._git("status", "--porcelain")
        ledger.snapshot_tree(self.repo)
        self.assertEqual(self._git("status", "--porcelain"), before)
        self.assertEqual(self._git("diff", "--cached"), "")

    def test_diff_since_ignores_color_and_external_diff_config(self):
        # Agents read this output; the user's diff config must not leak in.
        self._git("config", "color.ui", "always")
        self._git("config", "diff.external", "/usr/bin/false")
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "a.py").write_text("x = 9\n", encoding="utf-8")
        diff = ledger.diff_since(self.repo, baseline)
        self.assertIn("+x = 9", diff)
        self.assertNotIn("\x1b", diff)

    def test_split_index_config_leaves_no_orphan_shared_index(self):
        self._git("config", "core.splitIndex", "true")
        self._git("update-index", "--split-index")
        before = sorted(p.name for p in (self.repo / ".git").glob("sharedindex.*"))
        (self.repo / "new.py").write_text("n = 1\n", encoding="utf-8")
        ledger.snapshot_tree(self.repo)
        after = sorted(p.name for p in (self.repo / ".git").glob("sharedindex.*"))
        self.assertEqual(after, before)

    def test_submodule_paths_are_reported(self):
        # git add -A records only a submodule's commit, so edits inside it
        # are invisible to the snapshot; callers must be told.
        head = self._git("rev-parse", "HEAD").strip()
        self._git("update-index", "--add", "--cacheinfo", f"160000,{head},mod")
        self.assertEqual(ledger.submodule_paths(self.repo), ["mod"])

    def test_no_submodules_reports_none(self):
        self.assertEqual(ledger.submodule_paths(self.repo), [])

    def test_tracked_file_matching_gitignore_stays_in_the_snapshot(self):
        # add -A skips ignored files; only the copied real index keeps a
        # tracked-but-now-ignored file in the tree instead of dropping it.
        (self.repo / "keep.log").write_text("k\n", encoding="utf-8")
        self._git("add", "keep.log")
        self._git("commit", "-qm", "track a log")
        (self.repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        tree = ledger.snapshot_tree(self.repo)
        self.assertIn("keep.log", self._git("ls-tree", "--name-only", tree))

    def test_diff_since_ignores_relative_and_prefix_config(self):
        self._git("config", "diff.noprefix", "true")
        self._git("config", "diff.relative", "true")
        (self.repo / "sub").mkdir()
        (self.repo / "sub" / "s.py").write_text("s = 1\n", encoding="utf-8")
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "sub" / "s.py").write_text("s = 2\n", encoding="utf-8")
        diff = ledger.diff_since(self.repo / "sub", baseline)
        self.assertIn("+++ b/sub/s.py", diff)

    def test_missing_paths_names_a_path_in_neither_tree(self):
        baseline = ledger.snapshot_tree(self.repo)
        self.assertEqual(ledger.missing_paths(self.repo, ["a.py", "nope.py"], baseline),
                         ["nope.py"])

    def test_cli_diff_since_warns_about_a_path_that_matches_nothing(self):
        tree = ledger.snapshot_tree(self.repo)
        result = subprocess.run([sys.executable, str(LEDGER_PY), "diff-since", tree, "nope.py"],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stderr)
        self.assertIn("nope.py", result.stderr)

    def test_cli_diff_since_warns_about_submodules(self):
        head = self._git("rev-parse", "HEAD").strip()
        tree = ledger.snapshot_tree(self.repo)
        self._git("update-index", "--add", "--cacheinfo", f"160000,{head},mod")
        result = subprocess.run([sys.executable, str(LEDGER_PY), "diff-since", tree],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertIn("WARNING", result.stderr)
        self.assertIn("mod", result.stderr)

    def test_cli_reports_a_missing_git_binary_cleanly(self):
        env = {**os.environ, "PATH": "/nonexistent"}
        result = subprocess.run([sys.executable, str(LEDGER_PY), "diff-since", "abc"],
                                cwd=self.repo, capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_warns_about_submodules_on_stderr(self):
        head = self._git("rev-parse", "HEAD").strip()
        self._git("update-index", "--add", "--cacheinfo", f"160000,{head},mod")
        result = subprocess.run(
            [sys.executable, str(LEDGER_PY), "snapshot", "--task", "1", "--label", "x",
             "--store", str(self.repo / ".sdd")],
            cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stderr)
        self.assertIn("mod", result.stderr)

    def test_cli_snapshot_then_diff_since_round_trip(self):
        (self.repo / "cycle1.py").write_text("c1 = True\n", encoding="utf-8")
        run = lambda *a: subprocess.run(  # noqa: E731
            [sys.executable, str(LEDGER_PY), *a], cwd=self.repo,
            capture_output=True, text=True)
        snap = run("snapshot", "--task", "3", "--label", "pre-fix c2",
                   "--store", str(self.repo / ".sdd"))
        self.assertEqual(snap.returncode, 0, snap.stderr)
        tree = snap.stdout.strip()
        (self.repo / "fix.py").write_text("f = True\n", encoding="utf-8")
        diff = run("diff-since", tree)
        self.assertEqual(diff.returncode, 0, diff.stderr)
        self.assertIn("fix.py", diff.stdout)
        self.assertNotIn("cycle1.py", diff.stdout)
        bad = run("diff-since", "not-a-tree")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("ERROR: git", bad.stderr)

    def test_cmd_snapshot_records_a_typed_entry_and_prints_the_tree(self):
        store = self.repo / ".sdd"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_snapshot(store, 4, "pre-fix c2", "deadbeef")
        self.assertEqual(buf.getvalue().strip(), "deadbeef")
        self.assertEqual(ledger.load_progress_log(store),
                         [{"type": "snapshot", "task": 4, "label": "pre-fix c2",
                           "tree": "deadbeef"}])


# --- decision records (2026-10-09) ---

_SPEC_ISSUE = _finding(kind="missing", claim="bad value carried", rule="value is validated")
_QUALITY_FINDING = _finding(severity=2, claim="too broad", rule="catch narrowly")
_NOTE = _finding(severity=1, claim="a note", rule="name says what it holds")


def _candidate(name: str, chosen: bool = False, precedent: str = "a.py:1") -> dict:
    return {"name": name, "precedent": precedent, "why": f"why {name}", "chosen": chosen}


def _fix_choice(findings: list[str], **overrides) -> dict:
    choice = {"kind": "fix", "findings": findings, "reframe": "r", "choice": "c",
              "completeness": "searched callers of x",
              "candidates": [_candidate("A", chosen=True), _candidate("B")],
              "cases": [{"case": "k", "site": "a.py:1", "test": "tests/test_a.py::test_k",
                         "today": "t", "under_fix": "u", "result": "fixed"}],
              "couplings": [],
              "premise": {"assumption": "a.py:1 is the only writer", "probe": "rg -n 'write(' a.py"}}
    choice.update(overrides)
    return choice


def _decision(findings: list[str], **overrides) -> dict:
    data = {"schema": 2, "agent": "remediating-issues", "role": "decision", "task": 1,
            "status": "decided", "cycle": 2, "reviewer_records": ["task-1-spec-reviewer"],
            "choices": [_fix_choice(findings)], "excluded": [], "reconciled": []}
    data.update(overrides)
    return data


class TestDecisionShape(unittest.TestCase):
    """validate_record on a decision's own shape (no store or repo needed)."""

    def assertRejects(self, data: dict, fragment: str):
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(data)
        self.assertIn(fragment, str(ctx.exception))

    def test_a_complete_decision_is_valid(self):
        ledger.validate_record(_decision(["x#issues[1]"]))

    def test_one_candidate_is_not_a_defense(self):
        self.assertRejects(_decision(["x"], choices=[_fix_choice(
            ["x"], candidates=[_candidate("A", chosen=True)])]), "expected at least 2")

    def test_exactly_one_candidate_is_chosen(self):
        for flags in ((False, False), (True, True)):
            candidates = [_candidate("A", chosen=flags[0]), _candidate("B", chosen=flags[1])]
            self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"], candidates=candidates)]),
                               "expected exactly one")

    def test_a_precedent_needs_a_line(self):
        self.assertRejects(_decision(["x"], choices=[_fix_choice(
            ["x"], candidates=[_candidate("A", chosen=True, precedent="a.py"), _candidate("B")])]),
            "precedent")

    def test_a_fix_needs_completeness_and_cases(self):
        self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"], completeness=" ")]),
                           "completeness")
        self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"], cases=[])]),
                           "cases: got 0 entries")

    def test_a_decision_may_only_exclude(self):
        # A round started for a lone root cause the engine defers.
        ledger.validate_record(_decision([], choices=[], excluded=[{"finding": "c", "reason": "later"}]))
        self.assertRejects(_decision([], choices=[]), "choices: got 0 entries")

    def test_a_finding_is_accounted_for_once(self):
        self.assertRejects(_decision(["x"], excluded=[{"finding": "x", "reason": "trivial"}]),
                           "accounted for twice")

    def test_status_follows_escalation(self):
        escalate = {"kind": "escalate", "findings": ["y"], "why": "no fixture", "evidence": "e"}
        self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"]), escalate]),
                           "expected 'escalated'")
        ledger.validate_record(_decision(["x"], status="escalated",
                                         choices=[_fix_choice(["x"]), escalate]))
        self.assertRejects(_decision(["x"], status="escalated"), "expected 'decided'")

    def test_cycle_is_required(self):
        data = _decision(["x"])
        del data["cycle"]
        self.assertRejects(data, "cycle")

    def test_a_non_string_kind_is_a_record_error(self):
        self.assertRejects(_decision(["x"], choices=[_fix_choice(["x"], kind=["fix"])]), "kind")

    def test_task_is_a_positive_integer_or_final(self):
        for task in ("1", 0, True, "Final"):
            with self.subTest(task=task):
                self.assertRejects(_spec_reviewer(task=task), "task")
        ledger.validate_record(_spec_reviewer(task="final"))

    def test_a_decision_before_any_review_lists_no_reviewers(self):
        ledger.validate_record(_decision(["x"], reviewer_records=[]))
        self.assertRejects(_decision(["x"], reviewer_records=[""]), "reviewer_records")

    def test_reviewer_finding_lists_hold_objects(self):
        self.assertRejects(_spec_reviewer(issues="none"), "issues")
        self.assertRejects(_review_lite(findings=["x"]), "findings[0]")


class DecisionStoreTestCase(GitRepoTestCase):
    """A store inside the repo with one spec and one quality reviewer record
    for task 1; a.py (one line) is the only precedent target."""

    def setUp(self):
        super().setUp()
        self.store = ledger.ensure_store(self.repo / ".sdd")
        spec = _spec_reviewer(status="issues", issues=[_SPEC_ISSUE],
                              cannot_verify=[{"requirement": "r", "why": "w", "should_check": "s"}])
        quality = {**_spec_reviewer(agent="python-quality-reviewer", role="quality-reviewer",
                                    status="approved"), "findings": [_QUALITY_FINDING, _NOTE]}
        del quality["issues"], quality["cannot_verify"]
        _write(self.store, "task-1-spec-reviewer.json", spec)
        _write(self.store, "task-1-python-quality-reviewer.json", quality)
        self.spec_id = _entry_id("task-1-spec-reviewer", "issues", _SPEC_ISSUE)
        self.quality_id = _entry_id("task-1-python-quality-reviewer", "findings", _QUALITY_FINDING)
        self.note_id = _entry_id("task-1-python-quality-reviewer", "findings", _NOTE)

    def _complete(self, **overrides) -> dict:
        data = _decision([self.spec_id, self.quality_id],
                         reviewer_records=["task-1-spec-reviewer", "task-1-python-quality-reviewer"],
                         excluded=[{"finding": self.note_id, "reason": "severity-1 note"}])
        data.update(overrides)
        return data

    def _check(self, data: dict, name: str = "task-1-decision-c2.json") -> None:
        ledger.check_record(_write(self.store, name, data))

    def assertCheckFails(self, data: dict, fragment: str, name: str = "task-1-decision-c2.json"):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(data, name)
        self.assertIn(fragment, str(ctx.exception))


class TestDecisionContext(DecisionStoreTestCase):

    def test_a_decision_accounting_for_every_finding_passes(self):
        self._check(self._complete())

    def test_an_unaccounted_finding_is_named(self):
        self.assertCheckFails(self._complete(excluded=[]), self.note_id)

    def test_an_unknown_or_stale_id_is_refused(self):
        self.assertCheckFails(
            self._complete(excluded=[{"finding": "task-1-spec-reviewer#issues[00000000]",
                                      "reason": "x"}]), "no such finding")

    def test_cannot_verify_may_be_decided_but_is_not_required(self):
        cv = _entry_id("task-1-spec-reviewer", "cannot_verify",
                       {"requirement": "r", "why": "w", "should_check": "s"})
        self._check(self._complete(choices=[_fix_choice([self.spec_id, self.quality_id, cv])]))

    def test_a_coder_concern_may_be_decided_but_is_not_required(self):
        concern = "root cause: src/band.py:40 the band estimate copies the label cascade"
        _write(self.store, "task-1-python-coder.json", _coder(concerns=[concern, 7]))
        concern_id = _entry_id("task-1-python-coder", "concerns", concern)
        self._check(self._complete())
        self._check(self._complete(choices=[_fix_choice([self.spec_id, self.quality_id]),
                                            _fix_choice([concern_id])]))

    def test_another_tasks_coder_concern_is_unknown(self):
        concern = "root cause: src/x.py:1 x"
        _write(self.store, "task-2-python-coder.json", _coder(task=2, concerns=[concern]))
        concern_id = _entry_id("task-2-python-coder", "concerns", concern)
        self.assertCheckFails(self._complete(choices=[
            _fix_choice([self.spec_id, self.quality_id, concern_id])]), "no such finding")

    def test_every_reviewer_record_for_the_task_is_listed(self):
        self.assertCheckFails(self._complete(reviewer_records=["task-1-spec-reviewer"]),
                              "task-1-python-quality-reviewer")

    def test_another_tasks_reviewers_are_not_required(self):
        _write(self.store, "task-2-spec-reviewer.json",
               _spec_reviewer(task=2, status="issues", issues=[_SPEC_ISSUE]))
        self._check(self._complete())

    def test_a_listed_record_must_be_a_reviewer_for_the_task(self):
        self.assertCheckFails(self._complete(reviewer_records=[
            "task-1-spec-reviewer", "task-1-python-quality-reviewer", "task-1-python-coder"]),
            "not among")

    def _age(self, name: str, seconds: int) -> None:
        path = self.store / name
        stamp = path.stat().st_mtime_ns - seconds * 10**9
        os.utime(path, ns=(stamp, stamp))

    def test_every_decision_written_earlier_is_reconciled(self):
        self._check(self._complete(), name="task-1-decision-c2.json")
        self._age("task-1-decision-c2.json", 60)
        self.assertCheckFails(self._complete(cycle=3), "task-1-decision-c2",
                              name="task-1-decision-c3.json")
        self._check(self._complete(cycle=3, reconciled=[
            {"decision": "task-1-decision-c2", "relation": "c2's mechanism failed because"}]),
            name="task-1-decision-c3.json")

    def test_an_earlier_decision_stays_valid_when_a_later_one_lands(self):
        c2 = _write(self.store, "task-1-decision-c2.json", self._complete())
        self._age("task-1-decision-c2.json", 60)
        self._check(self._complete(cycle=3, reconciled=[
            {"decision": "task-1-decision-c2", "relation": "r"}]), name="task-1-decision-c3.json")
        ledger.check_record(c2)

    def test_reconciled_may_not_name_a_missing_decision(self):
        self.assertCheckFails(self._complete(reconciled=[
            {"decision": "task-9-decision-c2", "relation": "r"}]), "not among the other")

    def test_a_decision_naming_itself_is_harmless(self):
        self._check(self._complete(reconciled=[{"decision": "task-1-decision-c2", "relation": "r"}]))

    def test_a_markdown_decision_from_before_an_upgrade_can_be_reconciled(self):
        (self.store / "task-1-decision-c2.md").write_text("# old decision\n")
        self._check(self._complete(cycle=3, reconciled=[
            {"decision": "task-1-decision-c2", "relation": "c2 chose X"}]),
            name="task-1-decision-c3.json")

    def test_a_malformed_record_for_the_task_blocks_the_decision(self):
        (self.store / "task-1-rust-quality-reviewer.json").write_text("{not json")
        self.assertCheckFails(self._complete(), "task-1-rust-quality-reviewer")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_findings(self.store / "task-1-decision-c2.json")
        self.assertIn("PROBLEM", out.getvalue())

    def test_a_misfiled_reviewer_record_blocks_the_decision(self):
        # Review-lite gets no brief; a wrong `task` would hide its findings.
        _write(self.store, "task-1-python-review-lite.json",
               _review_lite(task=5, status="block", findings=[_QUALITY_FINDING]))
        self.assertCheckFails(self._complete(), "says task 5")

    def test_scope_comes_from_the_file_name(self):
        _write(self.store, "task-1-python-review-lite.json",
               _review_lite(status="block", findings=[_NOTE]))
        lite_id = _entry_id("task-1-python-review-lite", "findings", _NOTE)
        self.assertCheckFails(self._complete(), "task-1-python-review-lite")
        self._check(self._complete(reviewer_records=[
            "task-1-spec-reviewer", "task-1-python-quality-reviewer", "task-1-python-review-lite"],
            excluded=[{"finding": self.note_id, "reason": "note"},
                      {"finding": lite_id, "reason": "trivial"}]))

    def test_another_tasks_malformed_record_does_not_block(self):
        (self.store / "task-12-rust-quality-reviewer.json").write_text("{not json")
        self._check(self._complete())

    def test_the_name_carries_task_and_cycle(self):
        for name in ("task-1-decision-c3.json", "task-2-decision-c2.json",
                     "task-1-decision.json", "task-1-decision-c2.txt", "decision.json"):
            with self.subTest(name=name):
                self.assertCheckFails(self._complete(), "-decision-c2.json, scope task-1",
                                      name=name)

    def test_a_final_decision_is_named_for_final(self):
        lite = _review_lite(task="final", status="block", findings=[_QUALITY_FINDING])
        _write(self.store, "final-python-review-lite.json", lite)
        lite_id = _entry_id("final-python-review-lite", "findings", _QUALITY_FINDING)
        data = _decision([lite_id], task="final", reviewer_records=["final-python-review-lite"])
        self._check(data, name="final-decision-c2.json")

    def test_a_round_two_final_decision_covers_only_round_two(self):
        _write(self.store, "final-python-review-lite.json",
               _review_lite(task="final", status="block", findings=[_QUALITY_FINDING]))
        _write(self.store, "final-r2-python-review-lite.json",
               _review_lite(task="final", status="block", findings=[_NOTE]))
        r2_id = _entry_id("final-r2-python-review-lite", "findings", _NOTE)
        data = _decision([r2_id], task="final", reviewer_records=["final-r2-python-review-lite"])
        self._check(data, name="final-r2-decision-c2.json")
        self.assertCheckFails(data, "final-python-review-lite", name="final-decision-c2.json")

    def test_a_precedent_cannot_cite_the_store(self):
        _write(self.store, "notes.json", {"x": 1})
        choice = _fix_choice([self.spec_id, self.quality_id], candidates=[
            _candidate("A", chosen=True, precedent=".sdd/notes.json:1"), _candidate("B")])
        self.assertCheckFails(self._complete(choices=[choice]), "is in the store")

    def test_a_precedent_must_name_a_file_in_the_repo(self):
        choice = _fix_choice([self.spec_id, self.quality_id], candidates=[
            _candidate("A", chosen=True, precedent="missing.py:1"), _candidate("B")])
        self.assertCheckFails(self._complete(choices=[choice]), "'missing.py' is not a file")

    def test_a_precedent_cannot_leave_the_repo(self):
        # A real file, so only the containment check can refuse it.
        with tempfile.TemporaryDirectory() as elsewhere:
            outside = Path(elsewhere) / "outside.py"
            outside.write_text("y = 1\n", encoding="utf-8")
            rel = os.path.relpath(outside.resolve(), self.repo.resolve())
            choice = _fix_choice([self.spec_id, self.quality_id], candidates=[
                _candidate("A", chosen=True, precedent=f"{rel}:1"), _candidate("B")])
            self.assertCheckFails(self._complete(choices=[choice]), "is not a file in the repo")

    def test_a_precedent_line_must_exist(self):
        for precedent in ("a.py:2", "a.py:1-2", "a.py:0"):
            choice = _fix_choice([self.spec_id, self.quality_id], candidates=[
                _candidate("A", chosen=True, precedent=precedent), _candidate("B")])
            self.assertCheckFails(self._complete(choices=[choice]), "outside a.py (1 lines)")

    def test_a_relocated_store_resolves_precedents_in_the_working_repo(self):
        with tempfile.TemporaryDirectory() as loose:
            store = ledger.ensure_store(Path(loose))
            _write(store, "task-1-spec-reviewer.json",
                   _spec_reviewer(status="issues", issues=[_SPEC_ISSUE]))
            path = _write(store, "task-1-decision-c2.json", _decision([self.spec_id]))
            with mock.patch.object(Path, "cwd", return_value=self.repo):
                ledger.check_record(path)
            with mock.patch.object(Path, "cwd", return_value=Path(loose)):
                with self.assertRaises(ledger.RecordError) as ctx:
                    ledger.check_record(path)
            self.assertIn("neither the store nor the working directory", str(ctx.exception))

    def test_cmd_check_runs_the_context_check_and_logs_history(self):
        path = _write(self.store, "task-1-decision-c2.json", self._complete(excluded=[]))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(path))
        _write(self.store, "task-1-decision-c2.json", self._complete())
        ledger.cmd_check(str(path))
        history = (self.store / ledger.HISTORY_FILENAME).read_text().splitlines()
        self.assertEqual(json.loads(history[-1])["role"], "decision")

    def test_findings_lists_exactly_the_ids_check_requires(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_findings(self.store / "task-1-decision-c2.json")
        listed = re.findall(r"\[(task-1-[^\]]+\])\]", out.getvalue())
        required, optional = out.getvalue().split("cannot_verify (optional):")
        self.assertEqual(set(re.findall(r"\[(task-1-[^\]]+\])\]", required)),
                         {self.spec_id, self.quality_id, self.note_id})
        self.assertEqual(len(re.findall(r"\[(task-1-[^\]]+\])\]", optional)), 1)
        self.assertEqual(len(listed), 4)
        self.assertIn("decisions to reconcile: (none)", out.getvalue())

    def test_findings_lists_coder_concerns_as_optional(self):
        _write(self.store, "task-1-python-coder.json", _coder(concerns=["root cause: src/x.py:1 x"]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_findings(self.store / "task-1-decision-c2.json")
        concerns = out.getvalue().split("coder concerns")[1]
        self.assertIn(f"[{_entry_id('task-1-python-coder', 'concerns', 'root cause: src/x.py:1 x')}]", concerns)

    def test_findings_leaves_out_the_decision_being_written(self):
        _write(self.store, "task-1-decision-c2.json", self._complete())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_findings(self.store / "task-1-decision-c2.json")
            ledger.cmd_findings(self.store / "task-1-decision-c3.json")
        first, second = out.getvalue().split("reviewer records:")[1:]
        self.assertIn("decisions to reconcile: (none)", first)
        self.assertIn("decisions to reconcile: task-1-decision-c2", second)

    def test_findings_needs_a_decision_name(self):
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_findings(self.store / "task-1-decision.json")


class TestEscalations(DecisionStoreTestCase):
    """A close-gate escalation waits on the user: `open` lists it until the
    ruling resolves it, and `final` can't complete before then. A per-task
    decision's escalation is contested instead (TestUserDecisionsRouteBack)."""

    def setUp(self):
        super().setUp()
        _write(self.store, "final-python-review-lite.json",
               _review_lite(task="final", status="block", findings=[_QUALITY_FINDING]))
        self.lite_id = _entry_id("final-python-review-lite", "findings", _QUALITY_FINDING)

    def _escalating(self) -> dict:
        escalate = {"kind": "escalate", "findings": [self.lite_id], "why": "no fixture",
                    "evidence": "e"}
        return _decision([], task="final", status="escalated",
                         reviewer_records=["final-python-review-lite"], choices=[escalate])

    def _check(self, data: dict, name: str = "final-decision-c2.json") -> None:
        super()._check(data, name)

    def _open_escalations(self) -> list:
        items = ledger.compute_open_items(
            ledger.load_records(self.store),
            set(ledger.resolutions_from_log(ledger.load_progress_log(self.store))))
        return [i for i in items if i.kind == ledger.ESCALATION_KIND]

    def test_open_lists_an_escalation_until_the_ruling_resolves_it(self):
        self._check(self._escalating())
        (item,) = self._open_escalations()
        self.assertIn(self.lite_id, item.summary)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, item.id, "waived")
        self.assertIn("user ruling:", str(ctx.exception))
        ledger.cmd_resolve(self.store, item.id, "user ruling: waive it")
        self.assertEqual(self._open_escalations(), [])

    def test_completion_waits_on_the_escalations_resolution(self):
        self._check(self._escalating())
        (item,) = self._open_escalations()
        _completable(self.store, "final")
        # A ruling logged as a progress note leaves the escalation open.
        ledger.cmd_append(self.store, "progress", "final", "user ruling: fix it with a fixture")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_append(self.store, "complete", "final", "shipped")
        self.assertIn(item.id, str(ctx.exception))
        self.assertIn("resolve", str(ctx.exception))
        ledger.cmd_resolve(self.store, item.id, "user ruling: fix it with a fixture")
        ledger.cmd_append(self.store, "complete", "final", "shipped")
        self.assertEqual(ledger.completed_task_ids(ledger.load_progress_log(self.store)), ["final"])

    def test_another_tasks_escalation_does_not_block_completion(self):
        self._check(self._escalating())
        _completable(self.store, 2)
        ledger.cmd_append(self.store, "complete", 2, "shipped")
        self.assertEqual(ledger.completed_task_ids(ledger.load_progress_log(self.store)), ["2"])

    def test_final_completion_waits_on_a_close_gate_escalation(self):
        escalate = {"kind": "escalate", "findings": ["x"], "why": "w", "evidence": "e"}
        _write(self.store, "final-r2-decision-c1.json",
               _decision(["x"], task="final", cycle=1, status="escalated", choices=[escalate]))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_append(self.store, "complete", "final", "shipped")


# --- process labels (review-process narrative in code) ---

def _diff(path: str, *added: str, start: int = 1, context: tuple[str, ...] = ()) -> str:
    body = [f" {line}" for line in context] + [f"+{line}" for line in added]
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{start},{len(context)} +{start},{len(body)} @@\n" + "\n".join(body) + "\n")


class TestProcessLabels(unittest.TestCase):
    """Coders copy the run's vocabulary (task and finding ids, cycle
    numbers, decision docs, commit hashes) into comments. A self-check grep
    written by the label's author shares the author's blind spot, so the
    check is a script."""

    def _labels(self, diff: str) -> list[str]:
        return [hit.label for hit in ledger.find_process_labels(diff)]

    def test_observed_label_shapes_are_caught(self):
        # Shapes from a real run's comments.
        diff = _diff("src/m.py",
                     "# T1's refusal text, per the decision doc",
                     "# keeps the rule (A1) from #157 F1",
                     "# fixed in this task's cycle 2 at 510819e5",
                     "# see .sdd/w8/task-5-report.md",
                     "# the orchestrator reruns this after Task 3")
        labels = set(self._labels(diff))
        self.assertTrue({"task-id", "decision-doc", "finding-id", "cycle", "commit-hash",
                         "sdd-path", "orchestrator", "task-number"} <= labels, labels)

    def test_hits_carry_the_new_file_line_number(self):
        diff = _diff("src/m.py", "x = 1", "# cycle 2 fix", start=10, context=("a = 0", "b = 0"))
        [hit] = ledger.find_process_labels(diff)
        self.assertEqual((hit.path, hit.line, hit.label), ("src/m.py", 13, "cycle"))
        self.assertIn("cycle 2 fix", hit.text)

    def test_removed_and_context_lines_are_ignored(self):
        diff = ("diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,1 @@\n"
                "-# cycle 2 leftover being deleted\n # Task 3 context, not this change\n")
        self.assertEqual(ledger.find_process_labels(diff), [])

    def test_code_lookalikes_outside_comments_are_not_hits(self):
        # Short ids and hex runs are ordinary in code; they count only in comments.
        diff = _diff("src/m.rs", "fn f<T1, T2>(a: T1) -> T2 { g(A1) }",
                     'let rgba = "1f77b4ff"; let h = 0x1a2b3c4d;',
                     "# not a hash: #1f77b4ff colour")
        self.assertEqual(self._labels(diff), [])

    def test_trailing_comment_and_docstring_body_are_comments(self):
        diff = _diff("src/m.py", "x = 1  # carried from (F2)", "def f():",
                     '    """Summary line.', "", "    Matches 510819e5 behavior.", '    """')
        self.assertEqual(sorted(self._labels(diff)), ["commit-hash", "finding-id"])

    def test_prose_files_are_skipped(self):
        # Docs and changelogs may legitimately discuss the process.
        diff = _diff("CHANGELOG.md", "- The orchestrator now reruns cycle 2.")
        self.assertEqual(ledger.find_process_labels(diff), [])

    def test_process_words_in_code_are_not_hits(self):
        # cycle, task and orchestrator are ordinary domain words in code.
        diff = _diff("src/m.py", 'cycle_colors("cycle 2")', 'Task("task-1")',
                     "orchestrator = Orchestrator()")
        self.assertEqual(self._labels(diff), [])

    def test_quoted_and_tab_terminated_paths_are_scanned(self):
        # core.quotePath C-quotes non-ASCII names; a name with a space gets a tab.
        quoted = ('diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"\n'
                  '--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n'
                  "@@ -0,0 +1 @@\n+# cycle 2 fix\n")
        spaced = ("diff --git a/sp ace.py b/sp ace.py\n--- a/sp ace.py\t\n+++ b/sp ace.py\t\n"
                  "@@ -0,0 +1 @@\n+# cycle 2 fix\n")
        self.assertEqual([h.path for h in ledger.find_process_labels(quoted + spaced)],
                         ["café.py", "sp ace.py"])

    def test_an_added_line_starting_with_plus_plus_is_not_a_header(self):
        diff = ("diff --git a/m.c b/m.c\n--- a/m.c\n+++ b/m.c\n@@ -1,0 +1,2 @@\n"
                "+++ i;\n+// cycle 2 thing\n")
        self.assertEqual([(h.path, h.line) for h in ledger.find_process_labels(diff)],
                         [("m.c", 2)])

    def test_a_hunk_opening_inside_a_docstring_does_not_flip_code_to_comment(self):
        # The closing quotes arrive as context; the added code after them is code.
        diff = _diff("src/m.py", 'x = "abc1234f"', "foo(T1)", start=5,
                     context=("    body of an existing docstring", '    """'))
        self.assertEqual(self._labels(diff), [])

    def test_a_lone_closing_quote_does_not_open_a_docstring(self):
        # The docstring opened on an unseen line; its lone closing quotes are added.
        diff = _diff("src/m.py", '    """', 'name = "worker-task-1"', 'h = "cafe1234"',
                     start=8, context=("    more docstring text",))
        self.assertEqual(self._labels(diff), [])

    def test_a_lone_opening_quote_after_a_signature_opens_a_docstring(self):
        diff = _diff("src/m.py", "def f():", '    """', "    Matches 510819e5.", '    """')
        self.assertEqual(self._labels(diff), ["commit-hash"])

    def test_a_line_added_inside_a_docstring_opened_in_context_is_a_comment(self):
        # Extending an existing docstring is a common way a label leaks in a fix.
        diff = _diff("src/m.py", "    Handles negatives per cycle 2 review.", start=3,
                     context=("def f(x):", '    """Return x.', ""))
        self.assertEqual(self._labels(diff), ["cycle"])

    def test_text_then_closing_quotes_does_not_open_a_docstring(self):
        # Closes a docstring the hunk never showed opening; the code after is code,
        # and a real docstring later in the hunk is still scanned.
        diff = _diff("src/m.py", '    new text."""', "    self.orchestrator = Orchestrator(cycle-2)",
                     "def g():", '    """', "    Retries the task 3 path.", '    """',
                     start=9, context=("    existing docstring body",))
        self.assertEqual(self._labels(diff), ["task-number"])

    def test_a_module_docstring_after_leading_comments_is_scanned(self):
        for header in (("#!/usr/bin/env python3",), ("# Copyright 2026", "# License: MIT", "")):
            diff = _diff("src/m.py", *header, '"""Tool.', "", "Added in task 3.", '"""')
            self.assertEqual(self._labels(diff), ["task-number"], header)

    def test_a_comment_between_signature_and_docstring_still_opens_it(self):
        diff = _diff("src/m.py", "def f():", "    # noqa", '    """', "    Per task 3.", '    """')
        self.assertEqual(self._labels(diff), ["task-number"])

    def test_a_multiline_string_assigned_after_a_signature_is_code(self):
        diff = _diff("src/m.py", "def query():", '    sql = """', "    SELECT * FROM jobs WHERE name = 'task 3'",
                     '    """')
        self.assertEqual(self._labels(diff), [])

    def test_prefixed_docstrings_open(self):
        in_function = _diff("src/m.py", "def f(x):", '    r"""Compute $\\sigma$.', "",
                            "    Added in cycle 2.", '    """')
        at_top = _diff("src/m.py", 'R"""Tool.', "", "Added in cycle 2.", '"""')
        for diff in (in_function, at_top):
            self.assertEqual(self._labels(diff), ["cycle"])

    def test_code_after_a_closed_docstring_is_code(self):
        diff = _diff("src/m.py", "def f():", '    """Build the runner.', "", "    Body.", '    """',
                     "    orchestrator = Orchestrator()")
        self.assertEqual(self._labels(diff), [])

    def test_a_signature_with_a_trailing_comment_can_open_a_docstring(self):
        diff = _diff("src/m.py", "def f():  # noqa", '    """', "    Retries the task 3 path.", '    """')
        self.assertEqual(self._labels(diff), ["task-number"])

    def test_a_dereference_is_code_not_a_comment(self):
        diff = _diff("src/m.rs", "*slot = Some(T1);", '*x = "cycle 2";', " * cycle 2 in a block")
        self.assertEqual(self._labels(diff), ["cycle"])

    def test_a_trailing_comment_without_a_space_is_scanned(self):
        self.assertEqual(self._labels(_diff("src/m.py", "x = 1  #cycle 2")), ["cycle"])

    def test_form_feed_and_line_separators_do_not_end_the_hunk_early(self):
        # str.splitlines() splits on these too, which would shift the hunk counts.
        for odd in ("\f", "x = ' '", "\r"):
            diff = _diff("src/m.py", odd, "a = 1", "# see task 3")
            self.assertEqual(self._labels(diff), ["task-number"], repr(odd))

    def test_a_non_utf8_quoted_path_does_not_crash(self):
        diff = ('diff --git "a/bad\\377.py" "b/bad\\377.py"\n--- "a/bad\\377.py"\n'
                '+++ "b/bad\\377.py"\n@@ -0,0 +1 @@\n+# cycle 2\n')
        [hit] = ledger.find_process_labels(diff)
        self.assertTrue(hit.path.startswith("bad"))

    def test_cmakelists_is_code_not_prose(self):
        self.assertEqual(self._labels(_diff("CMakeLists.txt", "# cycle 2 note")), ["cycle"])

    def test_prose_suffixes_match_case_insensitively(self):
        for name in ("R.MD", "notes.markdown", "page.mdx"):
            self.assertEqual(ledger.find_process_labels(_diff(name, "# cycle 2")), [], name)

    def test_ordinary_comments_pass(self):
        diff = _diff("src/m.py", "# Clamp padding to [0, 1] so band math stays finite.",
                     "# Warn at the user's call site, not inside the wrapper.")
        self.assertEqual(ledger.find_process_labels(diff), [])


class TestLabelsCLI(GitRepoTestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, str(LEDGER_PY), *args], cwd=self.repo,
                              capture_output=True, text=True)

    def test_labels_since_head_reports_hits_and_exits_1(self):
        (self.repo / "a.py").write_text("x = 1  # per the decision doc\n", encoding="utf-8")
        result = self._run("labels", "HEAD")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("a.py:1", result.stdout)
        self.assertIn("decision-doc", result.stdout)

    def test_labels_is_silent_and_exits_0_when_clean(self):
        (self.repo / "a.py").write_text("x = 1  # clamp to the axis range\n", encoding="utf-8")
        result = self._run("labels", "HEAD", "a.py")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_labels_ignores_the_users_quotepath_setting(self):
        # Unquoted output would hand the parser a raw name it can't decode.
        self._git("config", "core.quotePath", "false")
        (self.repo / 'café"q.py').write_text("x = 1  # cycle 2\n", encoding="utf-8")
        result = self._run("labels", "HEAD")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('café"q.py:1: cycle', result.stdout)

    def test_labels_errors_exit_2_not_the_hits_code(self):
        # Exit 1 means "labels found"; a bad tree must not look like that.
        result = self._run("labels", "nosuchtree")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_labels_rejects_an_option_shaped_tree_before_touching_paths(self):
        result = self._run("labels", "--", "--output=/dev/null", "a.py")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("must not start with '-'", result.stderr)

    def test_labels_refuses_a_path_that_matches_nothing(self):
        # A typo in the file list must not turn the gate into a pass.
        (self.repo / "a.py").write_text("x = 1  # cycle 2\n", encoding="utf-8")
        result = self._run("labels", "HEAD", "a.pyy")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("a.pyy", result.stderr)

    def test_labels_since_a_baseline_sees_only_the_fix(self):
        (self.repo / "a.py").write_text("x = 2  # cycle 1 note\n", encoding="utf-8")
        baseline = ledger.snapshot_tree(self.repo)
        (self.repo / "b.py").write_text("y = 1\n", encoding="utf-8")
        result = self._run("labels", baseline)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)


# --- per-cycle history and stats ---

class TestHistory(LedgerTestCase):
    """Records are overwritten each cycle, so `check` (which every agent
    runs after writing) appends a summary line per passing record. That
    history is what `stats` reads."""

    def setUp(self):
        super().setUp()
        ledger.ensure_store(self.store)

    def test_a_record_outside_a_store_writes_no_history(self):
        with tempfile.TemporaryDirectory() as loose:
            path = _write(Path(loose), "task-1-python-coder.json", _coder())
            ledger.cmd_check(str(path))
            self.assertFalse((Path(loose) / ledger.HISTORY_FILENAME).exists())

    def test_a_directory_with_some_other_gitignore_is_not_a_store(self):
        with tempfile.TemporaryDirectory() as repo_root:
            (Path(repo_root) / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
            ledger.cmd_check(str(_write(Path(repo_root), "task-1-python-coder.json", _coder())))
            self.assertFalse((Path(repo_root) / ledger.HISTORY_FILENAME).exists())

    def test_a_malformed_history_line_raises_naming_file_and_line(self):
        (self.store / ledger.HISTORY_FILENAME).write_text('{"record": "x"}\nnot json\n')
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.load_history(self.store)
        self.assertIn(f"{ledger.HISTORY_FILENAME}:2", str(ctx.exception))

    def _history(self) -> list[dict]:
        path = self.store / ledger.HISTORY_FILENAME
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_check_appends_a_summary_per_passing_record(self):
        path = _write(self.store, "task-2-spec-reviewer.json", _spec_reviewer(
            task=2, status="issues", cycle=2,
            issues=[_finding(kind="missing")],
            introduced_by_fix=[{"site": "a.py:1", "why": "x"}]))
        ledger.cmd_check(str(path))
        self.assertEqual(self._history(), [{
            "record": "task-2-spec-reviewer", "task": 2, "role": "spec-reviewer",
            "cycle": 2, "status": "issues", "findings": 1, "recurring": 0,
            "introduced_by_fix": 1}])

    def test_failed_check_appends_nothing(self):
        path = _write(self.store, "task-1-python-coder.json", _coder(status="Blocked"))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(path))
        self.assertFalse((self.store / ledger.HISTORY_FILENAME).exists())

    def test_clear_removes_the_history(self):
        ledger.cmd_check(str(_write(self.store, "task-1-python-coder.json", _coder())))
        ledger.cmd_clear(self.store)
        self.assertFalse((self.store / ledger.HISTORY_FILENAME).exists())

    def test_stats_keeps_the_last_check_per_record_and_cycle(self):
        name = "task-5-spec-reviewer.json"
        issue = _finding(kind="missing")
        for cycle, status, issues in ((1, "issues", [issue, issue]), (2, "issues", [issue]),
                                      (2, "compliant", [])):
            ledger.cmd_check(str(_write(self.store, name, _spec_reviewer(
                task=5, cycle=cycle, status=status, issues=issues))))
        ledger.cmd_check(str(_write(self.store, "task-5-python-coder.json",
                                    _coder(task=5, cycle=1))))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_stats(self.store)
        text = out.getvalue()
        self.assertIn("task 5", text)
        self.assertRegex(text, r"spec-reviewer\s+c1\s+issues\s+findings=2")
        self.assertRegex(text, r"spec-reviewer\s+c2\s+compliant\s+findings=0")
        self.assertNotRegex(text, r"c2\s+issues")  # superseded by the later check

    def test_stats_lists_fix_regressions_and_recurrence(self):
        ledger.cmd_check(str(_write(self.store, "task-2-spec-reviewer.json", _spec_reviewer(
            task=2, cycle=2, status="issues",
            issues=[_finding(kind="regression")],
            recurring=[{"site": "a.py:1", "why": "x"}],
            introduced_by_fix=[{"site": "a.py:1", "why": "x"}]))))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_stats(self.store)
        self.assertRegex(out.getvalue(), r"introduced_by_fix: task-2-spec-reviewer c2 \(1\)")
        self.assertRegex(out.getvalue(), r"recurring: task-2-spec-reviewer c2 \(1\)")

    def test_an_undecodable_history_file_raises_record_error(self):
        (self.store / ledger.HISTORY_FILENAME).write_bytes(b"\xff\xfe not utf-8\n")
        with self.assertRaises(ledger.RecordError):
            ledger.load_history(self.store)

    def test_a_history_line_that_is_not_an_object_raises_record_error(self):
        (self.store / ledger.HISTORY_FILENAME).write_text("3\n", encoding="utf-8")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.load_history(self.store)
        self.assertIn(f"{ledger.HISTORY_FILENAME}:1", str(ctx.exception))

    def test_a_non_integer_cycle_is_logged_as_unknown(self):
        # Reviewer cycle isn't validated by check; stats must still sort.
        for name, cycle in (("task-1-spec-reviewer.json", "2"),
                            ("task-1-python-quality-reviewer.json", [2])):
            ledger.cmd_check(str(_write(self.store, name, _spec_reviewer(cycle=cycle))))
        ledger.cmd_check(str(_write(self.store, "task-1-python-coder.json", _coder())))
        self.assertEqual({e["record"]: e["cycle"] for e in self._history()},
                         {"task-1-spec-reviewer": None, "task-1-python-quality-reviewer": None,
                          "task-1-python-coder": 1})
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_stats(self.store)  # no TypeError

    def test_stats_on_an_empty_store_says_so(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_stats(self.store)
        self.assertIn("No history", out.getvalue())


# --- fix-loop integrity (2026-10-30) ---

class TriageStoreTestCase(GitRepoTestCase):
    """A store inside a throwaway repo, with task 3's footprint recorded."""

    def setUp(self):
        super().setUp()
        self.store = ledger.ensure_store(self.repo / ".sdd")
        ledger.cmd_stage(self.store, 3, 1, ["a.py"])

    def write(self, name: str, data: dict) -> Path:
        return _write(self.store, name, data)

    def spec(self, *issues: dict, **extra) -> Path:
        status = "issues" if any(i["severity"] >= 3 for i in issues) else "compliant"
        return self.write("task-3-spec-reviewer.json",
                          _spec_reviewer(task=3, status=status, issues=list(issues), **extra))

    def coder(self, **fields) -> Path:
        return self.write("task-3-python-coder.json", _coder(task=3, **fields))

    def fixed(self, **fields) -> Path:
        """The coder's finished fix from the round triage just routed."""
        return self.coder(**{"cycle": 2, "baseline": _baseline(self.store, 3), **_FIX_FIELDS,
                             **fields})

    def triage(self, task: int | str = 3) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_triage(self.store, task)
        return out.getvalue()

    def entries(self) -> list[dict]:
        return [e for e in ledger.load_progress_log(self.store) if e.get("type") == "triage"]

    def spec_id(self, issue: dict) -> str:
        return _entry_id("task-3-spec-reviewer", "issues", issue)


class TestTriageCommand(TriageStoreTestCase):
    def test_a_clean_review_is_done(self):
        self.spec()
        self.assertIn("done", self.triage())
        [entry] = self.entries()
        self.assertEqual((entry["task"], entry["kind"]), (3, "done"))

    def test_one_local_s3_prints_a_patch_with_the_finding_and_its_reviewer(self):
        issue = _finding(sites=["a.py:1"])
        self.spec(issue)
        out = self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "patch")
        for expected in ("patch", self.spec_id(issue), issue["rule"], "task-3-spec-reviewer"):
            self.assertIn(expected, out)

    def test_a_malformed_record_in_scope_is_refused_and_nothing_written(self):
        self.spec()
        (self.store / "task-3-python-quality-reviewer.json").write_text("not json")
        with self.assertRaises(ledger.RecordError) as ctx:
            self.triage()
        self.assertIn("task-3-python-quality-reviewer", str(ctx.exception))
        self.assertEqual(self.entries(), [])

    def test_triage_again_with_nothing_changed_reprints_without_a_new_round(self):
        self.spec(_finding(), _finding(severity=1, rule="a note"))
        first = self.triage()
        again = self.triage()
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(first, again)

    def test_a_task_nobody_reviewed_is_refused(self):
        self.coder()
        with self.assertRaises(ledger.RecordError):
            self.triage()
        self.assertEqual(self.entries(), [])

    def test_an_s2_contract_finding_is_filed_once_as_a_follow_up_with_its_rule(self):
        self.spec(_finding(severity=2, reach="contract", rule="public names are nouns"))
        self.triage()
        self.triage()
        follow_ups = [n for n in ledger.notes_from_log(ledger.load_progress_log(self.store))
                      if n["kind"] == "follow-up"]
        self.assertEqual([n.get("rule") for n in follow_ups], ["public names are nouns"])

    def test_skipped_notes_and_outside_sites_are_filed(self):
        ledger.cmd_stage(self.store, 5, 2, ["lib/x.py"])
        note = _finding(severity=1, rule="name says what it holds")
        self.spec(note)
        self.coder(notes_skipped=[{"finding": self.spec_id(note), "reason": "renaming breaks callers"}],
                   sweeps=[{"findings": [self.spec_id(note)], "rule": "size must be positive",
                            "rows": [{"site": "a.py:1", "hunk": "a.py:1"}],
                            "searched": {"command": "rg size", "result": "2 matches"},
                            "sites_outside": ["lib/x.py:4", "lib/y.py:2"]}])
        self.triage()
        notes = ledger.notes_from_log(ledger.load_progress_log(self.store))
        kinds = sorted((n["kind"], n.get("for")) for n in notes)
        self.assertEqual(kinds, [("follow-up", None), ("follow-up", None), ("task-note", 5)])

    def test_a_held_contest_parks_and_a_ruling_then_rules_the_rest(self):
        issue, other = _finding(sites=["a.py:1"]), _finding(sites=["a.py:1"], rule="other rule")
        self.spec(issue, other)
        self.triage()  # patch
        self.fixed(contested=[{"finding": self.spec_id(issue), "reason": "wrong",
                               "evidence": "a.py:1 already guards size"}])
        self.spec(issue, other, contests=[{"finding": self.spec_id(issue), "verdict": "hold",
                                           "reason": "the guard skips None"}])
        self.triage()  # second patch for `other`; issue held
        self.assertEqual(self.entries()[-1]["held"], [self.spec_id(issue)])
        self.fixed(cycle=3, report="the second fix")  # it lands, and `other` is still raised
        self.triage()  # rounds spent: escalate
        self.assertEqual(self.entries()[-1]["kind"], "escalate")
        ledger.cmd_resolve(self.store, _entry_id("task-3-spec-reviewer", "issues", other),
                           "user ruling: waive, it's out of scope")
        ledger.cmd_append(self.store, "progress", 3, "user ruling: fix the None guard")
        self.triage()
        last = self.entries()[-1]
        self.assertEqual(last["kind"], "ruling")
        self.assertEqual([f["id"] for f in last["findings"]], [self.spec_id(issue)])

    def test_a_conceded_contest_and_a_waiver_are_settled_with_the_tree(self):
        issue, other = _finding(), _finding(rule="other rule")
        self.spec(issue, other)
        self.triage()
        ledger.cmd_resolve(self.store, self.spec_id(other), "user ruling: waive")
        self.fixed(contested=[{"finding": self.spec_id(issue), "reason": "wrong", "evidence": "e"}])
        self.spec(issue, contests=[{"finding": self.spec_id(issue), "verdict": "concede",
                                    "reason": "the guard exists"}])
        self.triage()
        last = self.entries()[-1]
        self.assertEqual(last["kind"], "done")
        self.assertEqual(set(last["settled"]), {self.spec_id(issue), self.spec_id(other)})
        self.assertTrue(last["tree"])


class TestTriageBaseline(TriageStoreTestCase):
    """A fix step takes its own snapshot and prints it; an open fix is
    reprinted, never re-derived."""

    def snapshots(self) -> list[dict]:
        return [e for e in ledger.load_progress_log(self.store) if e.get("type") == "snapshot"]

    def finish(self, baseline: str, **fields) -> None:
        self.coder(cycle=2, baseline=baseline, **_FIX_FIELDS, **fields)

    def test_a_fix_step_snapshots_right_after_its_entry_and_prints_the_dispatch_lines(self):
        for kind, issue in (("patch", _finding()), ("holistic", _finding(reach="contract")),
                            ("polish", _finding(severity=1))):
            with self.subTest(kind=kind):
                self.store = ledger.ensure_store(self.repo / f".sdd-{kind}")
                ledger.cmd_stage(self.store, 3, 1, ["a.py"])
                self.spec(issue)
                out = self.triage()
                log = ledger.load_progress_log(self.store)
                self.assertEqual([e["type"] for e in log[-2:]], ["triage", "snapshot"])
                self.assertEqual(log[-2]["kind"], kind)
                self.assertEqual(log[-1]["label"], f"triage {kind} round {log[-2]['round']}")
                self.assertIn(f"Fix baseline: {log[-1]['tree']}", out)
                self.assertIn("Task files: a.py", out)

    def test_done_and_escalate_take_no_snapshot(self):
        self.spec()
        out = self.triage()
        self.assertEqual(self.snapshots(), [])
        self.assertNotIn("Fix baseline", out)

    def test_an_unchanged_reprint_shows_the_same_baseline(self):
        self.spec(_finding())
        first = self.triage()
        self.assertEqual(self.triage(), first)
        self.assertEqual(len(self.snapshots()), 1)

    def test_an_open_fix_is_reprinted_when_the_coder_pauses(self):
        self.spec(_finding())
        first = self.triage()
        tree = self.snapshots()[0]["tree"]
        self.coder(cycle=1, status="needs_context")
        (self.repo / "a.py").write_text("x = 1\npartial = True\n", encoding="utf-8")
        self.assertEqual(self.triage(), first)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual([s["tree"] for s in self.snapshots()], [tree])

    def test_a_finished_fix_and_a_re_check_start_the_next_step(self):
        issue, other = _finding(), _finding(rule="other rule")
        self.spec(issue, other)
        self.triage()
        tree = self.snapshots()[0]["tree"]
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        self.finish(tree)
        self.spec(other)
        out = self.triage()
        self.assertEqual(len(self.entries()), 2)
        [_, second] = self.snapshots()
        self.assertNotEqual(second["tree"], tree)
        self.assertIn(f"Fix baseline: {second['tree']}", out)

    def test_the_first_fix_at_final_stays_open_until_a_final_coder_carries_it(self):
        self.write("final-python-review-lite.json",
                   _review_lite(task="final", status="block", findings=[_finding()]))
        first = self.triage("final")
        self.write("final-python-review-lite.json",
                   _review_lite(task="final", status="block", findings=[_finding(), _finding(rule="r2")]))
        self.assertEqual(self.triage("final"), first)
        tree = self.snapshots()[0]["tree"]
        self.write("final-python-coder.json", _coder(task="final", cycle=2, baseline=tree, **_FIX_FIELDS))
        self.triage("final")
        self.assertEqual(len([e for e in self.entries() if e["task"] == "final"]), 2)

    def test_baseline_resolves_a_triage_taken_snapshot(self):
        self.spec(_finding())
        self.triage()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_baseline(self.store, self.snapshots()[0]["tree"], 3)
        self.assertIn("round: patch", out.getvalue())


class TestResolveFindings(TriageStoreTestCase):
    def test_an_open_finding_is_waived_only_by_a_user_ruling(self):
        issue = _finding()
        self.spec(issue)
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_resolve(self.store, self.spec_id(issue), "not needed")
        ledger.cmd_resolve(self.store, self.spec_id(issue), "user ruling: waive")
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "done")

    def test_an_open_choice_is_accepted_by_a_user_ruling(self):
        choice = {"question": "size=None?", "choice": "ValueError", "precedent": "a.py:1"}
        self.coder(open=[choice])
        ledger.cmd_resolve(self.store, _entry_id("task-3-python-coder", "open", choice),
                           "user ruling: accept")


class TestContestAnswersAndReopens(TriageStoreTestCase):
    def test_a_recheck_must_answer_every_contest_sent_to_it(self):
        issue = _finding()
        self.spec(issue)
        self.coder(contested=[{"finding": self.spec_id(issue), "reason": "wrong", "evidence": "e"}])
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_check(str(self.spec(issue)))
        self.assertIn(self.spec_id(issue), str(ctx.exception))
        ledger.cmd_check(str(self.spec(issue, contests=[
            {"finding": self.spec_id(issue), "verdict": "hold", "reason": "r"}])))

    def _settle(self, issue: dict) -> None:
        self.spec(issue)
        ledger.cmd_resolve(self.store, self.spec_id(issue), "user ruling: waive")
        self.triage()

    def test_the_same_finding_raised_again_without_reopens_is_refused(self):
        issue = _finding()
        self._settle(issue)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_check(str(self.spec(issue)))
        self.assertIn(self.spec_id(issue), str(ctx.exception))

    def test_a_reopen_needs_a_site_in_code_changed_since_settlement(self):
        issue = _finding()
        self._settle(issue)
        (self.repo / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        ledger.cmd_check(str(self.spec(_finding(sites=["a.py:2"], reopens=self.spec_id(issue)))))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(self.spec(_finding(sites=["a.py:1"], reopens=self.spec_id(issue)))))

    def test_a_reopen_must_name_a_settled_finding(self):
        self.spec()
        self.triage()
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(self.spec(_finding(reopens="task-3-spec-reviewer#issues[00000000]"))))


class TestFixChecks(TriageStoreTestCase):
    """A finished fix starts from a triaged snapshot, covers what it was
    sent, maps its rows to real hunks, writes failing tests first, and
    justifies any edit to a test that already existed."""

    def setUp(self):
        super().setUp()
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_a.py").write_text(
            "def helper():\n    return 1\n\n\ndef test_x():\n    assert x == 2\n", encoding="utf-8")
        self._git("add", "tests/test_a.py")
        self._git("commit", "-qm", "tests")
        ledger.cmd_stage(self.store, 3, 1, ["a.py", "tests/test_a.py"])
        self.issue = _finding(sites=["a.py:1"])

    def review(self, *issues: dict, **extra) -> list[str]:
        issues = issues or (self.issue,)
        self.spec(*issues, **extra)
        self.triage()
        return [self.spec_id(i) for i in issues]

    def snapshot(self) -> str:
        """The baseline triage took for the round `review` routed."""
        return _baseline(self.store, 3)

    def manual_snapshot(self) -> str:
        tree = ledger.snapshot_tree(self.repo)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, 3, "pre-fix c2", tree)
        return tree

    def edit(self, a_py: str = "x = 1\ny = 2\n", test_a: str | None = None) -> None:
        (self.repo / "a.py").write_text(a_py, encoding="utf-8")
        if test_a is not None:
            (self.repo / "tests" / "test_a.py").write_text(test_a, encoding="utf-8")

    def fix(self, tree: str, sent: list[str], **overrides) -> None:
        fields = dict(
            cycle=2, baseline=tree, changed_files=["a.py"],
            diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
            hunk_map=[{"site": "a.py:2", "implements": "the guard"}], consumers_checked=[],
            sweeps=[{"findings": sent, "rule": "size must be positive",
                     "rows": [{"site": "a.py:2", "hunk": "a.py:2"}],
                     "searched": {"command": "rg size", "result": "1 match"}}],
            tests_first=[{"finding": i, "n/a": "existing", "reason": "the round-trip test fails",
                          "test": "tests/test_a.py::test_x"} for i in sent])
        fields.update(overrides)
        ledger.cmd_check(str(self.coder(**fields)))

    def test_a_triaged_fix_that_covers_its_findings_passes(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        self.fix(tree, sent)

    def test_a_fix_with_no_triage_before_its_snapshot_is_refused(self):
        self.spec(self.issue)
        tree = self.manual_snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, [self.spec_id(self.issue)])
        self.assertIn("triage", str(ctx.exception))

    def test_a_sent_finding_left_uncovered_is_refused_naming_it(self):
        other = _finding(sites=["a.py:1"], rule="other rule")
        sent = self.review(self.issue, other)
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent[:1], tests_first=[
                {"finding": i, "n/a": "existing", "reason": "r", "test": "tests/test_a.py::test_x"}
                for i in sent])
        self.assertIn(sent[1], str(ctx.exception))

    def test_a_finding_covered_twice_is_refused(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError):
            self.fix(tree, sent, contested=[{"finding": sent[0], "reason": "wrong", "evidence": "e"}])

    def test_a_row_claiming_a_hunk_the_fix_never_changed_is_refused(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent, sweeps=[{"findings": sent, "rule": "r",
                                          "rows": [{"site": "a.py:1", "hunk": "a.py:1"}],
                                          "searched": {"command": "rg", "result": "1"}}])
        self.assertIn("a.py:1", str(ctx.exception))

    def test_a_recurring_site_must_be_a_row(self):
        issue = _finding(sites=["a.py:1", "a.py:2"])
        sent = self.review(issue, recurring=[{"site": "a.py:1", "why": "same rule as c1"}])
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent)
        self.assertIn("a.py:1", str(ctx.exception))

    def test_a_patch_finding_without_tests_first_is_refused(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent, tests_first=[])
        self.assertIn("tests_first", str(ctx.exception))

    def test_a_written_test_must_be_in_the_fix_diff(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError):
            self.fix(tree, sent, tests_first=[{"finding": sent[0], "test": "tests/test_b.py::test_y",
                                               "command": "pytest", "failed_output": "AssertionError"}])

    def test_an_edited_assertion_in_an_existing_test_needs_a_changed_entry(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit(test_a="def helper():\n    return 1\n\n\ndef test_x():\n    assert x == 3\n")
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])
        self.assertIn("tests/test_a.py", str(ctx.exception))
        self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"], test_changes=[
            {"kind": "changed", "test": "tests/test_a.py::test_x", "old": "assert x == 2",
             "new": "assert x == 3", "reason": "the brief's row sets 3"}])

    def test_a_deleted_or_skipped_test_needs_its_entry(self):
        sent = self.review()
        tree = self.snapshot()
        for test_a, kind in (("def helper():\n    return 1\n", "deleted"),
                             ("def helper():\n    return 1\n\n\n@pytest.mark.skip\n"
                              "def test_x():\n    assert x == 2\n", "skipped")):
            with self.subTest(kind=kind):
                self.edit(test_a=test_a)
                with self.assertRaises(ledger.RecordError):
                    self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])
                self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"], test_changes=[
                    {"kind": kind, "test": "tests/test_a.py::test_x", "old": "test_x", "new": "",
                     "reason": "the behavior it pinned was removed by the ruling"}])

    def test_deleting_a_whole_test_file_needs_a_deleted_entry(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        (self.repo / "tests" / "test_a.py").unlink()
        with self.assertRaises(ledger.RecordError):
            self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])

    def test_a_unittest_skip_needs_a_skipped_entry(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit(test_a="def helper():\n    return 1\n\n\ndef test_x():\n"
                         "    self.skipTest('flaky')\n    assert x == 2\n")
        with self.assertRaises(ledger.RecordError):
            self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])

    def test_a_signature_change_or_a_reindented_assertion_needs_no_entry(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit(test_a="def helper():\n    return 1\n\n\ndef test_x(tmp_path):\n"
                         "    for _ in range(1):\n        assert x == 2\n")
        self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])

    def test_a_finding_raised_to_contract_needs_no_failing_test(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit()
        self.fix(tree, sent, sweeps=[], tests_first=[],
                 reach_raised=[{"finding": sent[0], "evidence": "the fix renames a public API"}])

    def test_a_helper_edit_or_a_new_test_file_needs_no_entry(self):
        sent = self.review()
        tree = self.snapshot()
        self.edit(test_a="def helper():\n    return 2\n\n\ndef test_x():\n    assert x == 2\n")
        (self.repo / "tests" / "test_new.py").write_text(
            "import pytest\n\n\n@pytest.mark.xfail\ndef test_n():\n    assert 0 == 0\n")
        self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py", "tests/test_new.py"])

    def test_deleting_a_test_that_asserts_through_a_helper_needs_an_entry(self):
        (self.repo / "tests" / "test_a.py").write_text(
            "def helper():\n    return 1\n\n\ndef test_x():\n    assert x == 2\n\n\n"
            "def test_y():\n    check_round_trip()\n", encoding="utf-8")
        self._git("commit", "-qam", "add test_y")
        sent = self.review()
        tree = self.snapshot()
        self.edit(test_a="def helper():\n    return 1\n\n\ndef test_x():\n    assert x == 2\n")
        with self.assertRaises(ledger.RecordError):
            self.fix(tree, sent, changed_files=["a.py", "tests/test_a.py"])

    def test_a_fix_whose_window_ends_in_a_non_fix_step_is_refused(self):
        # Triage moved on (done) after routing the round: the fix is stale.
        self.spec(self.issue)
        sent = [self.spec_id(self.issue)]
        ledger.cmd_resolve(self.store, sent[0], "user ruling: waive")
        self.triage()
        tree = self.manual_snapshot()
        self.edit()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.fix(tree, sent)
        self.assertIn("done", str(ctx.exception))

    def test_baseline_prints_the_round_its_findings_and_errors_untriaged(self):
        sent = self.review()
        tree = self.snapshot()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_baseline(self.store, tree, 3)
        for expected in ("round: patch", "recheck: raising", sent[0]):
            self.assertIn(expected, out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, 3, "pre-fix c3", "tree-b")
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_baseline(self.store, "tree-b", 3)


class TestHolisticFix(TriageStoreTestCase):
    def test_a_holistic_fix_implements_this_rounds_decision_case_by_case(self):
        issue = _finding(sites=["a.py:1"], reach="contract")
        self.coder()  # the task's first attempt, cycle 1
        self.spec(issue)
        self.triage()
        entry = self.entries()[-1]
        self.assertEqual((entry["kind"], entry["decision"]), ("holistic", "task-3-decision-c2"))
        fid = self.spec_id(issue)
        self.write("task-3-decision-c2.json", _decision(
            [fid], task=3, reviewer_records=["task-3-spec-reviewer"],
            choices=[_fix_choice([fid])]))
        tree = _baseline(self.store, 3)
        (self.repo / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        fields = dict(cycle=2, baseline=tree, changed_files=["a.py"],
                      diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
                      hunk_map=[{"site": "a.py:2", "implements": "choice 0"}], consumers_checked=[])
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(self.coder(decision="task-3-decision-c2", **fields)))
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_check(str(self.coder(decision="task-3-decision-c1", **fields,
                                            decision_rows=[{"choice": 0, "case": 0, "hunk": "a.py:2"}])))
        ledger.cmd_check(str(self.coder(decision="task-3-decision-c2", **fields,
                                        decision_rows=[{"choice": 0, "case": 0, "hunk": "a.py:2"}])))


    def holistic_round(self, *issues: dict) -> str:
        """Review, triage to a holistic round, and snapshot for its fix."""
        self.coder()
        self.spec(*issues)
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "holistic")
        return _baseline(self.store, 3)

    def holistic_fix(self, tree: str, **fields) -> None:
        record = dict(cycle=2, baseline=tree, changed_files=["a.py"], decision="task-3-decision-c2",
                      diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
                      hunk_map=[], consumers_checked=[])
        record.update(fields)
        ledger.cmd_check(str(self.coder(**record)))

    def test_notes_sent_in_a_holistic_round_must_be_fixed_or_skipped(self):
        issue, note = _finding(reach="contract"), _finding(severity=1, rule="name says what it holds")
        tree = self.holistic_round(issue, note)
        fid, nid = self.spec_id(issue), self.spec_id(note)
        escalate = {"kind": "escalate", "findings": [fid], "why": "the plan fixes the API", "evidence": "plan §3"}
        self.write("task-3-decision-c2.json", _decision(
            [fid], task=3, status="escalated", reviewer_records=["task-3-spec-reviewer"],
            choices=[escalate], excluded=[{"finding": nid, "reason": "a note; the coder handles it"}]))
        contest = [{"finding": fid, "reason": "plan-conflict", "evidence": "plan §3 fixes the API"}]
        with self.assertRaises(ledger.RecordError) as ctx:
            self.holistic_fix(tree, contested=contest)
        self.assertIn(nid, str(ctx.exception))
        self.holistic_fix(tree, contested=contest,
                          notes_skipped=[{"finding": nid, "reason": "renaming breaks callers"}])

    def test_a_finding_the_decision_escalates_must_be_contested(self):
        issue = _finding(reach="contract")
        tree = self.holistic_round(issue)
        fid = self.spec_id(issue)
        escalate = {"kind": "escalate", "findings": [fid], "why": "the plan fixes the API", "evidence": "plan §3"}
        self.write("task-3-decision-c2.json", _decision(
            [fid], task=3, status="escalated", reviewer_records=["task-3-spec-reviewer"],
            choices=[escalate]))
        with self.assertRaises(ledger.RecordError) as ctx:
            self.holistic_fix(tree)
        self.assertIn(fid, str(ctx.exception))
        self.holistic_fix(tree, contested=[{"finding": fid, "reason": "plan-conflict",
                                            "evidence": "plan §3: the decision's escalation"}])


class TestUserDecisionsRouteBack(TriageStoreTestCase):
    """What the stage batch decides comes back into the loop: an override is
    a ruling round, a deferred or waived root cause stops counting, and a
    per-task decision's escalation goes through the contest path."""

    choice = {"question": "size=None?", "choice": "ValueError", "precedent": "a.py:1"}
    root = "root cause: a.py:1 the size guard lives in the wrong layer"

    def choice_id(self) -> str:
        return _entry_id("task-3-python-coder", "open", self.choice)

    def root_id(self) -> str:
        return _entry_id("task-3-python-coder", "concerns", self.root)

    def test_an_override_after_done_is_a_ruling_round_the_spec_reviewer_rechecks(self):
        self.coder(open=[self.choice])
        self.spec()
        self.triage()
        ledger.cmd_append(self.store, "progress", 3, f"user ruling: override {self.choice_id()}: return None")
        ledger.cmd_resolve(self.store, self.choice_id(), "user ruling: override, return None")
        out = self.triage()
        last = self.entries()[-1]
        self.assertEqual((last["kind"], last["recheck"], last["recheck_records"]),
                         ("ruling", "spec", ["task-3-spec-reviewer"]))
        self.assertIn("re-check: task-3-spec-reviewer", out)

    def test_an_opus_ruling_starts_no_round(self):
        self.spec()
        self.triage()
        ledger.cmd_append(self.store, "progress", 3, "user ruling: opus coder for this task")
        self.triage()
        self.assertEqual([e["kind"] for e in self.entries()], ["done"])

    def test_a_root_cause_a_decision_excludes_stops_counting_and_is_filed_once(self):
        self.coder(concerns=[self.root])
        self.spec()
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "holistic")
        self.write("task-3-decision-c2.json", _decision(
            [], task=3, reviewer_records=["task-3-spec-reviewer"], choices=[],
            excluded=[{"finding": self.root_id(), "reason": "moving the guard is its own refactor"}]))
        self.fixed(concerns=[self.root], report="still lists it")
        self.triage()
        self.coder(report="dropped it once the decision claimed it")
        self.triage()
        self.assertEqual([e["kind"] for e in self.entries()], ["holistic", "done", "done"])
        follow_ups = [n for n in ledger.notes_from_log(ledger.load_progress_log(self.store))
                      if n["kind"] == "follow-up"]
        self.assertEqual([n.get("rule") for n in follow_ups], ["moving the guard is its own refactor"])

    def test_a_root_cause_only_the_user_waives(self):
        self.coder(concerns=[self.root])
        self.spec()
        self.triage()
        self.fixed(concerns=[self.root])
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_resolve(self.store, self.root_id(), "not needed")
        ledger.cmd_resolve(self.store, self.root_id(), "user ruling: leave the guard where it is")
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "done")

    def test_a_decision_stays_valid_after_the_coder_drops_the_root_cause_it_claimed(self):
        self.coder(concerns=[self.root])
        self.spec()
        self.triage()
        decision = self.write("task-3-decision-c2.json", _decision(
            [], task=3, reviewer_records=["task-3-spec-reviewer"], choices=[],
            excluded=[{"finding": self.root_id(), "reason": "its own refactor"}]))
        ledger.check_record(decision)
        self.coder(cycle=2, baseline="t", hunk_map=[], consumers_checked=[],
                   diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"})
        ledger.check_record(decision)

    def test_a_per_task_decision_escalation_never_blocks_ready(self):
        # The coder contests it and the reviewer's hold parks the task instead.
        fid = self.spec_id(_finding())
        escalate = {"kind": "escalate", "findings": [fid], "why": "w", "evidence": "e"}
        self.write("task-3-decision-c2.json", _decision(
            [fid], task=3, status="escalated", reviewer_records=["task-3-spec-reviewer"],
            choices=[escalate]))
        self.spec()
        self.triage()
        items = ledger.compute_open_items(ledger.load_records(self.store), set())
        self.assertNotIn(ledger.ESCALATION_KIND, [i.kind for i in items])
        self.assertEqual(ledger.ready_blockers(self.store, 3), [])


class TestEndToEnd(TriageStoreTestCase):
    """A task walked through the whole loop on a real repo and store, every
    record passing `check` the way the agents' records must."""

    DIAGNOSIS = {"root_cause": "r", "end_state": "e", "resolves_cluster": "c"}

    def setUp(self):
        super().setUp()
        ledger.cmd_stage(self.store, 3, 1, ["a.py", "tests/test_size.py"])
        (self.repo / "tests").mkdir()
        self.files("def size(n):\n    return n\n", "def test_one():\n    assert size(1) == 1\n")

    def files(self, a_py: str, test_size: str) -> None:
        (self.repo / "a.py").write_text(a_py, encoding="utf-8")
        (self.repo / "tests" / "test_size.py").write_text(test_size, encoding="utf-8")

    def check(self, path: Path) -> None:
        ledger.cmd_check(str(path))

    def snapshot(self, label: str) -> str:
        """The baseline triage took for the round it just routed."""
        return _baseline(self.store, 3)

    def fix(self, cycle: int, tree: str, **fields) -> None:
        self.check(self.coder(cycle=cycle, baseline=tree, changed_files=["a.py", "tests/test_size.py"],
                              diagnosis=self.DIAGNOSIS, consumers_checked=[], **fields))

    def blockers(self) -> list[str]:
        return ledger.ready_blockers(self.store, 3)

    def commit(self) -> None:
        self._git("add", "a.py", "tests/test_size.py")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ledger.cmd_gate(self.store, 3, "grep -q 'def size' a.py", None), 0)
        self._git("commit", "-qm", "task 3")
        ledger.cmd_append(self.store, "complete", 3, "commits a..b")
        self.assertIn("3", ledger.completed_task_ids(ledger.load_progress_log(self.store)))

    def test_a_patch_then_an_overridden_choice_then_the_commit(self):
        choice = {"question": "size(None)?", "choice": "raise TypeError", "precedent": "a.py:1"}
        choice_id = _entry_id("task-3-python-coder", "open", choice)
        self.check(self.coder(open=[choice]))
        issue = _finding(sites=["a.py:2"], rule="size must be positive")
        note = _finding(severity=1, sites=["a.py:1"], rule="name says what it holds")
        self.check(self.spec(issue, note))
        self.triage()
        step = self.entries()[-1]
        self.assertEqual((step["kind"], step["recheck_records"]), ("patch", ["task-3-spec-reviewer"]))

        tree = self.snapshot("pre-fix c2")
        self.files("def size(n):\n    if n <= 0:\n        raise ValueError(n)\n    return n\n",
                   "def test_one():\n    assert size(1) == 1\n\n\ndef test_zero():\n"
                   "    with pytest.raises(ValueError):\n        size(0)\n")
        self.fix(2, tree, open=[choice], hunk_map=[{"site": "a.py:2-3", "implements": "the guard"}],
                 sweeps=[{"findings": [self.spec_id(issue)], "rule": issue["rule"],
                          "rows": [{"site": "a.py:2", "hunk": "a.py:2-3"}],
                          "searched": {"command": "rg -n 'def size' .", "result": "a.py:1 only"}}],
                 notes_skipped=[{"finding": self.spec_id(note), "reason": "callers use the name"}],
                 tests_first=[{"finding": self.spec_id(issue), "test": "tests/test_size.py::test_zero",
                               "command": "pytest tests/test_size.py", "failed_output": "DID NOT RAISE"}])
        self.check(self.spec())
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "done")
        self.assertTrue(any(choice_id in b for b in self.blockers()))  # parked for the batch

        ledger.cmd_append(self.store, "progress", 3, f"user ruling: override {choice_id}: size(None) is 0")
        ledger.cmd_resolve(self.store, choice_id, "user ruling: override, size(None) is 0")
        self.triage()
        step = self.entries()[-1]
        self.assertEqual((step["kind"], step["recheck_records"]), ("ruling", ["task-3-spec-reviewer"]))

        tree = self.snapshot("pre-fix c3")
        self.files("def size(n):\n    if n is None:\n        return 0\n    if n <= 0:\n"
                   "        raise ValueError(n)\n    return n\n",
                   "def test_one():\n    assert size(1) == 1\n\n\ndef test_zero():\n"
                   "    with pytest.raises(ValueError):\n        size(0)\n\n\n"
                   "def test_none():\n    assert size(None) == 0\n")
        self.fix(3, tree, hunk_map=[{"site": "a.py:2-3", "implements": "the user's ruling"}])
        self.check(self.spec())
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "done")
        self.assertEqual(self.blockers(), [])
        self.commit()
        follow_ups = [n for n in ledger.notes_from_log(ledger.load_progress_log(self.store))
                      if n["kind"] == "follow-up"]
        self.assertEqual(len(follow_ups), 1)  # the skipped note, for the close batch

    def test_a_holistic_round_that_defers_a_root_cause_and_escalates_a_finding(self):
        root = "root cause: lib/callers.py:4 callers pass sizes unchecked"
        self.check(self.coder(concerns=[root]))
        api = _finding(reach="contract", sites=["a.py:1"], rule="size() keeps its public signature")
        bug = _finding(sites=["a.py:2"], rule="size must be positive")
        self.check(self.spec(api))
        quality = self.write("task-3-python-quality-reviewer.json",
                             _quality_reviewer(task=3, status="issues", findings=[bug]))
        self.check(quality)
        self.triage()
        step = self.entries()[-1]
        self.assertEqual((step["kind"], step["decision"]), ("holistic", "task-3-decision-c2"))
        self.assertEqual(step["recheck_records"], ["task-3-python-quality-reviewer", "task-3-spec-reviewer"])

        api_id, bug_id = self.spec_id(api), _entry_id("task-3-python-quality-reviewer", "findings", bug)
        root_id = _entry_id("task-3-python-coder", "concerns", root)
        escalate = {"kind": "escalate", "findings": [api_id], "why": "the plan fixes this signature",
                    "evidence": "plan Task 3: size(n) -> int"}
        self.check(self.write("task-3-decision-c2.json", _decision(
            [bug_id], task=3, status="escalated",
            reviewer_records=["task-3-python-quality-reviewer", "task-3-spec-reviewer"],
            choices=[_fix_choice([bug_id], cases=[
                {"case": "size(0)", "site": "a.py:2", "test": "tests/test_size.py::test_zero",
                 "today": "returns 0", "under_fix": "raises ValueError", "result": "fixed"}]), escalate],
            excluded=[{"finding": root_id, "reason": "validating callers is its own task"}])))

        tree = self.snapshot("pre-fix c2")
        self.files("def size(n):\n    if n <= 0:\n        raise ValueError(n)\n    return n\n",
                   "def test_one():\n    assert size(1) == 1\n\n\ndef test_zero():\n"
                   "    with pytest.raises(ValueError):\n        size(0)\n")
        self.fix(2, tree, decision="task-3-decision-c2",
                 hunk_map=[{"site": "a.py:2-3", "implements": "decision choice 0"}],
                 decision_rows=[{"choice": 0, "case": 0, "hunk": "a.py:2-3"}],
                 contested=[{"finding": api_id, "reason": "plan-conflict",
                             "evidence": "plan Task 3 fixes size(n) -> int; the decision escalates it"}])
        self.check(self.spec(api, contests=[{"finding": api_id, "verdict": "hold",
                                             "reason": "the plan predates the caller"}]))
        self.check(self.write("task-3-python-quality-reviewer.json", _quality_reviewer(task=3)))
        self.triage()
        step = self.entries()[-1]
        self.assertEqual((step["kind"], step["held"]), ("escalate", [api_id]))
        self.assertTrue(any(api_id in b for b in self.blockers()))

        ledger.cmd_resolve(self.store, api_id, "user ruling: waive, the plan's signature stands")
        self.triage()
        self.assertEqual(self.entries()[-1]["kind"], "done")
        self.assertEqual(self.blockers(), [])
        self.commit()
        rules = [n.get("rule") for n in ledger.notes_from_log(ledger.load_progress_log(self.store))
                 if n["kind"] == "follow-up"]
        self.assertEqual(rules, ["validating callers is its own task"])


class TestTriageOutput(TriageStoreTestCase):
    """What `triage` prints and records for the orchestrator's next dispatch."""

    def gate_record(self, *findings: dict) -> None:
        self.write("task-3-gate.json", {
            "schema": 2, "agent": "ledger", "role": "gate", "task": 3,
            "status": "fail" if findings else "pass", "tree": "t", "files": ["a.py"],
            "commands": [], "findings": list(findings), "recurring": [], "introduced_by_fix": []})

    def test_settled_ids_and_the_decision_doc_are_printed(self):
        issue, other = _finding(reach="contract"), _finding(rule="other rule")
        self.coder()
        self.spec(issue, other)
        ledger.cmd_resolve(self.store, self.spec_id(other), "user ruling: waive")
        out = self.triage()
        self.assertIn(f"settled: {self.spec_id(other)}", out)
        self.assertIn("decision doc: task-3-decision-c2", out)

    def test_the_first_fix_at_final_is_cycle_two_so_its_decision_is_c2(self):
        self.write("final-python-review-lite.json", _review_lite(
            task="final", status="block", findings=[_finding(reach="contract")]))
        self.triage("final")
        self.assertEqual(self.entries()[-1]["decision"], "final-decision-c2")

    def test_the_gate_is_rerun_not_redispatched(self):
        issue = _finding()
        self.spec(issue)
        self.gate_record(_finding(rule="`pytest` passes", sites=["a.py"], claim="the test command failed"))
        for recheck in ("raising", "all"):
            with self.subTest(recheck=recheck):
                if recheck == "all":
                    self.coder()
                    self.spec(issue, _finding(reach="contract", rule="api"))
                out = self.triage()
                last = self.entries()[-1]
                self.assertNotIn("task-3-gate", last["recheck_records"])
                self.assertIn("re-stage and re-run `gate`", out)

    def test_contest_answers_count_only_from_the_raising_reviewer(self):
        issue = _finding()
        self.spec(issue)
        self.triage()
        self.coder(contested=[{"finding": self.spec_id(issue), "reason": "wrong", "evidence": "e"}])
        self.write("task-3-python-quality-reviewer.json", _quality_reviewer(
            task=3, contests=[{"finding": self.spec_id(issue), "verdict": "concede", "reason": "r"}]))
        self.triage()
        self.assertNotIn(self.spec_id(issue), self.entries()[-1]["settled"])

    def test_settled_lists_only_this_scopes_ids(self):
        ledger.cmd_stage(self.store, 4, 1, ["b.py"])
        other = _finding(sites=["b.py:1"])
        self.write("task-4-spec-reviewer.json", _spec_reviewer(task=4, status="issues", issues=[other]))
        ledger.cmd_resolve(self.store, _entry_id("task-4-spec-reviewer", "issues", other),
                           "user ruling: waive")
        self.spec()
        self.triage()
        self.assertEqual(self.entries()[-1]["settled"], [])


class TestChangedLines(unittest.TestCase):
    def test_an_added_line_that_looks_like_a_file_header_stays_in_its_file(self):
        diff = ("--- a/a.py\n+++ b/a.py\n@@ -1,0 +1,2 @@\n+x = 1\n+++ b/evil.py\n"
                "--- a/b.py\n+++ b/b.py\n@@ -3,0 +4 @@\n+y = 2\n")
        self.assertEqual(ledger.changed_lines(diff), {"a.py": {1, 2}, "b.py": {4}})

    def test_a_quoted_path_is_decoded(self):
        diff = '--- "a/sp ace.py"\n+++ "b/sp ace.py"\n@@ -1 +1 @@\n-x = 0\n+x = 1\n'
        self.assertEqual(ledger.changed_lines(diff), {"sp ace.py": {1}})

    def test_a_pure_deletion_marks_the_line_it_removed(self):
        diff = "--- a/a.py\n+++ b/a.py\n@@ -2 +1,0 @@\n-y = 2\n"
        self.assertEqual(ledger.changed_lines(diff), {"a.py": {1}})


class TestPlainSnapshot(LedgerTestCase):
    def test_a_snapshot_records_task_label_and_tree_only(self):
        ledger.ensure_store(self.store)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, 4, "pre-fix c2", "deadbeef")
        [entry] = ledger.load_progress_log(self.store)
        self.assertEqual(entry, {"type": "snapshot", "task": 4, "label": "pre-fix c2",
                                 "tree": "deadbeef"})

    def test_the_removed_route_flags_and_command_are_rejected(self):
        flag = "--" + "non" + "-trivial"
        command = "fix" + "-count"
        for argv in (["snapshot", "--task", "1", "--label", "x", flag], [command, "--task", "1"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ledger.build_parser().parse_args(argv)

    def test_a_log_with_old_route_fields_still_renders(self):
        ledger.ensure_store(self.store)
        legacy = {"type": "snapshot", "task": 2, "label": "pre-fix c2", "tree": "t",
                  "non" + "_trivial": True, "decision": "task-2-decision-c2"}
        (self.store / ledger.PROGRESS_FILENAME).write_text(json.dumps(legacy) + "\n")
        self.assertIn("pre-fix c2", ledger.render_store_markdown([], ledger.load_progress_log(self.store)))


class TestGate(TriageStoreTestCase):
    """`gate` runs labels, lint, and the task's Verify command on the staged
    scope files; each passes only on exit 0."""

    def stage_fix(self, text: str = "x = 1\ny = 2\n") -> None:
        (self.repo / "a.py").write_text(text, encoding="utf-8")
        self._git("add", "a.py")

    def gate(self, test: str = "true", lint: str | None = "true", task: int | str = 3) -> tuple[int, dict]:
        with contextlib.redirect_stdout(io.StringIO()):
            code = ledger.cmd_gate(self.store, task, test, lint)
        prefix = "task-3" if task == 3 else "final"
        return code, json.loads((self.store / f"{prefix}-gate.json").read_text())

    def test_everything_passing_writes_a_passing_record(self):
        self.stage_fix()
        code, record = self.gate()
        self.assertEqual((code, record["status"], record["findings"]), (0, "pass", []))
        self.assertEqual([c["kind"] for c in record["commands"]], ["labels", "lint", "test"])
        ledger.cmd_check(str(self.store / "task-3-gate.json"))

    def test_an_unexcused_label_fails_without_a_finding(self):
        self.stage_fix("x = 1\ny = 2  # fixed per the decision doc\n")
        code, record = self.gate()
        self.assertEqual((code, record["status"], record["findings"]), (1, "fail", []))

    def test_a_label_the_coder_listed_as_a_false_positive_passes(self):
        line = "y = 2  # fixed per the decision doc"
        self.coder(concerns=[f"label false positive: a.py: {line}"])
        self.stage_fix(f"x = 1\n{line}\n")
        self.assertEqual(self.gate()[0], 0)

    def test_a_failing_lint_fails_without_a_finding(self):
        self.stage_fix()
        code, record = self.gate(lint="false")
        self.assertEqual((code, record["status"], record["findings"]), (1, "fail", []))

    def test_a_failing_test_becomes_one_serious_local_finding(self):
        self.stage_fix()
        code, record = self.gate(test="exit 1")
        self.assertEqual((code, record["status"]), (1, "fail"))
        [finding] = record["findings"]
        self.assertEqual((finding["severity"], finding["reach"], finding["sites"]), (3, "local", ["a.py"]))
        self.assertIn("exit 1", finding["rule"])
        self.assertIn("task-3-gate#status", {i.id for i in ledger.compute_open_items(
            ledger.load_records(self.store), set())})

    def test_a_failing_tests_finding_keeps_its_id_across_runs(self):
        # The excerpt (timings, temp paths) lives on the command, so a re-run
        # that fails the same way raises the same finding, never a new one.
        self.coder(cycle=2, status="done", baseline="t",
                   diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
                   hunk_map=[], consumers_checked=[])
        self.stage_fix()
        counter = Path(self._tmp.name) / "runs"
        test = f"echo run >> {counter}; wc -l < {counter}; exit 1"
        _, record = self.gate(test=test)
        _, again = self.gate(test=test)
        self.assertNotEqual(record["commands"][-1]["excerpt"], again["commands"][-1]["excerpt"])
        self.assertEqual(record["findings"], again["findings"])
        self.assertEqual(record["introduced_by_fix"], [])

    def test_a_zero_matches_check_passes_when_nothing_matches(self):
        self.stage_fix()
        self.assertEqual(self.gate(test="! grep -q TODO a.py")[0], 0)

    def test_without_lint_only_labels_and_test_run(self):
        self.stage_fix()
        self.assertEqual([c["kind"] for c in self.gate(lint=None)[1]["commands"]], ["labels", "test"])

    def test_a_scope_without_a_footprint_or_a_change_is_refused(self):
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_gate(self.store, 9, "true", None)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_gate(self.store, 3, "true", None)
        self.assertIn("a.py", str(ctx.exception))

    def test_edits_new_files_and_deletions_in_the_footprint_are_staged_and_gated(self):
        (self.repo / "c.py").write_text("c = 1\n", encoding="utf-8")
        self._git("add", "c.py")
        self._git("commit", "-qm", "c")
        ledger.cmd_stage(self.store, 3, 1, ["a.py", "b.py", "c.py"])
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "b.py").write_text("b = 1\n", encoding="utf-8")
        (self.repo / "c.py").unlink()
        code, record = self.gate()
        self.assertEqual(code, 0)
        self.assertEqual(self._git("diff", "--cached", "--name-status").split(),
                         ["M", "a.py", "A", "b.py", "D", "c.py"])
        self.assertEqual(record["files"], ["a.py", "b.py", "c.py"])

    def test_a_change_outside_the_footprint_stays_unstaged(self):
        (self.repo / "z.py").write_text("z = 1\n", encoding="utf-8")
        self._git("add", "z.py")
        self._git("commit", "-qm", "z")
        (self.repo / "z.py").write_text("z = 2\n", encoding="utf-8")
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        self.gate()
        self.assertEqual(self._git("diff", "--cached", "--name-only").split(), ["a.py"])
        self.assertEqual(self._git("diff", "--name-only").split(), ["z.py"])

    def test_the_final_footprint_adds_the_final_coders_changed_files(self):
        (self.repo / "lib").mkdir()
        (self.repo / "lib" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self.write("final-python-coder.json", _coder(task="final", changed_files=["lib/x.py"]))
        code, record = self.gate(task="final")
        self.assertEqual(code, 0)
        self.assertIn("lib/x.py", record["files"])
        self.assertIn("lib/x.py", self._git("diff", "--cached", "--name-only").split())

    def test_the_store_is_unlocked_while_the_commands_run(self):
        # Parallel tasks' agents write the store while a gate's tests run.
        self.stage_fix()
        probe = Path(self._tmp.name) / "probe_lock.py"
        probe.write_text(
            "import fcntl, sys\n"
            f"with open({str(self.store / ledger.LOCK_FILENAME)!r}, 'a') as h:\n"
            "    try:\n"
            "        fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "    except BlockingIOError:\n"
            "        sys.exit(1)\n", encoding="utf-8")
        self.assertEqual(self.gate(test=f"python3 {probe}")[0], 0)

    def test_the_staged_tree_is_recorded_and_the_index_left_alone(self):
        self.stage_fix()
        before = self._git("diff", "--cached", "--name-only")
        _, record = self.gate()
        self.assertEqual(record["tree"], self._git("write-tree").strip())
        self.assertEqual(self._git("diff", "--cached", "--name-only"), before)

    def complete(self) -> None:
        _triaged(self.store, 3, kind="done")
        ledger.cmd_append(self.store, "complete", 3, "shipped")

    def test_complete_needs_a_passing_gate_matching_the_commit(self):
        self.stage_fix()
        with self.assertRaises(ledger.RecordError):
            self.complete()
        self.gate(test="exit 1")
        self._git("commit", "-qm", "fix")
        with self.assertRaises(ledger.RecordError):
            self.complete()
        with self.assertRaises(ledger.RecordError):
            self.gate(test="true")  # nothing staged now: refused, the record stays failed
        self.stage_fix("x = 1\ny = 3\n")
        self.gate()
        self._git("commit", "-qm", "fix")
        self.complete()

    def test_complete_refuses_a_file_changed_after_the_gate(self):
        self.stage_fix()
        self.gate()
        (self.repo / "a.py").write_text("x = 1\ny = 4\n", encoding="utf-8")
        self._git("commit", "-qam", "changed after the gate")
        with self.assertRaises(ledger.RecordError) as ctx:
            self.complete()
        self.assertIn("a.py", str(ctx.exception))


class TestCommit(TriageStoreTestCase):
    """`commit` takes a ready task from staging to a completed commit, and
    touches nothing when it stops."""

    MESSAGE = "Guard size against zero\n\nA second paragraph, kept verbatim."

    def setUp(self):
        super().setUp()
        (self.repo / "p.py").write_text("p = 1\n", encoding="utf-8")
        self._git("add", "p.py")
        self._git("commit", "-qm", "p")

    def ready_to_commit(self) -> None:
        self.spec()
        self.triage()
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")

    def commit(self, task: int | str = 3, test: str = "true", light: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ledger.cmd_commit(self.store, task, self.MESSAGE, test, None, light)
        return code, out.getvalue()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def completes(self) -> list[dict]:
        return [e for e in ledger.load_progress_log(self.store) if e.get("type") == "complete"]

    def test_a_blocker_stages_nothing_and_commits_nothing(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        before = self.head()
        code, out = self.commit()
        self.assertEqual(code, 1)
        self.assertIn("no triage entry", out)
        self.assertEqual((self.head(), self._git("diff", "--cached", "--name-only")), (before, ""))

    def test_a_coder_file_outside_the_footprint_is_refused_by_name(self):
        self.ready_to_commit()
        self.coder(changed_files=["a.py", "b.py"])
        self.triage()
        with self.assertRaises(ledger.RecordError) as ctx:
            self.commit()
        self.assertIn("b.py", str(ctx.exception))
        self.assertEqual(self._git("diff", "--cached", "--name-only"), "")

    def test_a_ready_task_becomes_one_commit_with_the_message_and_a_complete_entry(self):
        (self.repo / "n.py").write_text("n = 1\n", encoding="utf-8")
        ledger.cmd_stage(self.store, 3, 1, ["a.py", "n.py", "p.py"])
        (self.repo / "p.py").unlink()
        self.ready_to_commit()
        before = self.head()
        code, out = self.commit()
        self.assertEqual(code, 0, out)
        after = self.head()
        self.assertEqual(self._git("rev-list", "--count", f"{before}..{after}").strip(), "1")
        self.assertEqual(self._git("log", "-1", "--format=%B").rstrip("\n"), self.MESSAGE)
        self.assertEqual(self._git("show", "--name-status", "--format=", "HEAD").split(),
                         ["M", "a.py", "A", "n.py", "D", "p.py"])
        [entry] = self.completes()
        self.assertEqual(entry["note"], f"commits {before[:7]}..{after[:7]}")
        self.assertIn(f"committed {after}", out)
        self.assertIn("task 3 complete", out)

    def test_a_path_another_task_staged_stays_staged_and_out_of_the_commit(self):
        self.ready_to_commit()
        (self.repo / "p.py").write_text("p = 2\n", encoding="utf-8")
        self._git("add", "p.py")
        self.assertEqual(self.commit()[0], 0)
        self.assertEqual(self._git("show", "--name-only", "--format=", "HEAD").split(), ["a.py"])
        self.assertEqual(self._git("diff", "--cached", "--name-only").split(), ["p.py"])

    def test_a_failing_gate_writes_its_record_and_commits_nothing(self):
        self.ready_to_commit()
        before = self.head()
        code, out = self.commit(test="exit 1")
        self.assertEqual(code, 1)
        self.assertIn("gate: fail", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.completes(), [])
        gate = json.loads((self.store / "task-3-gate.json").read_text())
        self.assertEqual(gate["status"], "fail")

    def test_a_gate_already_passed_on_the_same_files_is_not_rerun(self):
        self.ready_to_commit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ledger.cmd_gate(self.store, 3, "true", None), 0)
        code, out = self.commit(test="exit 1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("gate: fail", out)

    def test_a_file_changed_since_the_passing_gate_is_gated_again(self):
        self.ready_to_commit()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_gate(self.store, 3, "true", None)
        (self.repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        self.assertEqual(self.commit(test="exit 1")[0], 1)

    def test_the_light_path_commits_without_triage(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        self.assertEqual(self.commit(light=True)[0], 0)
        self.assertTrue(self.completes()[0]["light"])

    def test_final_commits_the_final_coders_changed_files(self):
        (self.repo / "lib").mkdir()
        (self.repo / "lib" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self.write("final-python-review-lite.json", _review_lite(task="final"))
        self.write("final-python-coder.json", _coder(task="final", changed_files=["lib/x.py"]))
        self.triage("final")
        self.assertEqual(self.commit(task="final")[0], 0)
        self.assertIn("lib/x.py", self._git("show", "--name-only", "--format=", "HEAD").split())

    def test_a_commit_git_refuses_appends_nothing(self):
        self.ready_to_commit()
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'hook says no' >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        before = self.head()
        code, out = self.commit()
        self.assertEqual(code, 1)
        self.assertIn("hook says no", out)
        self.assertEqual((self.head(), self.completes()), (before, []))

    def test_a_refused_complete_after_the_commit_reports_it_and_keeps_it(self):
        self.ready_to_commit()
        before = self.head()
        with mock.patch.object(ledger, "_check_gate_matches_commit",
                               side_effect=ledger.RecordError("a.py changed between the gate and the commit")):
            code, out = self.commit()
        self.assertEqual(code, 1)
        self.assertNotEqual(self.head(), before)
        self.assertIn(f"committed {self.head()}", out)
        self.assertIn("a.py changed", out)
        self.assertEqual(self.completes(), [])

    def test_nothing_left_to_commit_never_commits_another_tasks_staged_files(self):
        self.ready_to_commit()
        self.assertEqual(self.commit()[0], 0)
        (self.repo / "p.py").write_text("p = 2\n", encoding="utf-8")
        self._git("add", "p.py")
        before = self.head()
        self.assertEqual(self.commit()[0], 1)
        self.assertEqual(self.head(), before)
        self.assertEqual(self._git("diff", "--cached", "--name-only").split(), ["p.py"])

    def test_an_empty_message_is_refused(self):
        self.ready_to_commit()
        with self.assertRaises(ledger.RecordError):
            with contextlib.redirect_stdout(io.StringIO()):
                ledger.cmd_commit(self.store, 3, "  ", "true", None)


class TestReady(TriageStoreTestCase):
    """`ready` lists everything that stops a task from committing; `complete`
    refuses on the same list."""

    def ready(self, task: int | str = 3, light: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ledger.cmd_ready(self.store, task, light)
        return code, out.getvalue()

    def test_a_done_task_with_nothing_open_is_ready(self):
        self.spec()
        self.triage()
        self.assertEqual(self.ready()[0], 0)

    def test_no_triage_yet_blocks(self):
        code, out = self.ready()
        self.assertEqual(code, 1)
        self.assertIn("triage", out)

    def test_a_step_that_isnt_done_blocks(self):
        self.spec(_finding())
        self.triage()
        code, out = self.ready()
        self.assertEqual(code, 1)
        self.assertIn("patch", out)

    def test_a_held_finding_blocks(self):
        issue = _finding()
        self.spec(issue)
        self.triage()
        self.fixed(contested=[{"finding": self.spec_id(issue), "reason": "wrong", "evidence": "e"}])
        self.spec(issue, contests=[{"finding": self.spec_id(issue), "verdict": "hold", "reason": "r"}])
        self.triage()
        self.assertIn(self.spec_id(issue), self.ready()[1])

    def test_an_unanswered_open_choice_blocks_until_accepted(self):
        choice = {"question": "size=None?", "choice": "ValueError", "precedent": "a.py:1"}
        self.coder(open=[choice])
        self.spec()
        self.triage()
        choice_id = _entry_id("task-3-python-coder", "open", choice)
        self.assertIn(choice_id, self.ready()[1])
        ledger.cmd_resolve(self.store, choice_id, "user ruling: accept")
        self.assertEqual(self.ready()[0], 0)

    def test_notes_escalations_cannot_verify_and_malformed_records_each_block(self):
        self.spec(cannot_verify=[{"requirement": "r", "why": "w", "should_check": "s"}])
        self.triage()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_note(self.store, "task-note", "carry the helper", for_task=3)
            ledger.cmd_note(self.store, "question", "bless the goldens?", owner=3)
        (self.store / "task-3-rust-quality-reviewer.json").write_text("not json")
        code, out = self.ready()
        self.assertEqual(code, 1)
        for fragment in ("undelivered", "question", "cannot_verify", "task-3-rust-quality-reviewer"):
            self.assertIn(fragment, out)

    def test_an_open_duplication_blocks_only_the_whole_change(self):
        self.coder(duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}])
        self.spec()
        self.triage()
        self.assertEqual(self.ready()[0], 0)
        self.write("final-python-review-lite.json", _review_lite(task="final"))
        self.triage("final")
        self.assertIn("duplication_pending", self.ready("final")[1])

    def test_light_is_refused_on_a_task_the_triage_loop_runs(self):
        self.spec(_finding())
        self.triage()
        code, out = self.ready(light=True)
        self.assertEqual(code, 1)
        self.assertIn("--light", out)

    def test_light_skips_the_triage_checks_only(self):
        code, _ = self.ready(light=True)
        self.assertEqual(code, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_note(self.store, "task-note", "carry the helper", for_task=3)
        self.assertEqual(self.ready(light=True)[0], 1)

    def test_complete_refuses_with_every_blocker(self):
        self.spec(_finding())
        self.triage()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_note(self.store, "task-note", "carry the helper", for_task=3)
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_append(self.store, "complete", 3, "shipped")
        for fragment in ("patch", "undelivered"):
            self.assertIn(fragment, str(ctx.exception))

    def test_a_light_completion_is_recorded_and_reported(self):
        _write(self.store, "task-3-gate.json", {
            "schema": 2, "agent": "ledger", "role": "gate", "task": 3, "status": "pass",
            "tree": self._git("write-tree").strip(), "files": [], "commands": [], "findings": [],
            "recurring": [], "introduced_by_fix": []})
        ledger.cmd_append(self.store, "complete", 3, "shipped", light=True)
        self.assertTrue(ledger.load_progress_log(self.store)[-1]["light"])
        report = ledger.render_report(ledger.load_progress_log(self.store), [])
        self.assertIn("task 3", report.split("## Ran light")[1])


class TestPlansAndVerdict(GitRepoTestCase):
    """The store records the plans it ran, and `run-state` opens with a
    verdict on the store and the next action."""

    def setUp(self):
        super().setUp()
        self.store = self.repo / ".sdd"
        ledger.ensure_store(self.store)
        (self.repo / "plans").mkdir()
        (self.repo / "plans" / "a.md").write_text(
            "# A\n\n### Task 1: one\n\n### Task 2: two\n\n```\n### Task 9: fenced\n```\n",
            encoding="utf-8")
        (self.repo / "plans" / "b.md").write_text("# B\n\n### Task 3: three\n", encoding="utf-8")
        old = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, old)

    def _plans(self) -> list[str]:
        return ledger.recorded_plans(ledger.load_progress_log(self.store))

    def _state(self, plan: str | None = None) -> list[str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_run_state(self.store, plan)
        return out.getvalue().splitlines()

    def test_recording_a_plan_is_idempotent_whatever_its_spelling(self):
        ledger.record_plan(self.store, "plans/a.md")
        ledger.record_plan(self.store, "./plans/a.md")
        ledger.record_plan(self.store, str(self.repo / "plans" / "a.md"))
        self.assertEqual(self._plans(), ["plans/a.md"])

    def test_a_second_plan_is_recorded_separately(self):
        ledger.record_plan(self.store, "plans/a.md")
        ledger.record_plan(self.store, "plans/b.md")
        self.assertEqual(self._plans(), ["plans/a.md", "plans/b.md"])

    def test_run_state_opens_with_the_verdict_and_next_action(self):
        ledger.record_plan(self.store, "plans/a.md")
        ledger.cmd_append(self.store, "progress", 1, "started")
        lines = self._state("plans/a.md")
        self.assertEqual(lines[0], "Verdict: resume")
        self.assertEqual(lines[1], "Next: resume at task 1")
        self.assertIn("# Run state", lines)

    def test_a_fenced_task_heading_is_not_a_plan_task(self):
        ledger.record_plan(self.store, "plans/a.md")
        _completable(self.store, 1)
        ledger.cmd_append(self.store, "complete", 1, "commits a..b")
        _completable(self.store, 2)
        ledger.cmd_append(self.store, "complete", 2, "commits b..c")
        self.assertIn("whole-change gate", self._state("plans/a.md")[1])

    def test_without_plan_the_latest_recorded_plan_is_used(self):
        ledger.record_plan(self.store, "plans/a.md")
        ledger.record_plan(self.store, "plans/b.md")
        self.assertEqual(self._state()[1], "Next: resume at task 3")

    def test_an_unrecorded_plan_is_foreign(self):
        ledger.record_plan(self.store, "plans/a.md")
        self.assertEqual(self._state("plans/b.md")[0], "Verdict: foreign")

    def test_a_missing_plan_file_is_a_usage_error(self):
        with self.assertRaisesRegex(ledger.UsageError, "nope.md"):
            self._state("plans/nope.md")

    def test_a_store_from_before_plans_were_recorded_is_ambiguous(self):
        _completable(self.store, 1)
        ledger.cmd_append(self.store, "complete", 1, "commits a..b")
        self.assertEqual(self._state("plans/a.md")[0], "Verdict: ambiguous")

    def test_a_remediation_note_makes_its_plan_a_remediation_run(self):
        ledger.record_plan(self.store, "plans/a.md")
        ledger._append_progress(self.store, {"type": "close_round", "round": 1, "head": "h",
                                             "note": "plans/a.md"})
        ledger.cmd_append(self.store, "progress", "final",
                          "close-gate remediation r1: plan ./plans/b.md, decision d.md, "
                          "intent i.md, front-end none")
        ledger.record_plan(self.store, "plans/b.md")
        lines = self._state("plans/b.md")
        self.assertEqual(lines[0], "Verdict: remediation")
        self.assertIn("task 3", lines[1])
        self.assertIn("plans/b.md", self._state("plans/a.md")[1])

    def test_read_renders_a_plan_entry(self):
        ledger.record_plan(self.store, "plans/a.md")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_read(self.store)
        self.assertIn("plan `plans/a.md`", out.getvalue())
        self.assertNotIn("unknown entry", out.getvalue())

    def test_the_cli_exits_2_on_a_missing_plan_and_prints_the_verdict_otherwise(self):
        ledger.record_plan(self.store, "plans/a.md")
        run = lambda *a: subprocess.run([sys.executable, str(LEDGER_PY), "run-state",  # noqa: E731
                                         "--store", str(self.store), *a],
                                        cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(run("--plan", "plans/nope.md").returncode, 2)
        done = run("--plan", "plans/a.md")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.startswith("Verdict: resume\n"))


class TestRoundRendering(TriageStoreTestCase):
    """`run-state`, `read` and `stats` show the rounds triage logged."""

    def run_state(self) -> str:
        return ledger.render_run_state(ledger.load_progress_log(self.store),
                                       ledger.load_records(self.store))

    def test_run_state_lists_each_task_rounds_and_what_is_parked(self):
        issue = _finding()
        choice = {"question": "size=None?", "choice": "ValueError", "precedent": "a.py:1"}
        self.spec(issue)
        self.triage()
        self.fixed(open=[choice], contested=[{"finding": self.spec_id(issue), "reason": "wrong",
                                              "evidence": "e"}])
        self.spec(issue, contests=[{"finding": self.spec_id(issue), "verdict": "hold", "reason": "r"}])
        self.triage()
        out = self.run_state()
        self.assertIn("- task 3: patch → escalate", out)
        parked = out.split("## Parked")[1].split("## ")[0]
        self.assertIn(self.spec_id(issue), parked)
        self.assertIn(_entry_id("task-3-python-coder", "open", choice), parked)

    def test_read_renders_a_triage_entry(self):
        self.spec(_finding())
        self.triage()
        markdown = ledger.render_store_markdown([], ledger.load_progress_log(self.store))
        self.assertIn("- task 3 triage: patch (round 1, recheck raising)", markdown)

    def test_stats_prints_each_round_telemetry_and_n_a_counts(self):
        self.spec(_finding())
        ledger.cmd_check(str(self.coder(model="sonnet")))
        self.triage()
        ledger.cmd_check(str(self.coder(tests_first=[
            {"finding": "f", "n/a": "structural", "reason": "r"},
            {"finding": "g", "n/a": "structural", "reason": "r"}])))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ledger.cmd_stats(self.store)
        self.assertRegex(out.getvalue(), r"round 1 patch\s+model=sonnet\s+closed=0\s+survived=0\s+"
                                         r"introduced=0")
        self.assertIn("tests_first n/a: structural=2", out.getvalue())

    def test_a_log_with_pre_change_snapshots_still_renders(self):
        legacy = {"type": "snapshot", "task": 3, "label": "pre-fix c2", "tree": "t",
                  "decision": "task-3-decision-c2"}
        ledger._append_progress(self.store, legacy)
        self.run_state()
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_stats(self.store)


class TestCoderStoreChecks(GitRepoTestCase):
    """Checks a coder record gets only inside a store: deferrals stay out of
    the task's footprint, a fix's added lines carry no process labels, and
    an open choice's precedent exists."""

    def setUp(self):
        super().setUp()
        self.store = ledger.ensure_store(self.repo / ".sdd")
        ledger.cmd_stage(self.store, 1, 1, ["a.py", "tests/test_a.py"])

    def _check(self, name: str = "task-1-python-coder.json", **fields) -> None:
        ledger.cmd_check(str(_write(self.store, name, _coder(**fields))))

    def _sweep(self, *outside: str) -> list[dict]:
        return [{"findings": ["f"], "rule": "r", "rows": [{"site": "a.py:1", "hunk": "a.py:1"}],
                 "searched": {"command": "rg r", "result": "1 match"},
                 "sites_outside": list(outside)}]

    def test_an_outside_site_beyond_the_footprint_is_accepted(self):
        self._check(sweeps=self._sweep("lib/other.py:9"))

    def test_an_outside_site_inside_the_footprint_is_refused_naming_it(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(sweeps=self._sweep("./a.py:3"))
        self.assertIn("a.py", str(ctx.exception))

    def test_a_root_cause_inside_the_footprint_is_refused(self):
        with self.assertRaises(ledger.RecordError):
            self._check(concerns=["root cause: tests/test_a.py:4 the fixture hides it"])
        self._check(concerns=["root cause: lib/cache.py:4 evicts before write"])

    def test_the_final_footprint_is_every_task_footprint(self):
        ledger.cmd_stage(self.store, 2, 2, ["b.py"])
        with self.assertRaises(ledger.RecordError):
            self._check("final-python-coder.json", task="final", sweeps=self._sweep("b.py:2"))

    def test_a_deferral_on_an_unstaged_task_asks_for_the_footprint(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check("task-7-python-coder.json", task=7, sweeps=self._sweep("lib/x.py:1"))
        self.assertIn("ledger.py stage", str(ctx.exception))
        self._check("task-7-python-coder.json", task=7)  # nothing deferred, no stage owed

    def test_a_record_outside_a_store_skips_the_store_checks(self):
        loose = self.repo / "loose"
        loose.mkdir()
        ledger.cmd_check(str(_write(loose, "task-1-python-coder.json",
                                    _coder(sweeps=self._sweep("a.py:3")))))

    def _fix_with(self, added: str, **fields) -> None:
        tree = ledger.snapshot_tree(self.repo)
        _triaged(self.store)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, 1, "pre-fix c2", tree)
        (self.repo / "a.py").write_text(f"x = 1\n{added}\n", encoding="utf-8")
        self._check(cycle=2, baseline=tree, changed_files=["a.py"],
                    diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
                    hunk_map=[{"site": "a.py:2", "implements": "the guard"}],
                    consumers_checked=[], **fields)

    def test_a_fix_whose_added_lines_are_clean_passes(self):
        self._fix_with("y = 2  # size is positive here")

    def test_a_fix_that_adds_a_process_label_is_refused_listing_it(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._fix_with("y = 2  # guard added per the decision doc")
        self.assertIn("a.py:2", str(ctx.exception))

    def test_a_label_hit_listed_as_a_false_positive_passes(self):
        line = "y = 2  # guard added per the decision doc"
        self._fix_with(line, concerns=[f"label false positive: a.py: {line}"])

    def test_the_inline_executor_may_run_on_any_model(self):
        self._check(agent="executing-plans", model="opus")

    def test_an_open_choice_citing_a_missing_file_is_refused(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(open=[{"question": "size=None?", "choice": "ValueError",
                               "precedent": "src/nowhere.py:3"}])
        self.assertIn("src/nowhere.py", str(ctx.exception))
        self._check(open=[{"question": "size=None?", "choice": "ValueError",
                           "precedent": "a.py:1"}])


class TestStoreChecksOutsideGit(LedgerTestCase):
    def test_a_store_outside_a_work_tree_skips_the_label_scan(self):
        ledger.ensure_store(self.store)
        _triaged(self.store)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, 1, "pre-fix c2", "tree-a")
        ledger.cmd_check(str(_write(self.store, "task-1-python-coder.json", _coder(
            cycle=2, baseline="tree-a", changed_files=["a.py"],
            diagnosis={"root_cause": "r", "end_state": "e", "resolves_cluster": "c"},
            hunk_map=[{"site": "a.py:2", "implements": "g"}], consumers_checked=[]))))


class TestFixBaselineIsItsOwn(LedgerTestCase):
    """A finished fix names the snapshot it started from, and no earlier
    cycle of the same record used it, so each fix has its own diff and its
    own triage entry."""

    def setUp(self):
        super().setUp()
        ledger.ensure_store(self.store)

    def _snapshot(self, tree: str, task: int | str = 1) -> None:
        _triaged(self.store, task)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(self.store, task, f"pre-fix {tree}", tree)

    def _fix(self, cycle: int, baseline: str | None, name: str = "task-1-python-coder.json",
             **overrides) -> Path:
        fields = {"cycle": cycle, "diagnosis": {"root_cause": "r", "end_state": "e",
                                                "resolves_cluster": "c"},
                  "hunk_map": [{"site": "a.py:1", "implements": "f"}], "consumers_checked": []}
        if baseline is not None:
            fields["baseline"] = baseline
        fields.update(overrides)
        return _write(self.store, name, _coder(**fields))

    def _check(self, path: Path) -> None:
        ledger.cmd_check(str(path))

    def test_a_finished_fix_without_baseline_fails(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(self._fix(2, None))
        self.assertIn("baseline", str(ctx.exception))

    def test_a_baseline_with_no_snapshot_fails(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(self._fix(2, "deadbeef"))
        self.assertIn("no snapshot", str(ctx.exception))

    def test_reusing_an_earlier_cycles_baseline_fails(self):
        self._snapshot("tree-a")
        self._check(self._fix(2, "tree-a"))
        with self.assertRaises(ledger.RecordError) as ctx:
            self._check(self._fix(3, "tree-a"))
        self.assertIn("already started cycle 2", str(ctx.exception))
        self._snapshot("tree-b")
        self._check(self._fix(3, "tree-b"))

    def test_a_resumed_fix_keeps_its_cycle_and_baseline(self):
        self._snapshot("tree-a")
        self._check(self._fix(2, None, status="needs_context"))  # paused: no baseline owed
        self._check(self._fix(2, "tree-a"))
        self._check(self._fix(2, "tree-a"))  # re-checked after a rewrite

    def test_two_coders_may_share_one_cycles_baseline(self):
        self._snapshot("tree-a")
        self._check(self._fix(2, "tree-a"))
        self._check(self._fix(3, "tree-a", name="task-1-rust-coder.json", agent="rust-coder"))

    def test_first_attempts_and_final_scope(self):
        self._check(_write(self.store, "task-1-python-coder.json", _coder()))  # cycle 1
        self._snapshot("tree-f", task="final")
        self._check(self._fix(2, "tree-f", name="final-python-coder.json", task="final"))

    def test_history_records_the_baseline(self):
        self._snapshot("tree-a")
        self._check(self._fix(2, "tree-a"))
        self.assertEqual(ledger.load_history(self.store)[-1]["baseline"], "tree-a")

    def test_a_pre_upgrade_record_without_baseline_still_loads(self):
        self._fix(2, None)
        records = ledger.load_records(self.store)
        self.assertTrue(records[0].ok, records[0].error)

    def test_an_empty_baseline_is_malformed_at_load(self):
        self._fix(2, "  ")
        self.assertFalse(ledger.load_records(self.store)[0].ok)


# --- CLI end-to-end (subprocess) ---

class TestCLI(LedgerTestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(LEDGER_PY), *args, "--store", str(self.store)],
            capture_output=True, text=True)

    def test_append_task_zero_exits_2(self):
        # _task_arg rejects 0 (must be a positive integer or 'final');
        # argparse.ArgumentTypeError maps to the standard argparse usage
        # exit code.
        result = self._run("append", "--type", "progress", "--task", "0", "--note", "x")
        self.assertEqual(result.returncode, 2)

    def test_append_task_negative_exits_2(self):
        result = self._run("append", "--type", "progress", "--task", "-1", "--note", "x")
        self.assertEqual(result.returncode, 2)

    def test_check_cli_exit_codes(self):
        good = _write(self.store, "task-1-python-coder.json", _coder())
        bad = _write(self.store, "task-2-python-coder.json", _coder(status="Blocked"))

        ok = subprocess.run([sys.executable, str(LEDGER_PY), "check", str(good)],
                             capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0)

        fail = subprocess.run([sys.executable, str(LEDGER_PY), "check", str(bad)],
                               capture_output=True, text=True)
        self.assertNotEqual(fail.returncode, 0)
        self.assertIn("status", fail.stderr)

    def test_check_cli_resolves_bare_filename_against_store_flag(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        result = subprocess.run(
            [sys.executable, str(LEDGER_PY), "check", "task-1-python-coder.json",
             "--store", str(self.store)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_append_and_resolve_roundtrip_via_store_flag(self):
        entry = {"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}
        _write(self.store, "task-1-python-coder.json", _coder(duplication_pending=[entry]))

        opened = self._run("open")
        # `open` prints each item's id so the orchestrator copies rather
        # than constructs it (spec Sec 6) — recover the real, content-
        # derived id from its output instead of assuming a fixed shape.
        match = re.search(
            r"\[(task-1-python-coder#duplication_pending\[[0-9a-f]{8}\])\]", opened.stdout)
        self.assertIsNotNone(match, opened.stdout)
        resolve_id = match.group(1)

        resolved = self._run("resolve", resolve_id, "--note", "hoisted")
        self.assertEqual(resolved.returncode, 0)

        opened_again = self._run("open")
        self.assertIn("No open items.", opened_again.stdout)

    def test_open_reports_no_open_items_on_empty_store(self):
        result = self._run("open")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No open items.", result.stdout)

    def test_store_dir_prints_resolved_store_path(self):
        result = self._run("store-dir")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(self.store.resolve()))

    def test_append_complete_and_completed_roundtrip(self):
        _completable(self.store, 5)
        appended = self._run("append", "--type", "complete", "--task", "5",
                              "--note", "shipped")
        self.assertEqual(appended.returncode, 0, appended.stderr)

        completed = self._run("completed")
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.splitlines(), ["5"])

    def test_completed_lists_nothing_when_no_task_is_complete(self):
        self._run("append", "--type", "progress", "--task", "1", "--note", "still going")
        result = self._run("completed")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_close_round_cli_prints_rounds_then_fails_past_the_cap(self):
        outputs = [self._run("close-round", "--expect", str(n), "--note", f"round {n}")
                   for n in range(1, ledger.CLOSE_ROUND_CAP + 2)]
        for n, result in enumerate(outputs[:-1], 1):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(n))
        # The CLI fills `head` from git (the test runs inside this repo).
        heads = [e["head"] for e in ledger.load_progress_log(self.store)]
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", h) for h in heads), heads)
        past_cap = outputs[-1]
        self.assertNotEqual(past_cap.returncode, 0)
        self.assertIn("escalate", past_cap.stderr)

    def test_read_renders_complete_entries_distinctly_from_progress(self):
        _completable(self.store, 5)
        self._run("append", "--type", "progress", "--task", "5", "--note", "working on it")
        self._run("append", "--type", "complete", "--task", "5", "--note", "shipped")
        result = self._run("read")
        self.assertEqual(result.returncode, 0)
        self.assertIn("working on it", result.stdout)
        self.assertIn("**COMPLETE**", result.stdout)
        self.assertIn("shipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
