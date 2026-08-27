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
        "concerns": [], "report": "",
    }
    data.update(overrides)
    return data


def _spec_reviewer(**overrides) -> dict:
    data = {
        "schema": 1, "agent": "spec-reviewer", "role": "spec-reviewer",
        "task": 1, "status": "compliant", "issues": [], "cannot_verify": [],
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
                "task": 1, "status": "issues", "findings": [], "lossiness": []})
        _write(self.store, "task-1-pytorch-quality-reviewer.json",
               {"schema": 1, "agent": "pytorch-quality-reviewer", "role": "quality-reviewer",
                "task": 1, "status": "issues", "findings": [], "lossiness": []})
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

    def test_non_object_progress_line_skipped_with_warning(self):
        self.store.mkdir(exist_ok=True)
        progress = self.store / ledger.PROGRESS_FILENAME
        progress.write_text(
            '{"type": "progress", "task": 1, "note": "ok"}\n["not", "an", "object"]\n',
            encoding="utf-8")
        with mock.patch("sys.stderr"):
            log = ledger.load_progress_log(self.store)  # must not raise
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["note"], "ok")

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
