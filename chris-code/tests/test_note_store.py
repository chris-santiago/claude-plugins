#!/usr/bin/env python3
"""
Tests for the orchestrator note store in ledger.py: the store lock, the
run scope, notes, delivery, the stage map, handles, and the run-state and
report views (spec .claude/output/specs/2026-10-30-note-store-design.md).

Run: python3 -m unittest discover -s chris-code/tests
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

SCRIPTS_DIR = (Path(__file__).resolve().parents[1]
               / "skills" / "subagent-driven-development" / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import ledger  # noqa: E402

LEDGER_PY = SCRIPTS_DIR / "ledger.py"


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ledger.ensure_store(Path(self._tmp.name) / "store")

    def _log(self) -> list[dict]:
        return ledger.load_progress_log(self.store)

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(LEDGER_PY), *args, "--store", str(self.store)],
                              capture_output=True, text=True)

    def _out(self, func, *args, **kwargs) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            func(*args, **kwargs)
        return buf.getvalue()

    def _note(self, kind: str, text: str, **kwargs) -> str:
        """File a note and return the id it printed."""
        return self._out(ledger.cmd_note, self.store, kind, text, **kwargs).strip()

    def _complete(self, task: int | str) -> None:
        self._completable(task)
        ledger.cmd_append(self.store, "complete", task, "shipped")

    def _completable(self, task: int | str) -> None:
        """A done triage entry and a passing gate, so completion turns only
        on the notes under test."""
        ledger.ensure_store(self.store)
        ledger._append_progress(self.store, {"type": "triage", "task": task, "kind": "done",
                                             "recheck": "none", "findings": []})
        prefix = ledger.scope_prefix(ledger.load_progress_log(self.store), task)
        (self.store / f"{prefix}-gate.json").write_text(json.dumps({
            "schema": 2, "agent": "ledger", "role": "gate", "task": task, "status": "pass",
            "tree": "t", "files": [], "commands": [], "findings": [], "recurring": [],
            "introduced_by_fix": []}), encoding="utf-8")

    def assertRefused(self, fragment: str, func, *args, **kwargs) -> None:
        def snapshot() -> dict:
            return {p.name: p.read_bytes() for p in self.store.iterdir()}
        before = snapshot()
        with self.assertRaises(ledger.RecordError) as ctx:
            self._out(func, *args, **kwargs)
        self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(snapshot(), before, "a refusal must write nothing")


# --- store lock (2026-10-30) ---

_APPENDER = """
import sys
sys.path.insert(0, {scripts!r})
import ledger
from pathlib import Path
store = Path({store!r})
for i in range({count}):
    ledger.cmd_append(store, "progress", 1, "writer {tag} line " + str(i) + " " + "x" * 3000)
