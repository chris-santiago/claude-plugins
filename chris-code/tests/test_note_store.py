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

    def _complete(self, task: int) -> None:
        ledger.cmd_append(self.store, "complete", task, "shipped")

    def assertRefused(self, fragment: str, func, *args, **kwargs) -> None:
        before = len(self._log())
        with self.assertRaises(ledger.RecordError) as ctx:
            self._out(func, *args, **kwargs)
        self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(len(self._log()), before, "a refusal must append nothing")


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

    def test_read_only_commands_take_no_lock(self):
        missing = Path(self._tmp.name) / "nowhere"
        self._out(ledger.cmd_open, missing)
        self._out(ledger.cmd_read, missing)
        self.assertFalse(missing.exists())

    def test_lock_file_is_created_on_first_write(self):
        fresh = Path(self._tmp.name) / "fresh"
        ledger.cmd_append(fresh, "progress", 1, "x")
        self.assertTrue((fresh / ledger.LOCK_FILENAME).exists())
        self.assertEqual((fresh / ".gitignore").read_text(), "*\n")


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
        self.assertRefused("already open", ledger.cmd_note, self.store, "follow-up", "same text")
        ledger.cmd_resolve(self.store, nid, "fixed in task 3")
        self.assertRefused("(resolved)", ledger.cmd_note, self.store, "follow-up", "same text")
        self._note("follow-up", "same text", source=4)  # different content, different note

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
