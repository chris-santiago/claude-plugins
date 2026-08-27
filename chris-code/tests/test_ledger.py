#!/usr/bin/env python3
"""
Tests for ledger.py (spec Sec 9 acceptance criteria 3-7, plus one test per
failure case from the first build's five adversarial review rounds).

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
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


def _write(store: Path, name: str, data: dict) -> Path:
    path = store / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


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
        # Fix 1: an unhashable role (e.g. a list) must not crash the
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
        # Finding 1: a non-dict new_shared_symbols entry used to be
        # silently dropped by list_shapes; it must now fail loudly instead.
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
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]))
        records = ledger.load_records(self.store)
        items = ledger.compute_open_items(records, resolved_ids=set())
        self.assertEqual([i.id for i in items], ["task-1-python-coder#duplication_pending[0]"])

        resolved = {"task-1-python-coder#duplication_pending[0]"}
        items = ledger.compute_open_items(records, resolved)
        self.assertEqual(items, [])

    def test_cannot_verify_entries_open_until_each_resolved(self):
        # Acceptance criterion 4.
        _write(self.store, "task-1-spec-reviewer.json", _spec_reviewer(
            status="issues",
            cannot_verify=[
                {"requirement": "r1", "why": "w1", "should_check": "sc1"},
                {"requirement": "r2", "why": "w2", "should_check": "sc2"},
            ]))
        records = ledger.load_records(self.store)
        ids = {i.id for i in ledger.compute_open_items(records, resolved_ids=set())
               if i.kind == "cannot_verify"}
        self.assertEqual(ids, {"task-1-spec-reviewer#cannot_verify[0]",
                                "task-1-spec-reviewer#cannot_verify[1]"})

        remaining = {i.id for i in ledger.compute_open_items(
            records, resolved_ids={"task-1-spec-reviewer#cannot_verify[0]"})
            if i.kind == "cannot_verify"}
        self.assertEqual(remaining, {"task-1-spec-reviewer#cannot_verify[1]"})

    def test_cannot_verify_summary_includes_should_check(self):
        # Finding 3: should_check was omitted from cannot_verify summaries.
        _write(self.store, "task-1-spec-reviewer.json", _spec_reviewer(
            status="issues",
            cannot_verify=[{"requirement": "r1", "why": "w1", "should_check": "run the tests"}]))
        [item] = [i for i in ledger.compute_open_items(ledger.load_records(self.store),
                                                         resolved_ids=set())
                  if i.kind == "cannot_verify"]
        self.assertIn("run the tests", item.summary)

    def test_malformed_record_appears_open_query_never_crashes(self):
        _write(self.store, "task-1-python-coder.json", _coder())
        (self.store / "task-2-bad.json").write_text("not json", encoding="utf-8")
        items = ledger.compute_open_items(ledger.load_records(self.store), resolved_ids=set())
        self.assertEqual([i.kind for i in items], ["malformed"])

    def test_status_and_malformed_resolutions_do_not_suppress(self):
        # Finding 2: whole-record items (status, malformed) are not
        # resolvable; a resolution against #status/#malformed must not
        # hide a later, different problem recorded at the same stem.
        _write(self.store, "task-1-python-coder.json", _coder(status="blocked"))
        (self.store / "task-2-bad.json").write_text("not json", encoding="utf-8")
        records = ledger.load_records(self.store)
        resolved = {"task-1-python-coder#status", "task-2-bad#malformed"}
        items = ledger.compute_open_items(records, resolved)
        kinds = {i.kind for i in items}
        self.assertEqual(kinds, {"status", "malformed"})

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
        # Fix (spec review of Task 1'): per-record isolation must cover
        # open-item *construction*, not just load-time validation.
        # sites=[1, 2] passes validate_record (an informational sub-field)
        # but crashes str.join inside _describe_duplication. That must
        # become one loud item naming the offending file, not a bare
        # TypeError that kills every other record's items too.
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
        # Finding 1: previously list_shapes silently isinstance-continued
        # past a non-dict entry. Now the whole record is malformed (loud),
        # visible as an open item, and contributes no shapes.
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
        # Finding 4: appending to a file whose last line lacks a trailing
        # newline must not merge with that line.
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

    def test_resolved_ids_ignores_non_string_resolves(self):
        log = [{"type": "resolution", "resolves": ["not", "a", "string"]}]
        self.assertEqual(ledger.resolved_ids_from_log(log), set())


# --- resolve (write path) ---

class TestCmdResolve(LedgerTestCase):
    def test_succeeds_for_currently_open_item(self):
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]))
        ledger.cmd_resolve(self.store, "task-1-python-coder#duplication_pending[0]", "note")
        log = ledger.load_progress_log(self.store)
        self.assertEqual(len(log), 1)

    def test_unknown_id_raises_naming_currently_open_resolvable_ids(self):
        # Ruling: a resolve matching nothing is not a silent no-op.
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]))
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, "task-1-python-coder#duplication_pending[9]", "")
        message = str(ctx.exception)
        self.assertIn("matches no open resolvable item", message)
        self.assertIn("task-1-python-coder#duplication_pending[0]", message)
        # A never-was-open id gets no whole-record explanation — that
        # suffix is reserved for ids that are real but non-resolvable.
        self.assertNotIn("not resolvable", message)

    def test_non_resolvable_kind_id_raises_naming_whole_record_rule(self):
        # #status is a whole-record item — never resolvable, even though
        # it's a real, currently-open id. Polish fix: the error must name
        # the rule so an orchestrator pasting this id straight from `open`
        # learns why it doesn't work, instead of just "not found".
        _write(self.store, "task-1-python-coder.json", _coder(status="blocked"))
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, "task-1-python-coder#status", "")
        message = str(ctx.exception)
        self.assertIn("matches no open resolvable item", message)
        self.assertIn("not resolvable", message)
        self.assertIn("clear when the record is rewritten", message)

    def test_already_resolved_raises_naming_prior_note(self):
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]))
        ledger.cmd_resolve(self.store, "task-1-python-coder#duplication_pending[0]", "first note")

        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_resolve(self.store, "task-1-python-coder#duplication_pending[0]",
                                "second note")
        message = str(ctx.exception)
        self.assertIn("already resolved", message)
        self.assertIn("first note", message)


# --- clear ---

class TestClear(LedgerTestCase):
    def test_clear_deletes_by_naming_convention_leaves_unrelated_files(self):
        # Finding 5 (clear used to delete any *.json unconditionally) plus
        # the follow-up ruling: clear is now a deterministic naming-
        # convention match (task-*-* / final-*), independent of content
        # validity — a malformed record-attempt is clearable, an unrelated
        # notes.json is not.
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
        # Fix 1: `check` must never traceback. A record with an unhashable
        # role (e.g. a list, valid JSON but the wrong shape) used to crash
        # the `role not in VALID_ROLES` membership test with a bare
        # TypeError instead of a corrective RecordError.
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


# --- get_store_dir ---

class TestGetStoreDir(unittest.TestCase):
    def test_override_bypasses_git(self):
        with mock.patch("subprocess.check_output") as check_output:
            result = ledger.get_store_dir("/some/explicit/dir")
        check_output.assert_not_called()
        self.assertEqual(result, Path("/some/explicit/dir").resolve())

    def test_no_override_outside_git_raises_runtime_error(self):
        # Library entry points raise instead of calling sys.exit, so
        # task_brief.py (or a test) can catch this itself.
        with mock.patch("subprocess.check_output", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError):
                ledger.get_store_dir()


# --- CLI end-to-end (subprocess) ---

class TestCLI(LedgerTestCase):
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(LEDGER_PY), *args, "--store", str(self.store)],
            capture_output=True, text=True)

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

    def test_append_and_resolve_roundtrip_via_store_flag(self):
        _write(self.store, "task-1-python-coder.json", _coder(
            duplication_pending=[{"sites": ["a.py:1"], "wants_owner": "b.py", "why": "x"}]))

        opened = self._run("open")
        self.assertIn("duplication_pending[0]", opened.stdout)

        resolved = self._run("resolve", "task-1-python-coder#duplication_pending[0]",
                              "--note", "hoisted")
        self.assertEqual(resolved.returncode, 0)

        opened_again = self._run("open")
        self.assertIn("No open items.", opened_again.stdout)

    def test_open_reports_no_open_items_on_empty_store(self):
        result = self._run("open")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No open items.", result.stdout)


if __name__ == "__main__":
    unittest.main()