"""


class TestStoreLock(StoreTestCase):
    def test_concurrent_writers_leave_only_whole_lines(self):
        procs = [subprocess.Popen([sys.executable, "-c", _APPENDER.format(
                    scripts=str(SCRIPTS_DIR), store=str(self.store), count=40, tag=tag)])
                 for tag in "abcd"]
        for proc in procs:
            self.assertEqual(proc.wait(), 0)
        log = self._log()  # raises on any torn or merged line
        self.assertEqual(len(log), 160)

    def test_concurrent_close_rounds_start_exactly_one_round(self):
        procs = [subprocess.Popen(
                    [sys.executable, str(LEDGER_PY), "close-round", "--expect", "1",
                     "--note", "close", "--store", str(self.store)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(6)]
        codes = [proc.wait() for proc in procs]
        for proc in procs:
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(codes.count(0), 1, codes)
        self.assertEqual(ledger.close_rounds(self._log()), 1)

    def test_clear_keeps_the_lock_file(self):
        ledger.cmd_append(self.store, "progress", 1, "x")
        ledger.cmd_clear(self.store)
        self.assertTrue((self.store / ledger.LOCK_FILENAME).exists())
        self.assertFalse((self.store / ledger.PROGRESS_FILENAME).exists())

    def test_read_only_commands_create_nothing(self):
        missing = Path(self._tmp.name) / "nowhere"
        for func in (ledger.cmd_open, ledger.cmd_read, ledger.cmd_run_state, ledger.cmd_report,
                     ledger.cmd_completed, ledger.cmd_stats):
            self._out(func, missing)
        self._out(ledger.cmd_notes, missing, 3)
        self.assertFalse(missing.exists())

    def test_the_first_append_seeds_the_store_and_later_writes_lock_it(self):
        fresh = Path(self._tmp.name) / "fresh"
        ledger.cmd_append(fresh, "progress", 1, "x")
        self.assertEqual((fresh / ".gitignore").read_text(), "*\n")
        ledger.cmd_append(fresh, "progress", 1, "y")
        self.assertTrue((fresh / ledger.LOCK_FILENAME).exists())

    def test_a_refusal_on_a_missing_store_creates_nothing(self):
        missing = Path(self._tmp.name) / "nowhere"
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_resolve(missing, "bogus", "x")
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_close_round(missing, "close", "abc", 2)
        with self.assertRaises(ledger.RecordError):
            ledger.cmd_note(missing, "task-note", "x")
        self.assertFalse(missing.exists())

    def test_clear_never_seeds_a_directory_that_is_not_a_store(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        (plain / "keep.txt").write_text("mine", encoding="utf-8")
        ledger.cmd_clear(plain)
        self.assertEqual(sorted(p.name for p in plain.iterdir()), ["keep.txt"])

    def test_concurrent_checks_leave_whole_history_lines(self):
        record = {"schema": 2, "agent": "python-coder", "role": "coder", "task": 1,
                  "status": "done", "cycle": 1, "model": "sonnet", "new_shared_symbols": [],
                  "duplication_pending": [], "concerns": ["x" * 3000]}
        path = self.store / "task-1-python-coder.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        script = (f"import sys; sys.path.insert(0, {str(SCRIPTS_DIR)!r}); import ledger\n"
                  f"for _ in range(30): ledger.cmd_check({str(path)!r})\n")
        procs = [subprocess.Popen([sys.executable, "-c", script]) for _ in range(4)]
        for proc in procs:
            self.assertEqual(proc.wait(), 0)
        lines = (self.store / ledger.HISTORY_FILENAME).read_text().splitlines()
        self.assertEqual(len(lines), 120)
        for line in lines:
            json.loads(line)  # raises on a torn or merged line


# --- the run scope for rulings (2026-10-30) ---

class TestRunScope(StoreTestCase):
    def test_progress_accepts_the_run_scope(self):
        ledger.cmd_append(self.store, "progress", "run", "user ruling: pause after this stage")
        self.assertEqual(self._log()[-1]["task"], "run")

    def test_complete_refuses_the_run_scope_and_appends_nothing(self):
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_append(self.store, "complete", "run", "done")
        self.assertIn("never completed", str(ctx.exception))
        self.assertEqual(self._log(), [])

    def test_cli_accepts_run_and_still_rejects_bad_task_values(self):
        self.assertEqual(self._cli("append", "--type", "progress", "--task", "run",
                                   "--note", "user ruling: x").returncode, 0)
        for bad in ("0", "-1", "foo"):
            result = self._cli("append", "--type", "progress", "--task", bad, "--note", "x")
            self.assertEqual(result.returncode, 2, bad)

    def test_read_renders_a_run_ruling(self):
        ledger.cmd_append(self.store, "progress", "run", "user ruling: pause")
        out = self._out(ledger.cmd_read, self.store)
        self.assertIn("- run: user ruling: pause", out)


# --- notes: filing, resolution, rendering (2026-10-30) ---

class TestFilingNotes(StoreTestCase):
    def test_each_kind_files_and_prints_its_id(self):
        cases = [("task-note", {"for_task": 3}), ("run-note", {}),
                 ("disclosure", {"owner": 3}), ("question", {"owner": "close"}),
                 ("follow-up", {}), ("disposition", {"source": 2}), ("checkpoint", {})]
        for kind, kwargs in cases:
            nid = self._note(kind, f"a {kind}", **kwargs)
            self.assertRegex(nid, rf"^note#{kind}\[[0-9a-f]{{8}}\]$")
        entries = ledger.notes_from_log(self._log())
        self.assertEqual([e["kind"] for e in entries], [k for k, _ in cases])
        self.assertTrue(all(e["at"].endswith("+00:00") for e in entries))

    def test_the_id_is_the_one_note_id_derives(self):
        nid = self._note("task-note", "carry the helper", for_task=4, source=2)
        self.assertEqual(nid, ledger.note_id("task-note", "carry the helper", 4, None, 2))
        entry = ledger.notes_from_log(self._log())[0]
        self.assertEqual((entry["for"], entry["from"]), (4, 2))
        self.assertNotIn("owner", entry)

    def test_flags_must_match_the_kind(self):
        self.assertRefused("needs --for", ledger.cmd_note, self.store, "task-note", "x")
        self.assertRefused("only for a task-note", ledger.cmd_note, self.store, "follow-up",
                           "x", for_task=2)
        self.assertRefused("needs --owner", ledger.cmd_note, self.store, "disclosure", "x")
        self.assertRefused("needs --owner", ledger.cmd_note, self.store, "question", "x")
        self.assertRefused("only for a disclosure or question", ledger.cmd_note, self.store,
                           "run-note", "x", owner=2)
        self.assertRefused("only for a disclosure or question", ledger.cmd_note, self.store,
                           "task-note", "x", for_task=2, owner=2)
        self.assertRefused("non-empty --text", ledger.cmd_note, self.store, "run-note", "  ")
        self.assertRefused("allowed set", ledger.cmd_note, self.store, "memo", "x")

    def test_a_completed_target_is_refused(self):
        self._complete(2)
        self.assertRefused("never be delivered", ledger.cmd_note, self.store, "task-note", "x",
                           for_task=2)
        self.assertRefused("--owner close", ledger.cmd_note, self.store, "disclosure", "x",
                           owner=2)
        self.assertRefused("--owner close", ledger.cmd_note, self.store, "question", "x",
                           owner=2)
        self._note("disclosure", "x", owner="close")  # the close can still own it

    def test_a_duplicate_is_refused_with_its_state(self):
        nid = self._note("follow-up", "same text")
        self.assertRefused("(open)", ledger.cmd_note, self.store, "follow-up", "same text")
        ledger.cmd_resolve(self.store, nid, "fixed in task 3")
        self.assertRefused("(resolved)", ledger.cmd_note, self.store, "follow-up", "same text")
        self._note("follow-up", "same text", source=4)  # different content, different note
        self._note("checkpoint", "paused")
        self.assertRefused("never open or resolved", ledger.cmd_note, self.store, "checkpoint",
                           "paused")
        self._note("task-note", "carry it", for_task=6)
        ledger.record_delivery(self.store, 6, [ledger.note_id("task-note", "carry it", 6)],
                               "brief")
        self._complete(6)
        self.assertRefused("never be delivered", ledger.cmd_note, self.store,
                           "task-note", "carry it", for_task=6)

    def test_cli_files_a_note_and_rejects_bad_flag_values(self):
        result = self._cli("note", "--kind", "task-note", "--text", "x", "--for", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("note#task-note["))
        self.assertEqual(self._cli("note", "--kind", "task-note", "--text", "x",
                                   "--for", "0").returncode, 2)
        self.assertEqual(self._cli("note", "--kind", "question", "--text", "x",
                                   "--owner", "later").returncode, 2)
        refused = self._cli("note", "--kind", "follow-up", "--text", "x", "--for", "3")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("only for a task-note", refused.stderr)


class TestResolvingNotes(StoreTestCase):
    def test_open_kinds_resolve_with_a_note(self):
        ids = [self._note("task-note", "a", for_task=3), self._note("run-note", "b"),
               self._note("follow-up", "c"), self._note("disclosure", "d", owner=3)]
        for nid in ids:
            ledger.cmd_resolve(self.store, nid, "settled")
        self.assertEqual(ledger.open_notes(self._log()), [])

    def test_resolution_text_is_required(self):
        nid = self._note("disclosure", "changelog line owed", owner="close")
        self.assertRefused("where it landed", ledger.cmd_resolve, self.store, nid, "")

    def test_a_question_resolves_only_with_a_ruling(self):
        nid = self._note("question", "bless the goldens?", owner=2)
        self.assertRefused("user ruling:", ledger.cmd_resolve, self.store, nid, "yes")
        ledger.cmd_resolve(self.store, nid, "User ruling: bless all four")
        self.assertEqual(ledger.open_notes(self._log()), [])

    def test_checkpoints_and_dispositions_are_never_resolved(self):
        for kind in ("checkpoint", "disposition"):
            nid = self._note(kind, f"a {kind}")
            self.assertRefused("never resolved", ledger.cmd_resolve, self.store, nid, "x")

    def test_a_task_note_closes_when_its_target_completes(self):
        nid = self._note("task-note", "a", for_task=3)
        self._log_delivery(3, [nid])
        self._complete(3)
        self.assertEqual(ledger.open_notes(self._log()), [])
        self.assertRefused("closed when task 3 completed", ledger.cmd_resolve, self.store,
                           nid, "x")

    def _log_delivery(self, task: int, ids: list[str]) -> None:
        with ledger.store_lock(self.store):
            ledger._append_jsonl(self.store / ledger.PROGRESS_FILENAME,
                                 {"type": "delivery", "task": task, "notes": ids, "via": "brief"})

    def test_unknown_and_resolved_ids_are_refused(self):
        nid = self._note("follow-up", "c")
        self.assertRefused("matches no filed note", ledger.cmd_resolve, self.store,
                           "note#follow-up[00000000]", "x")
        ledger.cmd_resolve(self.store, nid, "done")
        self.assertRefused("already resolved", ledger.cmd_resolve, self.store, nid, "again")

    def test_record_ids_list_open_notes_when_they_match_nothing(self):
        nid = self._note("follow-up", "c")
        self.assertRefused(nid, ledger.cmd_resolve, self.store, "task-1-x#cannot_verify[1]", "x")


# --- delivery, waivers and the delivery gates (2026-10-30) ---

class DeliveryTestCase(StoreTestCase):
    def _deliver(self, task: int, ids: list[str], via: str = "brief") -> None:
        ledger.record_delivery(self.store, task, ids, via)

    def _required(self, task: int) -> list[str]:
        return [n["id"] for n in ledger.required_notes(self._log(), task)]

    def _undelivered(self, task: int) -> list[str]:
        return [n["id"] for n in ledger.undelivered_notes(self._log(), task)]


class TestRequiredNotes(DeliveryTestCase):
    def test_a_task_requires_its_task_notes_run_notes_and_owned_disclosures(self):
        mine = self._note("task-note", "for 5", for_task=5)
        self._note("task-note", "for 6", for_task=6)
        rule = self._note("run-note", "never stash")
        owed = self._note("disclosure", "changelog", owner=5)
        self._note("disclosure", "spec", owner="close")
        self._note("question", "bless?", owner=5)
        self._note("follow-up", "later")
        self.assertEqual(self._required(5), [mine, rule, owed])

    def test_resolved_notes_are_not_required(self):
        rule = self._note("run-note", "never stash")
        ledger.cmd_resolve(self.store, rule, "retired")
        self.assertEqual(self._required(5), [])

    def test_a_completed_task_requires_nothing(self):
        self._complete(5)
        self._note("run-note", "filed later")
        self.assertEqual(self._required(5), [])

    def test_a_delivery_or_waiver_delivers(self):
        a = self._note("run-note", "a")
        b = self._note("run-note", "b")
        self._deliver(5, [a])
        self._out(ledger.cmd_notes, self.store, 5, waive=b, reason="the task touches no Python")
        self.assertEqual(self._undelivered(5), [])

    def test_a_note_filed_after_the_delivery_is_undelivered(self):
        a = self._note("task-note", "a", for_task=5)
        self._deliver(5, [a])
        late = self._note("task-note", "late", for_task=5)
        self.assertEqual(self._undelivered(5), [late])


class TestNotesCommand(DeliveryTestCase):
    def test_lists_required_notes_with_marks_and_owned_questions(self):
        a = self._note("task-note", "a", for_task=5)
        b = self._note("run-note", "b")
        q = self._note("question", "bless?", owner=5)
        self._deliver(5, [a])
        out = self._out(ledger.cmd_notes, self.store, 5)
        self.assertIn(f"[{a}] delivered", out)
        self.assertIn(f"[{b}] UNDELIVERED", out)
        self.assertIn(f"[{q}] for the user", out)

    def test_nothing_to_list(self):
        self.assertIn("No notes for task 5.", self._out(ledger.cmd_notes, self.store, 5))

    def test_deliver_records_exactly_the_required_ids(self):
        a = self._note("task-note", "a", for_task=5)
        b = self._note("run-note", "b")
        self._note("task-note", "other", for_task=6)
        self._out(ledger.cmd_notes, self.store, 5, deliver=True)
        entry = self._log()[-1]
        self.assertEqual((entry["type"], entry["via"], entry["notes"]),
                         ("delivery", "session", [a, b]))
        self._out(ledger.cmd_notes, self.store, 5, deliver=True)  # nothing new: still fine
        self.assertEqual(self._undelivered(5), [])

    def test_waivers_are_checked(self):
        a = self._note("run-note", "a")
        other = self._note("task-note", "x", for_task=6)
        self.assertRefused("not a note task 5 still needs", ledger.cmd_notes, self.store, 5,
                           waive=other, reason="n/a")
        self.assertRefused("needs --reason", ledger.cmd_notes, self.store, 5, waive=a,
                           reason="  ")
        self.assertRefused("needs --reason", ledger.cmd_notes, self.store, 5, waive=a)
        self.assertRefused("goes with --waive", ledger.cmd_notes, self.store, 5, reason="x")

    def test_cli_rejects_deliver_with_waive(self):
        a = self._note("run-note", "a")
        result = self._cli("notes", "--task", "5", "--deliver", "--waive", a)
        self.assertEqual(result.returncode, 2)


class TestCompletionGate(DeliveryTestCase):
    def test_an_undelivered_note_blocks_completion(self):
        a = self._note("task-note", "a", for_task=5)
        self.assertRefused(a, ledger.cmd_append, self.store, "complete", 5, "done")
        self._deliver(5, [a])
        self._complete(5)

    def test_a_run_note_blocks_every_task_in_flight_but_not_a_completed_one(self):
        for task in (5, 6):
            self._deliver(task, [])
        self._deliver(4, [])
        self._complete(4)
        rule = self._note("run-note", "rebuild the extension before testing")
        for task in (5, 6):
            self.assertRefused(rule, ledger.cmd_append, self.store, "complete", task, "done")
        self.assertEqual(self._required(4), [])

    def test_an_owned_disclosure_or_question_blocks_until_resolved(self):
        d = self._note("disclosure", "changelog", owner=7)
        q = self._note("question", "bless?", owner=7)
        self._deliver(7, [d])
        self.assertRefused(d, ledger.cmd_append, self.store, "complete", 7, "done")
        self.assertRefused(q, ledger.cmd_append, self.store, "complete", 7, "done")
        ledger.cmd_resolve(self.store, d, "CHANGELOG.md in abc1234")
        ledger.cmd_resolve(self.store, q, "user ruling: bless")
        self._complete(7)

    def test_a_superseded_task_note_never_blocks(self):
        a = self._note("task-note", "a", for_task=5)
        ledger.cmd_resolve(self.store, a, "superseded by the stage 2 rework")
        self._complete(5)

    def test_final_is_not_held_by_notes(self):
        self._note("run-note", "a")
        self._completable("final")
        ledger.cmd_append(self.store, "complete", "final", "whole change clean")


class TestCloseRoundGate(DeliveryTestCase):
    def test_open_disclosures_questions_and_stranded_task_notes_block_the_close(self):
        d = self._note("disclosure", "spec text", owner="close")
        q = self._note("question", "ship it?", owner="close")
        t = self._note("task-note", "for a task that never ran", for_task=9)
        for nid in (d, q, t):
            self.assertRefused(nid, ledger.cmd_close_round, self.store, "close", "abc", 1)
        ledger.cmd_resolve(self.store, d, "spec.md in abc1234")
        ledger.cmd_resolve(self.store, q, "user ruling: ship")
        ledger.cmd_resolve(self.store, t, "superseded: task 9 was dropped")
        self.assertEqual(self._out(ledger.cmd_close_round, self.store, "close", "abc", 1).strip(),
                         "1")

    def test_follow_ups_dispositions_and_run_notes_do_not_block_the_close(self):
        for kind in ("follow-up", "disposition", "run-note", "checkpoint"):
            self._note(kind, f"a {kind}")
        self._out(ledger.cmd_close_round, self.store, "close", "abc", 1)


class TestOpenListsNoteItems(DeliveryTestCase):
    def test_open_lists_undelivered_notes_for_tasks_in_flight_and_owned_notes(self):
        self._deliver(5, [])
        a = self._note("task-note", "a", for_task=5)
        future = self._note("task-note", "b", for_task=8)  # task 8 hasn't started
        d = self._note("disclosure", "changelog", owner="close")
        f = self._note("follow-up", "later")
        out = self._out(ledger.cmd_open, self.store)
        self.assertIn(f"[{a}] undelivered to task 5", out)
        self.assertIn(f"[{d}] disclosure owned by the close", out)
        self.assertNotIn(future, out)
        self.assertNotIn(f, out)

    def test_read_renders_deliveries_and_waivers(self):
        a = self._note("run-note", "a")
        b = self._note("run-note", "b")
        self._deliver(5, [a])
        self._out(ledger.cmd_notes, self.store, 5, waive=b, reason="no Python here")
        out = self._out(ledger.cmd_read, self.store)
        self.assertIn(f"task 5 received notes via brief: `{a}`", out)
        self.assertIn(f"task 5 waived `{b}`: no Python here", out)
        self.assertNotIn("unknown entry", out)


# --- stage map and handles (2026-10-30) ---

class TestStageMap(StoreTestCase):
    def test_records_a_normalized_footprint(self):
        ledger.cmd_stage(self.store, 3, 1, ["./src/a.py", "tests/../tests/test_a.py", "src/a.py"])
        entry = self._log()[-1]
        self.assertEqual((entry["task"], entry["stage"], entry["files"]),
                         (3, 1, ["src/a.py", "tests/test_a.py"]))

    def test_restaging_a_task_replaces_its_entry(self):
        ledger.cmd_stage(self.store, 3, 1, ["a.py"])
        ledger.cmd_stage(self.store, 3, 2, ["a.py", "b.py"])
        self.assertEqual(ledger.stage_map(self._log())[3]["stage"], 2)
        ledger.cmd_stage(self.store, 4, 1, ["a.py"])  # task 3 left stage 1

    def test_an_overlap_in_one_stage_is_refused(self):
        ledger.cmd_stage(self.store, 3, 1, ["src/a.py", "src/b.py"])
        self.assertRefused("task 3", ledger.cmd_stage, self.store, 4, 1, ["./src/b.py"])
        self.assertRefused("['src/b.py']", ledger.cmd_stage, self.store, 4, 1, ["src/b.py"])

    def test_overlap_is_allowed_across_stages_or_after_completion(self):
        ledger.cmd_stage(self.store, 3, 1, ["a.py"])
        ledger.cmd_stage(self.store, 4, 2, ["a.py"])
        self._complete(3)
        ledger.cmd_stage(self.store, 5, 1, ["a.py"])

    def test_bad_footprints_are_refused(self):
        self.assertRefused("expected the paths", ledger.cmd_stage, self.store, 3, 1, ["  "])
        self.assertRefused("expected the paths", ledger.cmd_stage, self.store, 3, 1, ["./"])
        no_files = self._cli("stage", "--task", "3", "--stage", "1", "--files")
        stage_zero = self._cli("stage", "--task", "3", "--stage", "0", "--files", "a.py")
        self.assertEqual((no_files.returncode, stage_zero.returncode), (2, 2))


class TestHandles(StoreTestCase):
    def test_latest_handle_per_task_and_role_wins(self):
        ledger.cmd_handle(self.store, 3, "python-coder", "a1")
        ledger.cmd_handle(self.store, 3, "python-coder", "a2")
        ledger.cmd_handle(self.store, "final", "rust-coder", "b1")
        handles = ledger.latest_handles(self._log())
        self.assertEqual(handles[(3, "python-coder")]["agent"], "a2")
        self.assertEqual(handles[("final", "rust-coder")]["agent"], "b1")

    def test_empty_role_or_agent_is_refused(self):
        self.assertRefused("non-empty", ledger.cmd_handle, self.store, 3, " ", "a1")
        self.assertRefused("non-empty", ledger.cmd_handle, self.store, 3, "python-coder", "")

    def test_cli_runs_stage_handle_and_notes(self):
        ok = [self._cli("stage", "--task", "3", "--stage", "1", "--files", "a.py", "b.py"),
              self._cli("handle", "--task", "3", "--role", "python-coder", "--agent", "a1"),
              self._cli("note", "--kind", "run-note", "--text", "rebuild first")]
        for result in ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        rule = ok[-1].stdout.strip()
        delivered = self._cli("notes", "--task", "3", "--deliver")
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        self.assertIn(f"[{rule}] delivered", delivered.stdout)
        self._cli("note", "--kind", "run-note", "--text", "second rule")
        second = ledger.notes_from_log(self._log())[-1]["id"]
        waived = self._cli("notes", "--task", "3", "--waive", second, "--reason", "no ext")
        self.assertEqual(waived.returncode, 0, waived.stderr)
        self.assertEqual(ledger.undelivered_notes(self._log(), 3), [])
        self.assertEqual(ledger.latest_handles(self._log())[(3, "python-coder")]["agent"], "a1")
        self.assertEqual(ledger.stage_map(self._log())[3]["files"], ["a.py", "b.py"])

    def test_read_renders_stages_and_handles(self):
        ledger.cmd_stage(self.store, 3, 1, ["a.py"])
        ledger.cmd_handle(self.store, 3, "python-coder", "a1")
        out = self._out(ledger.cmd_read, self.store)
        self.assertIn("task 3 in stage 1: a.py", out)
        self.assertIn("task 3 python-coder is agent `a1`", out)
        self.assertNotIn("unknown entry", out)


# --- run-state, report and the guarded clear (2026-10-30) ---

def _write_coder(store: Path, task: int, concerns: list[str]) -> None:
    record = {"schema": 2, "agent": "python-coder", "role": "coder", "task": task,
              "status": "done_with_concerns", "cycle": 1, "model": "sonnet",
              "new_shared_symbols": [], "duplication_pending": [], "concerns": concerns}
    (store / f"task-{task}-python-coder.json").write_text(json.dumps(record), encoding="utf-8")


class TestRunState(DeliveryTestCase):
    def _state(self) -> str:
        return self._out(ledger.cmd_run_state, self.store)

    def test_an_empty_store_renders_every_section(self):
        out = self._state()
        for heading in ("## Stages", "## Rounds", "## Notes owed",
                        "## Open disclosures and questions", "## Blocking items",
                        "## Agent handles", "## Latest checkpoint"):
            self.assertIn(heading, out)
        self.assertIn("(no stage map recorded)", out)
        self.assertLess(out.index("## Stages"), out.index("## Latest checkpoint"))

    def test_a_mid_run_store(self):
        ledger.cmd_stage(self.store, 1, 1, ["a.py"])
        ledger.cmd_stage(self.store, 2, 1, ["b.py"])
        ledger.cmd_stage(self.store, 3, 2, ["a.py"])
        self._deliver(1, [])
        self._complete(1)
        self._deliver(2, [])
        self._deliver(7, [])  # in flight but never staged
        late = self._note("run-note", "rebuild before testing")
        future = self._note("task-note", "carry the helper", for_task=3)
        q = self._note("question", "bless the goldens?", owner="close")
        ledger.cmd_handle(self.store, 1, "python-coder", "done-agent")
        ledger.cmd_handle(self.store, 2, "python-coder", "live-agent")
        self._note("checkpoint", "older checkpoint")
        self._note("checkpoint", "paused after stage 1")
        out = self._state()
        self.assertIn("task 1 (complete): a.py", out)
        self.assertIn("task 2 (in flight): b.py", out)
        self.assertIn("task 3 (not started): a.py", out)
        self.assertIn("## Unstaged tasks\n- task 7 (in flight)", out)
        self.assertIn("- task 2: (no triage yet)", out)
        self.assertIn(f"- task 2: [{late}]", out)
        self.assertIn(f"- task 3 (not started): [{future}]", out)
        self.assertIn(f"- [{q}] question owned by the close", out)
        self.assertIn("live-agent", out)
        self.assertNotIn("done-agent", out)
        self.assertIn("paused after stage 1", out)
        self.assertNotIn("older checkpoint", out)

    def test_a_finished_store(self):
        ledger.cmd_stage(self.store, 1, 1, ["a.py"])
        self._deliver(1, [])
        self._complete(1)
        out = self._state()
        self.assertIn("task 1 (complete)", out)
        self.assertIn("(no task in flight)", out)
        self.assertIn("0 open", out)


class TestReport(DeliveryTestCase):
    def test_lists_everything_the_completion_report_needs(self):
        ledger.cmd_append(self.store, "progress", 4, "User ruling: keep the digits")
        ledger.cmd_append(self.store, "progress", "run", "user ruling: pause after stage 2")
        ledger.cmd_append(self.store, "progress", 4, "not a ruling")
        open_f = self._note("follow-up", "split the layout module", source=4)
        done_f = self._note("follow-up", "typing gap in configure")
        ledger.cmd_resolve(self.store, done_f, "fixed in task 6")
        _write_coder(self.store, 4, ["Unlisted case: empty frame refuses", "root cause: src/x.py:1 x"])
        disp = self._note("disposition", "took option A on a small call", source=4)
        rule = self._note("run-note", "rebuild first")
        self._deliver(5, [])
        self._out(ledger.cmd_notes, self.store, 5, waive=rule, reason="no extension")
        landed = self._note("disclosure", "changelog line", owner="close")
        ledger.cmd_resolve(self.store, landed, "CHANGELOG.md in abc1234")
        owed = self._note("disclosure", "spec amendment", owner="close")
        q = self._note("question", "bless?", owner="close")
        ledger.cmd_resolve(self.store, q, "user ruling: bless all four")
        out = self._out(ledger.cmd_report, self.store)
        self.assertIn("- task 4: User ruling: keep the digits", out)
        self.assertIn("- run: user ruling: pause after stage 2", out)
        self.assertIn(f"- `{q}`: user ruling: bless all four", out)
        self.assertNotIn("not a ruling", out)
        self.assertIn(f"[{open_f}] follow-up, from task 4: split the layout module", out)
        self.assertIn("Unlisted case: empty frame refuses (task-4-python-coder)", out)
        self.assertNotIn("root cause: src/x.py:1 x", out)
        self.assertIn(f"[{done_f}] typing gap in configure: fixed in task 6", out)
        self.assertIn(f"[{disp}] disposition, from task 4", out)
        self.assertIn(f"task 5 waived `{rule}`: no extension", out)
        self.assertIn(f"[{landed}] disclosure owned by the close: changelog line: CHANGELOG.md", out)
        self.assertIn(f"[{owed}] OPEN disclosure", out)


class TestCloseBatch(DeliveryTestCase):
    """Follow-ups carry the rule they fall under; the report groups them by
    rule and offers one batch remediation over them."""

    def test_a_follow_up_keeps_its_rule_without_changing_its_id(self):
        with_rule = self._out(ledger.cmd_note, self.store, "follow-up", "pad check at c.py:4",
                              rule="padding is validated").strip()
        entry = next(n for n in ledger.notes_from_log(ledger.load_progress_log(self.store))
                     if n["id"] == with_rule)
        self.assertEqual(entry["rule"], "padding is validated")
        self.assertEqual(with_rule, ledger.note_id("follow-up", "pad check at c.py:4"))

    def test_a_rule_on_another_kind_or_a_blank_rule_is_refused(self):
        self.assertRefused("--rule", ledger.cmd_note, self.store, "task-note", "x",
                           for_task=3, rule="r")
        self.assertRefused("--rule", ledger.cmd_note, self.store, "follow-up", "x", rule="  ")

    def test_the_report_groups_open_follow_ups_by_rule_and_offers_one_batch(self):
        for text, rule in (("a.py:1", "size is positive"), ("b.py:2", "size is positive"),
                           ("c.py:3", "names are nouns"), ("free-form", None)):
            self._out(ledger.cmd_note, self.store, "follow-up", text, rule=rule)
        settled = self._note("follow-up", "already done")
        ledger.cmd_resolve(self.store, settled, "fixed in task 2")
        out = self._out(ledger.cmd_report, self.store)
        body = out.split("## Follow-ups")[1].split("### Unlisted")[0]
        headings = [line for line in body.splitlines() if line.startswith("### ")]
        self.assertEqual(headings, ["### names are nouns", "### size is positive", "### (no rule)"])
        self.assertEqual(body.count("Batch Path"), 1)
        self.assertIn(f"[{settled}] already done: fixed in task 2", out)

    def test_no_open_follow_up_means_no_batch_offer(self):
        self.assertNotIn("Batch Path", self._out(ledger.cmd_report, self.store))


class TestGuardedClear(StoreTestCase):
    def test_open_follow_ups_disclosures_or_questions_block_clear(self):
        for kind, kwargs in (("follow-up", {}), ("disclosure", {"owner": "close"}),
                             ("question", {"owner": "close"})):
            with self.subTest(kind=kind):
                nid = self._note(kind, f"a {kind}", **kwargs)
                with self.assertRaises(ledger.RecordError) as ctx:
                    ledger.cmd_clear(self.store)
                self.assertIn(nid, str(ctx.exception))
                self.assertTrue((self.store / ledger.PROGRESS_FILENAME).exists())
                ledger.cmd_clear(self.store, discard_open=True)
                self.assertFalse((self.store / ledger.PROGRESS_FILENAME).exists())
                self.assertTrue((self.store / ledger.LOCK_FILENAME).exists())

    def test_settled_or_non_blocking_notes_do_not_block_clear(self):
        nid = self._note("follow-up", "x")
        ledger.cmd_resolve(self.store, nid, "reported in the PR")
        for kind in ("run-note", "disposition", "checkpoint"):
            self._note(kind, f"a {kind}")
        ledger.cmd_clear(self.store)
        self.assertFalse((self.store / ledger.PROGRESS_FILENAME).exists())

    def test_a_malformed_log_needs_discard_open(self):
        (self.store / ledger.PROGRESS_FILENAME).write_text("not json\n", encoding="utf-8")
        with self.assertRaises(ledger.RecordError) as ctx:
            ledger.cmd_clear(self.store)
        self.assertIn("--discard-open", str(ctx.exception))
        ledger.cmd_clear(self.store, discard_open=True)
        self.assertFalse((self.store / ledger.PROGRESS_FILENAME).exists())

    def test_cli_wires_the_views_and_discard_open(self):
        self._note("follow-up", "x")
        for command in ("run-state", "report"):
            self.assertEqual(self._cli(command).returncode, 0, command)
        self.assertEqual(self._cli("clear").returncode, 1)
        self.assertEqual(self._cli("clear", "--discard-open").returncode, 0)


class TestRenderingNotes(StoreTestCase):
    def test_read_renders_every_kind_and_note_resolutions(self):
        nid = self._note("task-note", "carry it", for_task=3, source=1)
        self._note("disclosure", "changelog", owner="close")
        self._note("checkpoint", "paused after stage 2")
        ledger.cmd_resolve(self.store, nid, "superseded")
        out = self._out(ledger.cmd_read, self.store)
        self.assertIn(f"`{nid}` task-note for task 3, from task 1: carry it", out)
        self.assertIn("disclosure owned by the close: changelog", out)
        self.assertIn("checkpoint: paused after stage 2", out)
        self.assertIn(f"resolves `{nid}`: superseded", out)
        self.assertNotIn("unknown entry", out)


if __name__ == "__main__":
    unittest.main()
