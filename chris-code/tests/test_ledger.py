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
        "schema": 1, "agent": "python-coder", "role": "coder", "task": 1,
        "status": "done", "changed_files": [], "tests": {},
        "new_shared_symbols": [], "duplication_pending": [],
        "concerns": [], "report": "", "cycle": 1,
    }
    data.update(overrides)
    return data


def _spec_reviewer(**overrides) -> dict:
    data = {
        "schema": 1, "agent": "spec-reviewer", "role": "spec-reviewer",
        "task": 1, "status": "compliant", "issues": [], "cannot_verify": [],
        "recurring": [], "introduced_by_fix": [],
    }
    data.update(overrides)
    return data


def _review_lite(**overrides) -> dict:
    data = {
        "schema": 1, "agent": "python-review-lite", "role": "review-lite",
        "task": 1, "status": "clean", "cycle": 1, "findings": [],
        "linter": {"ran": True, "name": "ruff", "passed": True},
        "verdict_path": "",
    }
    data.update(overrides)
    return data


def _write(store: Path, name: str, data: dict) -> Path:
    path = store / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _entry_id(stem: str, field_name: str, entry: dict) -> str:
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
        quality = {"schema": 1, "agent": "python-quality-reviewer",
                   "role": "quality-reviewer", "task": 1, "status": "approved",
                   "findings": [], "lossiness": [], "recurring": [],
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

    def test_finished_fix_with_empty_hunk_map_raises(self):
        # A finished fix changed something; an empty map hides every hunk.
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.validate_record(_coder(cycle=2, **self._fix(hunk_map=[])))
        self.assertIn("hunk_map", str(ctx.exception))

    def test_introduced_by_fix_never_becomes_an_open_item(self):
        # Like recurring, it's a failed-fix signal riding on findings,
        # not separate work.
        record = _spec_reviewer(
            status="issues",
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
        quality = {"schema": 1, "agent": "python-quality-reviewer",
                   "role": "quality-reviewer", "task": 1, "status": "approved",
                   "findings": [], "lossiness": [], "recurring": [], "introduced_by_fix": []}
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
            status="issues",
            recurring=[{"site": "a.py:10", "why": "same class as cycle 1"}])
        _write(self.store, "task-1-spec-reviewer.json", record)
        items = ledger.compute_open_items(ledger.load_records(self.store), set())
        self.assertEqual([i.kind for i in items], ["status"])


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
        _write(self.store, "task-1-bad.json", {"schema": 1})
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
            status="issues", cannot_verify=[entry_1, entry_2]))
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
            status="issues",
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
        data = _spec_reviewer(status="issues", cannot_verify=[])
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
               {"schema": 1, "agent": "python-quality-reviewer", "role": "quality-reviewer",
                "task": 1, "status": "issues", "findings": [], "lossiness": [],
                "recurring": [], "introduced_by_fix": []})
        _write(self.store, "task-1-pytorch-quality-reviewer.json",
               {"schema": 1, "agent": "pytorch-quality-reviewer", "role": "quality-reviewer",
                "task": 1, "status": "issues", "findings": [], "lossiness": [],
                "recurring": [], "introduced_by_fix": []})
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
        ledger.cmd_append(self.store, "complete", 5, "shipped")
        log = ledger.load_progress_log(self.store)
        self.assertEqual(log, [{"type": "complete", "task": 5, "note": "shipped"}])
        # append routes creation through ensure_store, so a store born from
        # an append (not store-dir) is still self-ignoring.
        self.assertEqual((self.store / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_cmd_completed_prints_one_task_id_per_line(self):
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
        self.assertEqual(ledger.RESOLVABLE_KINDS, frozenset(ledger._FIELD_DESCRIBERS))


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

    def test_fix_count_counts_only_non_trivial_snapshots_for_the_task(self):
        # The escalation cap is two non-trivial fix attempts; trivial fixes,
        # labels bounces and reviewer re-dispatches take no flagged snapshot.
        store = self.repo / ".sdd"
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(store, 4, "pre-fix c2", "t1", non_trivial=True)
            ledger.cmd_snapshot(store, 4, "pre-fix c3", "t2")
            ledger.cmd_snapshot(store, 5, "pre-fix c2", "t3", non_trivial=True)
            ledger.cmd_snapshot(store, 4, "pre-fix c4", "t4", non_trivial=True)
        log = ledger.load_progress_log(store)
        self.assertEqual(ledger.non_trivial_fix_count(log, 4), 2)
        self.assertEqual(ledger.non_trivial_fix_count(log, 6), 0)

    def test_fix_count_for_final_restarts_after_a_close_round(self):
        # Round 2's whole-change gate (final-r2-* records) must not inherit
        # round 1's non-trivial fixes, just as its records don't.
        store = self.repo / ".sdd"
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.cmd_snapshot(store, "final", "pre-fix c2", "t1", non_trivial=True)
            ledger.cmd_snapshot(store, "final", "pre-fix c3", "t2", non_trivial=True)
            ledger.cmd_close_round(store, "round 1", "abc", 1)
            ledger.cmd_snapshot(store, "final", "pre-fix c2", "t3", non_trivial=True)
            ledger.cmd_snapshot(store, 7, "pre-fix c2", "t4", non_trivial=True)
        log = ledger.load_progress_log(store)
        self.assertEqual(ledger.non_trivial_fix_count(log, "final"), 1)
        self.assertEqual(ledger.non_trivial_fix_count(log, 7), 1)

    def test_cli_fix_count_prints_the_count(self):
        run = lambda *a: subprocess.run(  # noqa: E731
            [sys.executable, str(LEDGER_PY), *a, "--store", str(self.repo / ".sdd")],
            cwd=self.repo, capture_output=True, text=True)
        snap = run("snapshot", "--task", "2", "--label", "pre-fix c2", "--non-trivial")
        self.assertEqual(snap.returncode, 0, snap.stderr)
        count = run("fix-count", "--task", "2")
        self.assertEqual((count.returncode, count.stdout.strip()), (0, "1"), count.stderr)

    def test_cmd_snapshot_records_a_typed_entry_and_prints_the_tree(self):
        store = self.repo / ".sdd"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.cmd_snapshot(store, 4, "pre-fix c2", "deadbeef")
        self.assertEqual(buf.getvalue().strip(), "deadbeef")
        self.assertEqual(ledger.load_progress_log(store),
                         [{"type": "snapshot", "task": 4, "label": "pre-fix c2",
                           "tree": "deadbeef"}])


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
            issues=[{"kind": "missing", "file": "a.py", "line": 1, "claim": "x"}],
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
        issue = {"kind": "missing", "file": "a.py", "line": 1, "claim": "x"}
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
            issues=[{"kind": "regression", "file": "a.py", "line": 1, "claim": "x"}],
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
        self._run("append", "--type", "progress", "--task", "5", "--note", "working on it")
        self._run("append", "--type", "complete", "--task", "5", "--note", "shipped")
        result = self._run("read")
        self.assertEqual(result.returncode, 0)
        self.assertIn("working on it", result.stdout)
        self.assertIn("**COMPLETE**", result.stdout)
        self.assertIn("shipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
