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


if __name__ == "__main__":
    unittest.main()
