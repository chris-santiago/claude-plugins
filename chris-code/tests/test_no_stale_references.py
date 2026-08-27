#!/usr/bin/env python3
"""
Regression guard for spec Sec 9 acceptance criterion 9: no lingering
reference anywhere under chris-code/ to the two retired bash scripts this
layer replaced outright (spec Sec 7: "removed, not shimmed") with
ledger.py and task_brief.py.

The two retired paths are assembled from parts below (never written out
as a contiguous string in this file) so this guard's own source never
trips the exact acceptance-check grep it exists to keep green.

Two mentions are intentionally excused as documented history, not a live
reference an agent or skill might still follow: CHANGELOG.md's annotated
parenthetical noting the rename, and task_brief.py's own docstring notes
recalling the bash predecessor it replaced. Each exclusion is line-scoped:
the excusing phrase ("since renamed to", "retired bash") must appear on
the SAME line as the mention, not merely somewhere in the file — so a
future reflow that separates a retired-script mention from its excusing
phrase (e.g. CHANGELOG.md's parenthetical wrapping onto its own line, or
task_brief.py's docstring being rewrapped) trips this guard instead of
silently staying excused. This test's own source is excluded from the
scan for the same reason — defining the guard requires naming what it
guards against.

Loud-failure note: an empty scan (e.g. CHRIS_CODE_DIR renamed or moved so
the walk silently covers nothing) is exactly the failure mode this guard
must not tolerate, so it raises before trusting an empty offender list —
a real RuntimeError, not a bare `assert`, so `python -O` stripping assert
statements can never silence it.

Self-test note: the main scan's exclusion logic (_is_excused) short-
circuits before a line ever reaches STALE_PATTERNS, so a broken bare
`task-brief` pattern (a typo'd regex) would never be caught by the clean-
scan test alone — the excused line is skipped either way. And the
retired-progress path appears nowhere contiguously by design, so nothing
in the real tree can catch a typo in its own construction either. Both
gaps get a dedicated positive test below, each written independently of
the pattern/constant it's checking, so one typo can't satisfy both.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

CHRIS_CODE_DIR = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

CHANGELOG_PATH = CHRIS_CODE_DIR / "CHANGELOG.md"
TASK_BRIEF_SCRIPT_PATH = (
    CHRIS_CODE_DIR / "skills" / "subagent-driven-development" / "scripts" / "task_brief.py"
)

_SCRIPTS_DIR_NAME = "scripts"
_RETIRED_PROGRESS_SCRIPT = _SCRIPTS_DIR_NAME + "/" + "progress"
_RETIRED_TASK_BRIEF_SCRIPT = _SCRIPTS_DIR_NAME + "/" + "task-brief"

PROGRESS_PATH_PATTERN = re.compile(re.escape(_RETIRED_PROGRESS_SCRIPT))
TASK_BRIEF_PATH_PATTERN = re.compile(re.escape(_RETIRED_TASK_BRIEF_SCRIPT))
BARE_TASK_BRIEF_PATTERN = re.compile(r"\btask-brief\b")

STALE_PATTERNS = [PROGRESS_PATH_PATTERN, TASK_BRIEF_PATH_PATTERN, BARE_TASK_BRIEF_PATTERN]

SKIPPED_DIR_NAMES = {"__pycache__", ".git"}

# Minimum number of files the real scan must read before an empty offender
# list is trusted — a scan that silently covered zero files (a relocated
# or renamed CHRIS_CODE_DIR, say) must fail loudly, not pass green.
MIN_EXPECTED_FILE_COUNT = 20


def _is_excused(path: Path, line: str) -> bool:
    """The two documented historical mentions spec Sec 9's criterion 9
    explicitly tolerates: CHANGELOG's rename note and task_brief.py's own
    docstring recalling the bash predecessor it replaced. Line-scoped —
    the excusing phrase must be on the same line as the mention."""
    if path == CHANGELOG_PATH and "since renamed to" in line:
        return True
    if path == TASK_BRIEF_SCRIPT_PATH and "retired bash" in line:
        return True
    return False


def _iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if SKIPPED_DIR_NAMES & set(path.relative_to(root).parts):
            continue
        if path == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        yield path, text


def _scan(root: Path) -> list[str]:
    """Every stale reference under root, as 'path:lineno: line text'
    strings — the offender list the test asserts is empty. Lifted out of
    the test method so it's independently exercisable (see
    TestScanFindsInjectedReference and TestScanFloorIsEnforced below).

    Raises RuntimeError — not AssertionError — if the walk read fewer
    than MIN_EXPECTED_FILE_COUNT files, naming root: an empty offender
    list from a near-empty scan proves nothing, and this must fail loudly
    even under `python -O` (which strips `assert` statements but not a
    plain `raise`)."""
    offenders = []
    files_read = 0
    for path, text in _iter_text_files(root):
        files_read += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if _is_excused(path, line):
                continue
            if any(pattern.search(line) for pattern in STALE_PATTERNS):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    if files_read < MIN_EXPECTED_FILE_COUNT:
        raise RuntimeError(
            f"scan of {root} read only {files_read} file(s) — expected at "
            f"least {MIN_EXPECTED_FILE_COUNT}; an empty offender list from "
            f"a near-empty scan proves nothing (has CHRIS_CODE_DIR moved "
            f"or been renamed?)")
    return offenders


class TestNoStaleScriptReferences(unittest.TestCase):
    def test_no_stale_progress_or_task_brief_references(self):
        offenders = _scan(CHRIS_CODE_DIR)
        self.assertEqual(
            offenders, [],
            "stale reference(s) to a retired script:\n" + "\n".join(offenders),
        )


class TestPatternsPinnedIndependently(unittest.TestCase):
    """Closes the gap the two facts above open: neither the bare
    `task-brief` pattern's real-world match nor the retired-progress
    constant's exact spelling is actually exercised by the clean-scan
    test (the excused CHANGELOG/task_brief.py lines never reach
    STALE_PATTERNS, and the constant never appears in the real tree to
    typo-check itself against). Each check here is written independently
    of the thing it verifies, so a single typo can't satisfy both."""

    def test_bare_task_brief_pattern_matches_changelog_historical_line(self):
        line = next(
            ln for ln in CHANGELOG_PATH.read_text(encoding="utf-8").splitlines()
            if "since renamed to" in ln)
        self.assertRegex(line, BARE_TASK_BRIEF_PATTERN)
        self.assertTrue(_is_excused(CHANGELOG_PATH, line))

    def test_bare_task_brief_pattern_matches_task_brief_docstring_lines(self):
        lines = [
            ln for ln in TASK_BRIEF_SCRIPT_PATH.read_text(encoding="utf-8").splitlines()
            if "retired bash" in ln
        ]
        self.assertTrue(lines, "expected at least one 'retired bash' docstring "
                                "line in task_brief.py")
        for line in lines:
            self.assertRegex(line, BARE_TASK_BRIEF_PATTERN)
            self.assertTrue(_is_excused(TASK_BRIEF_SCRIPT_PATH, line))

    def test_changelog_line_without_excusing_phrase_is_not_excused(self):
        # Pins the negative direction: _is_excused must not loosen into
        # "any task-brief/progress mention in CHANGELOG.md is excused" —
        # only the one line carrying "since renamed to" is.
        self.assertFalse(
            _is_excused(CHANGELOG_PATH, "a new entry citing task-brief"))

    def test_task_brief_script_line_without_excusing_phrase_is_not_excused(self):
        # Same negative pin for task_brief.py: only a line carrying
        # "retired bash" is excused, not any task-brief mention in the file.
        self.assertFalse(
            _is_excused(TASK_BRIEF_SCRIPT_PATH, "see the old task-brief invocation"))

    def test_retired_progress_script_constant_is_spelled_correctly(self):
        # Built with different split points than _RETIRED_PROGRESS_SCRIPT's
        # own construction ("scripts" + "/" + "progress"), so a typo in
        # either one's parts (e.g. dropping the trailing "s") can't
        # silently produce agreement between the two.
        independently_built = "scr" + "ipts" + "/prog" + "ress"
        self.assertEqual(_RETIRED_PROGRESS_SCRIPT, independently_built)

    def test_retired_task_brief_script_constant_is_spelled_correctly(self):
        independently_built = "scri" + "pts/task" + "-br" + "ief"
        self.assertEqual(_RETIRED_TASK_BRIEF_SCRIPT, independently_built)


class TestScanFindsInjectedReference(unittest.TestCase):
    """Proves _scan's bite, not just its silence: a deliberately injected
    retired-script reference in a throwaway tree must be caught and named
    file:line, independent of the real chris-code/ tree being clean."""

    def test_injected_reference_is_reported_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offending_file = root / "notes.md"
            offending_file.write_text(
                "line one\nsee " + _RETIRED_PROGRESS_SCRIPT + " for details\n",
                encoding="utf-8",
            )
            # Pad past MIN_EXPECTED_FILE_COUNT so the fixture's own
            # loud-failure floor doesn't mask the assertion under test.
            for i in range(MIN_EXPECTED_FILE_COUNT):
                (root / f"filler-{i}.txt").write_text("nothing to see here\n",
                                                        encoding="utf-8")

            offenders = _scan(root)

        expected = f"{offending_file}:2: see {_RETIRED_PROGRESS_SCRIPT} for details"
        self.assertEqual(offenders, [expected])


class TestScanFloorIsEnforced(unittest.TestCase):
    """_scan's loud-failure floor (see its docstring): a near-empty tree
    must raise, not silently report a clean bill of health."""

    def test_scan_on_empty_tree_raises_naming_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError) as ctx:
                _scan(root)
        self.assertIn(str(root), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
