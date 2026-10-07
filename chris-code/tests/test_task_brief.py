#!/usr/bin/env python3
"""
Tests for task_brief.py (spec Sec 9 acceptance criteria 1, 2, 6).

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

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
import task_brief  # noqa: E402

TASK_BRIEF_PY = SCRIPTS_DIR / "task_brief.py"

PLAN_TEXT = """# Fixture Plan

## 4. Constraints

- Non-negotiable invariant one.
- Non-negotiable invariant two.

## 5. Tasks

### Task 1: warm-up

- Consumes: nothing
- Cases: n/a — setup only, no input domain
- [ ] do the warm-up thing

### Task 2: the real task

- Consumes: contract from spec §6 → `{consumed_path}`
- Cases: size>0; size=0, size<0, size=None → ValueError
- [ ] Concrete action
- [ ] Verify: something

### Task 3: cool-down

- Cases: n/a — wrap-up only
- [ ] wrap up

## 6. Acceptance checks

- everything passes
"""

SPEC_TEXT = """# Fixture Spec

## 4. System behavior

Some behavior text.

## 6. Canonical interfaces

Some contract text.
"""


def _plan_with_pointer(pointer_line: str) -> str:
    return PLAN_TEXT.replace(
        "- Consumes: contract from spec §6 → `{consumed_path}`",
        f"- Consumes: {pointer_line}",
    )


class TaskBriefTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.store = self.tmp / "store"
        self.plan_path = self.tmp / "plan.md"
        self.spec_path = self.tmp / "spec.md"
        self.spec_path.write_text(SPEC_TEXT, encoding="utf-8")

    def _cd(self, path: Path) -> None:
        """Temporarily chdir for tests that exercise a genuinely relative
        Consumes: pointer (./x, ../x, _pkg/x) — resolution is CWD-based,
        so these need a real working directory, not just an absolute
        prefix. Restored by addCleanup regardless of test outcome."""
        old = os.getcwd()
        os.chdir(str(path))
        self.addCleanup(os.chdir, old)

    def _args(self, **overrides) -> task_brief.BriefRequest:
        # run() takes an explicit BriefRequest, not an argparse.Namespace,
        # so tests build one directly instead of round-tripping through
        # argv construction and argparse just to get an object with the
        # right attribute names (TestCLI below still exercises the real
        # argv -> exit-code interface via subprocess).
        base = dict(
            plan_file=str(self.plan_path),
            task_n="2",
            intent="make the thing work",
            note=(),
            spec=None,
            constraints_from=None,
            store=str(self.store),
            output=None,
        )
        base.update(overrides)
        return task_brief.BriefRequest(**base)


# --- extract_task_entry (fence-aware "Task N" heading match) ---

class TestExtractTaskEntry(unittest.TestCase):
    def test_extracts_named_task_only(self):
        entry = task_brief.extract_task_entry(PLAN_TEXT, "2")
        self.assertIn("### Task 2: the real task", entry)
        self.assertIn("Concrete action", entry)
        self.assertNotIn("warm-up", entry)
        self.assertNotIn("cool-down", entry)

    def test_stops_at_next_task_heading_not_other_headings(self):
        # Preserves the old awk quirk: only a "Task <number>" heading (not
        # e.g. "## 6. Acceptance checks") closes a section, so content
        # between the last task and a following non-task heading is kept.
        text = "### Task 1: solo\n- [ ] do it\n## Acceptance checks\n- pass\n"
        entry = task_brief.extract_task_entry(text, "1")
        self.assertIn("Acceptance checks", entry)

    def test_fence_aware_ignores_heading_lookalikes_in_code_blocks(self):
        text = (
            "### Task 1: real\n- [ ] real action\n"
            "```\n### Task 2: fake, inside a fence\n```\n"
            "### Task 2: also real\n- [ ] real action two\n"
        )
        entry = task_brief.extract_task_entry(text, "2")
        self.assertIn("also real", entry)
        self.assertNotIn("fake, inside a fence", entry)

    def test_task_not_found_raises_usage_error(self):
        with self.assertRaises(task_brief.UsageError):
            task_brief.extract_task_entry(PLAN_TEXT, "99")

    def test_task_1_does_not_absorb_task_10(self):
        # this_task_re's number-boundary guard ((?:[^0-9]|$) after the
        # literal task number) must reject "Task 10" when asked for task
        # "1" — a prefix match without the boundary would incorrectly
        # absorb every Task 1X heading into Task 1's entry.
        text = (
            "### Task 1: first\n- [ ] do first\n"
            "### Task 10: tenth\n- [ ] do tenth\n"
        )
        entry = task_brief.extract_task_entry(text, "1")
        self.assertIn("do first", entry)
        self.assertNotIn("do tenth", entry)
        self.assertNotIn("Task 10", entry)


# --- find_consumes_pointers ---
#
# Detection extracts spans directly from a Consumes: bullet's raw text
# (spec Sec 6) rather than classifying whitespace-split tokens: §-ref
# spans first (combined per chain, e.g. "§6/§7", so no stray "/" is
# left behind), then backticked spans from the untouched original text
# (each whitespace-separated WORD inside a span is shape-tested on its
# own, so a backticked shell command like "`python3 scripts/ledger.py
# check`" still resolves the real path buried inside it), then bare
# path-character runs from what's left with both kinds of span masked
# out. A BACKTICKED word is a pointer if it contains "/" or has a valid
# "::" split (both halves non-empty). A BARE run is a pointer if it has
# a valid "::" split (that alone is decisive — "::" essentially never
# occurs in ordinary prose, e.g. "ledger.py::list_shapes" needs no "/"),
# or if it is file-shaped: contains "/" with a dot in its final segment,
# or ends with "/". A colon-adjacent word with an empty half on either
# side of "::" ("note::", "::1") is never treated as path::symbol.
# Either way, a run containing "://" is a URL, never a pointer.

class TestFindConsumesPointers(unittest.TestCase):
    def test_path_shaped_backtick_token_is_a_pointer(self):
        entry = (
            "### Task 2: x\n"
            "- Consumes: `check` contract from spec §6 → `a/b.py`\n"
        )
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["a/b.py"])
        self.assertEqual(findings.section_refs, ["6"])

    def test_backticked_filename_with_no_slash_is_not_path_shaped(self):
        # Precedent already in the plan: "Consumes: `ledger.py` CLI from
        # Task 1" mentions a bare filename in prose with no directory
        # separator — not path-shaped, must not be treated as a pointer.
        entry = "### Task 2: x\n- Consumes: `ledger.py` CLI from Task 1\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_bare_filename_with_no_slash_is_not_file_shaped(self):
        # Refinement: a bare token needs a "/" to be file-shaped at all —
        # "ledger.py" mentioned without backticks and without a directory
        # separator stays prose, matching the backticked treatment above
        # (a slashless token is never a pointer in either form).
        entry = "### Task 2: x\n- Consumes: ledger.py CLI from Task 1\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_dotted_abbreviations_and_version_numbers_are_not_pointers(self):
        # Refinement: a slashless bare token with a dot ("e.g", "3.9",
        # "v1.2") must not be mistaken for a file — the dotted-prose false
        # positive the "/"-required rule was added to kill.
        entry = "### Task 2: x\n- Consumes: the API, e.g. under Python 3.9 or v1.2\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_prose_word_is_not_path_shaped(self):
        entry = "### Task 2: x\n- Consumes: the importable API from earlier work\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_bare_path_with_trailing_period_rstrips_to_the_real_path(self):
        # Sentence-final punctuation with no space before it: the trailing
        # "." must rstrip off, leaving the real file-shaped path — not the
        # path-plus-period as one (never-existing) token.
        entry = "### Task 2: x\n- Consumes: see chris-code/tests/test_ledger.py. for details\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["chris-code/tests/test_ledger.py"])

    def test_bare_slashed_prose_with_trailing_period_stays_prose(self):
        # "store/records" has no dot in its final segment even after the
        # sentence-final period rstrips off — stays prose, same as without
        # the trailing period.
        entry = "### Task 2: x\n- Consumes: the store/records. API from earlier work\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_section_ref_token_with_slash_is_not_treated_as_a_path(self):
        # "§6/§7" contains a literal "/" but must stay a section-ref pair,
        # not a false-positive path pointer.
        entry = "### Task 2: x\n- Consumes: amended contract from spec §6/§7\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])
        self.assertEqual(sorted(findings.section_refs), ["6", "7"])

    def test_section_ref_masking_preserves_word_separation(self):
        # A §-ref span masks to a single SPACE, not empty string: with no
        # space in the original text at all ("a/b.py§6c/d.py"), masking
        # with "" would fuse the trailing path onto the removed span's
        # neighbor (bogus single token "a/b.pyc/d.py"); masking with " "
        # keeps the two real paths apart and the section ref intact.
        entry = "### Task 2: x\n- Consumes: a/b.py§6c/d.py\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["a/b.py", "c/d.py"])
        self.assertEqual(findings.section_refs, ["6"])

    def test_multiple_comma_separated_backtick_paths(self):
        entry = "### Task 2: x\n- Consumes: things → `dir/a.py`, `dir/b.py`\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["dir/a.py", "dir/b.py"])

    def test_path_symbol_token_splits(self):
        entry = "### Task 2: x\n- Consumes: thing → `a/b.py::foo`\n"
        [pointer] = task_brief.find_consumes_pointers(entry).pointers
        self.assertEqual(pointer.path, "a/b.py")
        self.assertEqual(pointer.symbol, "foo")

    def test_backticked_slash_path_out_of_convention_is_a_pointer(self):
        # A backticked path with no arrow, phrased differently than the
        # usual convention, must still be detected — backticks alone are
        # enough to mark it a pointer.
        entry = "### Task 2: x\n- Consumes: `totally/missing/file.py` from earlier work\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["totally/missing/file.py"])

    def test_ascii_arrow_bare_file_shaped_path_is_a_pointer(self):
        # A plain ASCII "->" (not the unicode "→") next to a bare,
        # un-backticked path — detection doesn't depend on the arrow at
        # all, and the token is file-shaped (".py" extension).
        entry = "### Task 2: x\n- Consumes: thing -> nope/missing.py\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["nope/missing.py"])

    def test_bare_slashed_prose_without_a_dot_is_not_a_pointer(self):
        # "store/records" is prose (the plan's own Task 2 Consumes line),
        # not a path — no dot in its final segment, so a bare token stays
        # prose. Same for "read/write" and "Task 1/2".
        entry = ("### Task 2: x\n"
                 "- Consumes: the store/records API, read/write access, Task 1/2 ordering\n")
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_bare_trailing_slash_directory_is_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: things under some/missing/dir/\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["some/missing/dir/"])

    def test_url_is_never_a_pointer_backticked_or_bare(self):
        entry = ("### Task 2: x\n"
                 "- Consumes: see `https://example.com/a/b.py` and https://example.com/x/y\n")
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_emphasized_markdown_path_strips_clean(self):
        entry = "### Task 2: x\n- Consumes: thing at **dir/x.py** for details\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["dir/x.py"])


# --- validate_consumes / stale pointer detection (acceptance criterion 2) ---

class TestValidateConsumes(TaskBriefTestCase):
    def test_nonexistent_bare_path_is_stale(self):
        entry = "### Task 2: x\n- Consumes: thing → `does/not/exist.py`\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "does/not/exist.py"):
            task_brief.validate_consumes(entry, None)

    def test_existing_path_missing_symbol_is_stale(self):
        real = self.tmp / "real.py"
        real.write_text("def bar(): pass\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: thing → `{real}::foo`\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "foo"):
            task_brief.validate_consumes(entry, None)

    def test_existing_path_with_symbol_passes(self):
        real = self.tmp / "real.py"
        real.write_text("def foo(): pass\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: thing → `{real}::foo`\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_unresolvable_section_ref_is_stale(self):
        entry = "### Task 2: x\n- Consumes: thing from spec §99\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "§99"):
            task_brief.validate_consumes(entry, str(self.spec_path))

    def test_resolvable_section_ref_passes(self):
        entry = "### Task 2: x\n- Consumes: thing from spec §6\n"
        task_brief.validate_consumes(entry, str(self.spec_path))  # no raise

    def test_h3_subsection_ref_resolves(self):
        # §6.1 names an h3 "### 6.1 ..." subsection heading, one level
        # deeper than every other resolvable-ref fixture in this file —
        # pins HEADING_NUMBER_RE's "#{1,6}" depth end to end.
        spec_with_subsection = self.tmp / "spec_with_subsection.md"
        spec_with_subsection.write_text(
            "# Fixture Spec\n\n## 6. Canonical interfaces\n\n"
            "### 6.1 A subsection\n\nBody text.\n",
            encoding="utf-8")
        entry = "### Task 2: x\n- Consumes: thing from spec §6.1\n"
        task_brief.validate_consumes(entry, str(spec_with_subsection))  # no raise

    def test_section_ref_without_spec_raises_usage_error(self):
        entry = "### Task 2: x\n- Consumes: thing from spec §6\n"
        with self.assertRaises(task_brief.UsageError):
            task_brief.validate_consumes(entry, None)

    def test_multiple_stale_pointers_all_named(self):
        entry = (
            "### Task 2: x\n"
            "- Consumes: a → `missing1/file.py`\n"
            "- Consumes: b → `missing2/file.py`\n"
        )
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        message = str(ctx.exception)
        self.assertIn("missing1/file.py", message)
        self.assertIn("missing2/file.py", message)

    def test_prose_symbol_token_is_not_validated(self):
        # A bare, non-path-shaped token in a Consumes: line (a subcommand
        # name mentioned in prose) must not be checked against the
        # filesystem at all, even though no file named "check" exists
        # anywhere.
        entry = "### Task 2: x\n- Consumes: `check` contract from spec §6\n"
        task_brief.validate_consumes(entry, str(self.spec_path))  # no raise

    def test_ascii_arrow_stale_path_is_caught(self):
        # Detection must not depend on the arrow character at all — an
        # ASCII "->" next to a stale bare path is still caught end to end
        # through validate_consumes.
        entry = "### Task 2: x\n- Consumes: thing -> nope/missing.py\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "nope/missing.py"):
            task_brief.validate_consumes(entry, None)

    def test_bare_slashed_prose_is_not_validated(self):
        # "store/records" is the plan's own Task 2 phrasing — a bare token
        # with no dot in its final segment must not block the brief even
        # though no file literally named "store/records" exists.
        entry = "### Task 2: x\n- Consumes: the store/records API from earlier work\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_url_is_not_validated(self):
        entry = "### Task 2: x\n- Consumes: see https://example.com/a/b.py for details\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_bare_path_with_trailing_period_validates_the_real_repo_relative_file(self):
        # Repo-root-relative, no chdir needed (paths resolve against the
        # invoking CWD by convention — spec Sec 6): this file really
        # exists, so the rstripped path must validate clean even though
        # the raw un-rstripped token (with the period) would not.
        entry = "### Task 2: x\n- Consumes: see chris-code/tests/test_ledger.py. for details\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_bare_slashed_prose_with_trailing_period_is_not_validated(self):
        entry = "### Task 2: x\n- Consumes: the store/records. API from earlier work\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_bare_trailing_slash_directory_is_validated_and_stale(self):
        entry = "### Task 2: x\n- Consumes: things under some/missing/dir/\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "some/missing/dir/"):
            task_brief.validate_consumes(entry, None)

    def test_emphasized_markdown_path_is_validated_and_stale(self):
        entry = "### Task 2: x\n- Consumes: thing at **dir/missing.py** for details\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "dir/missing.py"):
            task_brief.validate_consumes(entry, None)

    def test_emphasized_markdown_path_to_existing_file_passes(self):
        real = self.tmp / "x.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: thing at **{real}** for details\n"
        task_brief.validate_consumes(entry, None)  # no raise


# --- extract_section (--constraints-from) ---

class TestValidateCases(unittest.TestCase):
    """Every task states the cases its rule covers, or says why it has none
    (2026-10-06): coders patched only the cited line, and siblings like
    size=None surfaced one review cycle at a time."""

    def test_listed_cases_pass(self):
        task_brief.validate_cases("### Task 2: x\n- Cases: size>0; size=None → ValueError\n")

    def test_na_with_a_reason_passes(self):
        for dash in ("—", "-", "–"):
            task_brief.validate_cases(f"### Task 2: x\n- Cases: n/a {dash} wiring only\n")

    def test_missing_cases_line_raises(self):
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_cases("### Task 2: x\n- [ ] do it\n")
        self.assertIn("Cases:", str(ctx.exception))

    def test_empty_cases_raises(self):
        with self.assertRaises(task_brief.BriefValidationError):
            task_brief.validate_cases("### Task 2: x\n- Cases:   \n")

    def test_bare_na_without_a_reason_raises(self):
        for bare in ("n/a", "N/A", "n/a —"):
            with self.assertRaises(task_brief.BriefValidationError, msg=bare) as ctx:
                task_brief.validate_cases(f"### Task 2: x\n- Cases: {bare}\n")
            self.assertIn("reason", str(ctx.exception))

    def test_na_variants_without_a_real_reason_raise(self):
        for value in ("n/a.", "n/a:", "n/a ()", "none", "TBD", "todo", "-"):
            with self.assertRaises(task_brief.BriefValidationError, msg=value):
                task_brief.validate_cases(f"### Task 2: x\n- Cases: {value}\n")

    def test_na_with_colon_or_parenthesized_reason_passes(self):
        for value in ("n/a: wiring only", "n/a (docs only)"):
            task_brief.validate_cases(f"### Task 2: x\n- Cases: {value}\n")

    def test_bold_and_unbulleted_cases_lines_count(self):
        for line in ("- **Cases:** size>0", "Cases: size>0", "**Cases:** size>0"):
            task_brief.validate_cases(f"### Task 2: x\n{line}\n")

    def test_cases_as_an_indented_sub_list_counts(self):
        entry = "### Task 2: x\n- Cases:\n  - size>0\n  - size=None → ValueError\n- [ ] do it\n"
        task_brief.validate_cases(entry)

    def test_empty_cases_header_followed_by_a_sibling_bullet_still_raises(self):
        entry = "### Task 2: x\n- Cases:\n- [ ] do it\n"
        with self.assertRaises(task_brief.BriefValidationError):
            task_brief.validate_cases(entry)

    def test_cases_line_inside_a_code_fence_does_not_count(self):
        entry = "### Task 2: x\n```\n- Cases: size>0\n```\n- [ ] do it\n"
        with self.assertRaises(task_brief.BriefValidationError):
            task_brief.validate_cases(entry)


class TestExtractSection(unittest.TestCase):
    def test_extracts_constraints_stops_at_next_same_level_heading(self):
        section = task_brief.extract_section(PLAN_TEXT, "Constraints")
        self.assertIn("Non-negotiable invariant one.", section)
        self.assertIn("Non-negotiable invariant two.", section)
        self.assertNotIn("Tasks", section)

    def test_missing_heading_raises_usage_error(self):
        with self.assertRaises(task_brief.UsageError):
            task_brief.extract_section("# No such section here\n", "Constraints")


# --- heading_section_numbers (HEADING_NUMBER_RE's "#{1,6}" depth) ---

class TestHeadingSectionNumbers(unittest.TestCase):
    def test_h3_subsection_number_is_found(self):
        # HEADING_NUMBER_RE matches "#{1,6}", not just the h1/h2 depths
        # every other fixture in this file happens to use — an h3
        # "### 6.1 ..." subsection heading must resolve too.
        text = "# Fixture Spec\n\n## 6. Canonical interfaces\n\n### 6.1 A subsection\n\nBody text.\n"
        numbers = task_brief.heading_section_numbers(text)
        self.assertEqual(numbers, {"6", "6.1"})


# --- build_brief (direct, not just through run()) ---

class TestBuildBrief(unittest.TestCase):
    def test_zero_notes_renders_the_none_placeholder(self):
        brief = task_brief.build_brief(
            task_n="2", task_entry="### Task 2: x\n- [ ] do it\n", intent="make it work",
            notes=(), constraints=None, shapes_text="(none recorded yet)")
        self.assertIn("## Cross-task notes", brief)
        lines = brief.splitlines()
        notes_heading = lines.index("## Cross-task notes")
        # The placeholder is the next non-blank line after the heading —
        # not just present anywhere in the brief, but standing in for the
        # empty notes list specifically.
        self.assertEqual(lines[notes_heading + 2], "(none)")


# --- run() end-to-end (acceptance criteria 1, 2, 6) ---

def _write_shape_record(store: Path) -> None:
    store.mkdir(parents=True, exist_ok=True)
    (store / "task-1-python-coder.json").write_text(json.dumps({
        "schema": 1, "agent": "python-coder", "role": "coder", "task": 1,
        "status": "done", "changed_files": [], "tests": {},
        "new_shared_symbols": [{"symbol": "foo", "path": "a.py", "why": "shared"}],
        "duplication_pending": [], "concerns": [], "report": "",
    }), encoding="utf-8")


class TestRunEndToEnd(TaskBriefTestCase):
    def test_missing_intent_exits_nonzero_and_writes_nothing(self):
        # Acceptance criterion 1.
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        args = self._args(intent="   ", spec=str(self.spec_path))
        with self.assertRaises(task_brief.BriefValidationError):
            task_brief.run(args)
        self.assertFalse(any(self.store.rglob("*brief*")))

    def test_stale_pointer_exits_3_names_it_writes_nothing(self):
        # Acceptance criterion 2 (stale path case).
        self.plan_path.write_text(
            _plan_with_pointer("contract from spec §6 → `does/not/exist.py`"),
            encoding="utf-8")
        args = self._args(spec=str(self.spec_path))
        with self.assertRaisesRegex(task_brief.BriefValidationError, "does/not/exist.py"):
            task_brief.run(args)
        self.assertFalse(any(self.store.rglob("*brief*")))

    def test_stale_section_ref_exits_3_names_it_writes_nothing(self):
        self.plan_path.write_text(
            _plan_with_pointer("contract from spec §99"), encoding="utf-8")
        args = self._args(spec=str(self.spec_path))
        with self.assertRaisesRegex(task_brief.BriefValidationError, "§99"):
            task_brief.run(args)
        self.assertFalse(any(self.store.rglob("*brief*")))

    def test_task_without_cases_line_exits_3_writes_nothing(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        plan = _plan_with_pointer(f"contract from spec §6 → `{consumed}`").replace(
            "- Cases: size>0; size=0, size<0, size=None → ValueError\n", "")
        self.plan_path.write_text(plan, encoding="utf-8")
        with self.assertRaisesRegex(task_brief.BriefValidationError, "Cases:"):
            task_brief.run(self._args(spec=str(self.spec_path)))
        self.assertFalse(any(self.store.rglob("*brief*")))

    def test_brief_carries_the_cases_line(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        brief = task_brief.run(self._args(spec=str(self.spec_path))).read_text(encoding="utf-8")
        self.assertIn("- Cases: size>0; size=0, size<0, size=None → ValueError", brief)

    def test_valid_brief_contains_entry_intent_notes_constraints_shapes(self):
        # Acceptance criteria 2 (valid path) and 6 (shapes carry into the brief).
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        _write_shape_record(self.store)

        args = self._args(
            note=("watch out for X", "Y was already handled"),
            spec=str(self.spec_path),
            constraints_from=str(self.plan_path),
        )
        out_path = task_brief.run(args)
        brief = out_path.read_text(encoding="utf-8")

        self.assertIn("Task 2: the real task", brief)          # task entry
        self.assertIn("make the thing work", brief)             # intent
        self.assertIn("watch out for X", brief)                 # notes
        self.assertIn("Y was already handled", brief)
        self.assertIn("Non-negotiable invariant one.", brief)   # verbatim constraints
        self.assertIn("foo", brief)                             # shared shapes
        self.assertIn("a.py", brief)

    def test_shared_shapes_section_present_even_when_store_empty(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")

        args = self._args(spec=str(self.spec_path))
        out_path = task_brief.run(args)
        brief = out_path.read_text(encoding="utf-8")
        self.assertIn("Shared shapes already built", brief)
        self.assertIn(ledger.render_shapes([]), brief)  # "(none recorded yet)" placeholder

    def test_default_output_path_uses_store_and_task_n(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        args = self._args(spec=str(self.spec_path))
        out_path = task_brief.run(args)
        # ledger.get_store_dir resolves the store path (e.g. through macOS's
        # /var -> /private/var symlink), so compare against a resolved path.
        self.assertEqual(out_path, self.store.resolve() / "task-2-brief.md")
        # the default path routes creation through ledger.ensure_store, so a
        # store born from a brief write is still self-ignoring.
        self.assertEqual(
            (self.store.resolve() / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_explicit_output_path_honored(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        custom = self.tmp / "out" / "brief.md"
        args = self._args(spec=str(self.spec_path), output=str(custom))
        out_path = task_brief.run(args)
        self.assertEqual(out_path, custom)
        self.assertTrue(custom.is_file())

    def test_missing_plan_file_is_usage_error(self):
        args = self._args(plan_file=str(self.tmp / "nope.md"))
        with self.assertRaises(task_brief.UsageError):
            task_brief.run(args)

    def test_task_not_found_is_usage_error(self):
        self.plan_path.write_text(PLAN_TEXT, encoding="utf-8")
        args = self._args(task_n="99")
        with self.assertRaises(task_brief.UsageError):
            task_brief.run(args)


# --- CLI end-to-end (subprocess, exit codes) ---

class TestCLI(TaskBriefTestCase):
    def _run(self, *extra_args):
        return subprocess.run(
            [sys.executable, str(TASK_BRIEF_PY), str(self.plan_path), "2",
             "--store", str(self.store), *extra_args],
            capture_output=True, text=True)

    def test_missing_intent_exits_3(self):
        self.plan_path.write_text(PLAN_TEXT, encoding="utf-8")
        result = self._run()  # no --intent at all
        self.assertEqual(result.returncode, task_brief.EXIT_INVALID)
        # A literal-3 pin alongside the constant-based assert above: if
        # EXIT_INVALID and EXIT_USAGE ever drifted to the same value (or
        # either drifted off its spec-mandated number), a mutant that
        # swaps one constant's value for the other's would still pass the
        # constant-based assert but fail this one.
        self.assertEqual(result.returncode, 3)
        self.assertFalse(any(self.store.rglob("*brief*")))

    def test_bad_plan_file_exits_2(self):
        result = subprocess.run(
            [sys.executable, str(TASK_BRIEF_PY), str(self.tmp / "nope.md"), "2",
             "--intent", "x", "--store", str(self.store)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, task_brief.EXIT_USAGE)
        self.assertEqual(result.returncode, 2)

    def test_valid_run_exits_0_and_prints_path(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        result = self._run("--intent", "do the thing", "--spec", str(self.spec_path))
        self.assertEqual(result.returncode, 0)
        out_path = Path(result.stdout.strip())
        self.assertTrue(out_path.is_file())


# --- punctuation-adjacency matrix (span extraction, not token
# classification): glued arrow, glued §-ref, markdown link syntax,
# comma-joined backticks, and ./ ../ _ leading paths, each exercised both
# stale (BriefValidationError naming the exact pointer) and existing
# (validate_consumes doesn't raise) ---

class TestPunctuationAdjacencyMatrix(TaskBriefTestCase):
    def test_glued_arrow_backticked_stale(self):
        missing = self.tmp / "gone/missing.py"
        entry = f"### Task 2: x\n- Consumes: thing->`{missing}`\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape(str(missing))):
            task_brief.validate_consumes(entry, None)

    def test_glued_arrow_backticked_existing_passes(self):
        real = self.tmp / "real.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: thing->`{real}`\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_glued_arrow_bare_stale(self):
        missing = self.tmp / "gone" / "missing.py"
        entry = f"### Task 2: x\n- Consumes: thing->{missing}\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape(str(missing))):
            task_brief.validate_consumes(entry, None)

    def test_glued_arrow_bare_existing_passes(self):
        real = self.tmp / "real.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: thing->{real}\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_glued_section_ref_backticked_stale(self):
        # A pointer glued directly to a §-ref with no space at all must
        # still resolve.
        missing = self.tmp / "totally" / "missing.py"
        entry = f"### Task 2: x\n- Consumes: §6→`{missing}`\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape(str(missing))):
            task_brief.validate_consumes(entry, str(self.spec_path))

    def test_glued_section_ref_backticked_existing_passes(self):
        real = self.tmp / "real.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: §6→`{real}`\n"
        task_brief.validate_consumes(entry, str(self.spec_path))  # no raise

    def test_markdown_link_bare_stale(self):
        missing = self.tmp / "gone" / "missing.py"
        entry = f"### Task 2: x\n- Consumes: see [the file]({missing}) for details\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape(str(missing))):
            task_brief.validate_consumes(entry, None)

    def test_markdown_link_bare_existing_passes(self):
        real = self.tmp / "real.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: see [the file]({real}) for details\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_comma_joined_backticks_stale_names_the_missing_one(self):
        real = self.tmp / "real.py"
        real.write_text("x = 1\n", encoding="utf-8")
        missing = self.tmp / "missing.py"
        entry = f"### Task 2: x\n- Consumes: things → `{real}`, `{missing}`\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape(str(missing))):
            task_brief.validate_consumes(entry, None)

    def test_comma_joined_backticks_existing_passes(self):
        real1 = self.tmp / "real1.py"
        real1.write_text("x = 1\n", encoding="utf-8")
        real2 = self.tmp / "real2.py"
        real2.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: things → `{real1}`, `{real2}`\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_leading_dot_slash_stale(self):
        self._cd(self.tmp)
        entry = "### Task 2: x\n- Consumes: thing at ./gone/missing.py\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, re.escape("./gone/missing.py")):
            task_brief.validate_consumes(entry, None)

    def test_leading_dot_slash_existing_passes(self):
        self._cd(self.tmp)
        (self.tmp / "real.py").write_text("x = 1\n", encoding="utf-8")
        entry = "### Task 2: x\n- Consumes: thing at ./real.py\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_leading_dotdot_slash_stale(self):
        sub = self.tmp / "sub"
        sub.mkdir()
        self._cd(sub)
        entry = "### Task 2: x\n- Consumes: thing at ../gone/missing.py\n"
        with self.assertRaisesRegex(
                task_brief.BriefValidationError, re.escape("../gone/missing.py")):
            task_brief.validate_consumes(entry, None)

    def test_leading_dotdot_slash_existing_passes(self):
        sub = self.tmp / "sub"
        sub.mkdir()
        (self.tmp / "real.py").write_text("x = 1\n", encoding="utf-8")
        self._cd(sub)
        entry = "### Task 2: x\n- Consumes: thing at ../real.py\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_leading_underscore_stale(self):
        self._cd(self.tmp)
        entry = "### Task 2: x\n- Consumes: thing at _pkg/missing.py\n"
        with self.assertRaisesRegex(
                task_brief.BriefValidationError, re.escape("_pkg/missing.py")):
            task_brief.validate_consumes(entry, None)

    def test_leading_underscore_existing_passes(self):
        self._cd(self.tmp)
        pkg = self.tmp / "_pkg"
        pkg.mkdir()
        (pkg / "real.py").write_text("x = 1\n", encoding="utf-8")
        entry = "### Task 2: x\n- Consumes: thing at _pkg/real.py\n"
        task_brief.validate_consumes(entry, None)  # no raise


# --- CONSUMES_LINE_RE bullet markers ---

class TestConsumesLineBulletMarkers(unittest.TestCase):
    def test_star_and_plus_bullets_are_recognized(self):
        entry = (
            "### Task 2: x\n"
            "* Consumes: thing → `dir/a.py`\n"
            "+ Consumes: thing → `dir/b.py`\n"
        )
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["dir/a.py", "dir/b.py"])


# --- bare path::symbol (orchestrator ruling: "::" never occurs in prose,
# so a bare path::symbol is a pointer even with no "/" in the path half) ---

class TestBarePathSymbol(TaskBriefTestCase):
    def test_bare_path_symbol_is_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: use ledger.py::list_shapes for this\n"
        findings = task_brief.find_consumes_pointers(entry)
        [pointer] = findings.pointers
        self.assertEqual(pointer.path, "ledger.py")
        self.assertEqual(pointer.symbol, "list_shapes")

    def test_bare_path_symbol_missing_symbol_is_stale(self):
        real = self.tmp / "ledger.py"
        real.write_text("def other(): pass\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: use {real}::list_shapes for this\n"
        with self.assertRaisesRegex(task_brief.BriefValidationError, "list_shapes"):
            task_brief.validate_consumes(entry, None)

    def test_bare_path_symbol_existing_passes(self):
        real = self.tmp / "ledger.py"
        real.write_text("def list_shapes(): pass\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: use {real}::list_shapes for this\n"
        task_brief.validate_consumes(entry, None)  # no raise


# --- backticked command span: a backticked span may contain whitespace —
# a shell command is idiomatic in this repo's plans — and the real path
# buried inside it must be recovered and validated, not the command
# treated as one opaque token ---

class TestBacktickedCommandSpan(TaskBriefTestCase):
    def test_command_span_extracts_only_the_path_word(self):
        entry = "### Task 2: x\n- Consumes: run `python3 scripts/ledger.py check`\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["scripts/ledger.py"])

    def test_command_span_with_existing_path_passes_and_validates_it(self):
        real = self.tmp / "ledger.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: run `python3 {real} check`\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_command_span_with_stale_path_fails_naming_the_path_not_the_command(self):
        missing = self.tmp / "gone" / "ledger.py"
        entry = f"### Task 2: x\n- Consumes: run `python3 {missing} check`\n"
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        message = str(ctx.exception)
        self.assertIn(str(missing), message)
        self.assertNotIn("python3", message)
        self.assertNotIn(f"python3 {missing} check", message)

    def test_command_span_with_path_symbol_word_splits(self):
        entry = "### Task 2: x\n- Consumes: run `python3 a/b.py::foo check`\n"
        [pointer] = task_brief.find_consumes_pointers(entry).pointers
        self.assertEqual(pointer.path, "a/b.py")
        self.assertEqual(pointer.symbol, "foo")

    def test_command_span_with_no_path_word_yields_no_pointer(self):
        entry = "### Task 2: x\n- Consumes: run `ledger.py check`\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])


# --- "::" requires non-empty halves on both sides (recommended, applied):
# kills "note::" trailing-colon prose and an "::1"-style empty-path class
# (IPv6 loopback shorthand, plausible near a "git@..." remote mention) ---

class TestColonPairRequiresNonEmptyHalves(TaskBriefTestCase):
    def test_trailing_double_colon_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: see the note:: prefix convention\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_backticked_trailing_double_colon_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: see the `note::` prefix convention\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_leading_double_colon_empty_path_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: connect to git@host, loopback is ::1 for testing\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_trailing_double_colon_is_not_validated(self):
        entry = "### Task 2: x\n- Consumes: see the note:: prefix convention\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_dangling_double_colon_after_existing_path_fails_loudly(self):
        # The file-likeness check alone doesn't cover this case. Without
        # the non-empty-halves guard, "existing.py::"
        # would split to (path="existing.py", symbol="") — an empty
        # symbol is falsy, so validation would silently check only the
        # real underlying path and pass, discarding the dangling "::"
        # the author actually wrote. With the guard, the split is
        # rejected, so the *whole* token (colons included) becomes the
        # path — which reliably doesn't exist as a literal filename — and
        # fails loudly instead of silently accepting a malformed
        # reference.
        real = self.tmp / "tools.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: see {real}:: for details\n"
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        self.assertIn(f"{real}::", str(ctx.exception))


# --- "::" prose discriminator is symmetric (spec confirm amendment): a
# path::symbol token is a pointer only when its path half looks like a
# file (contains "/" or a dot) — bare AND backticked. "std::vector" and
# "serde::Deserialize" are Rust/C++ scope-resolution syntax (this repo
# ships Rust agents), not path pointers, in either form. Existing "::"
# positives (ledger.py::list_shapes, scripts/x.py::fn-shaped paths) stay
# positive — see TestBarePathSymbol and TestBacktickedCommandSpan.

class TestColonPairPathHalfMustLookLikeAFile(TaskBriefTestCase):
    def test_bare_cpp_scope_resolution_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: uses std::vector internally\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_backticked_cpp_scope_resolution_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: uses `std::vector` internally\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_bare_rust_scope_resolution_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: derives serde::Deserialize\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_backticked_rust_scope_resolution_is_not_a_pointer(self):
        entry = "### Task 2: x\n- Consumes: derives `serde::Deserialize`\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual(findings.pointers, [])

    def test_bare_cpp_scope_resolution_is_not_validated(self):
        entry = "### Task 2: x\n- Consumes: uses std::vector internally\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_backticked_rust_scope_resolution_is_not_validated(self):
        entry = "### Task 2: x\n- Consumes: derives `serde::Deserialize`\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_dotted_bare_path_symbol_still_positive(self):
        # Existing positive stays positive: "ledger.py" has a dot, so the
        # path half looks file-like even with no "/".
        entry = "### Task 2: x\n- Consumes: use ledger.py::list_shapes for this\n"
        findings = task_brief.find_consumes_pointers(entry)
        [pointer] = findings.pointers
        self.assertEqual(pointer.path, "ledger.py")
        self.assertEqual(pointer.symbol, "list_shapes")

    def test_slashed_backticked_path_symbol_still_positive(self):
        entry = "### Task 2: x\n- Consumes: thing → `a/b.py::foo`\n"
        [pointer] = task_brief.find_consumes_pointers(entry).pointers
        self.assertEqual(pointer.path, "a/b.py")
        self.assertEqual(pointer.symbol, "foo")


# --- emphasis strips as matched pairs only: "_x_" and "__x__" unwrap to
# the clean path; a leading-only "_" ("_pkg/y.py") is preserved since
# there's no matching close; "**x**" was already handled (excluded from
# PATH_RUN_RE's character class) and keeps working ---

class TestEmphasisMatchedPairUnwrap(TaskBriefTestCase):
    def test_single_underscore_wrap_strips_to_clean_path(self):
        entry = "### Task 2: x\n- Consumes: see _chris-code/consumed.py_ for details\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["chris-code/consumed.py"])

    def test_double_underscore_wrap_strips_to_clean_path(self):
        entry = "### Task 2: x\n- Consumes: see __chris-code/consumed.py__ for details\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["chris-code/consumed.py"])

    def test_leading_only_underscore_is_preserved_not_stripped(self):
        # No matching close: "_pkg/y.py" is a real path segment, not
        # emphasis — same case already covered end to end in
        # TestPunctuationAdjacencyMatrix, re-asserted here at the
        # extraction level alongside the new matched-pair behavior.
        entry = "### Task 2: x\n- Consumes: thing at _pkg/missing.py\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["_pkg/missing.py"])

    def test_single_underscore_wrap_existing_file_passes(self):
        real = self.tmp / "consumed.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: see _{real}_ for details\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_single_underscore_wrap_stale_names_the_clean_path(self):
        missing = self.tmp / "gone" / "missing.py"
        entry = f"### Task 2: x\n- Consumes: see _{missing}_ for details\n"
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        message = str(ctx.exception)
        self.assertIn(str(missing), message)
        self.assertNotIn(f"_{missing}_", message)

    def test_double_underscore_wrap_existing_file_passes(self):
        real = self.tmp / "consumed.py"
        real.write_text("x = 1\n", encoding="utf-8")
        entry = f"### Task 2: x\n- Consumes: see __{real}__ for details\n"
        task_brief.validate_consumes(entry, None)  # no raise

    def test_double_underscore_wrap_stale_names_the_clean_path(self):
        missing = self.tmp / "gone" / "missing.py"
        entry = f"### Task 2: x\n- Consumes: see __{missing}__ for details\n"
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        message = str(ctx.exception)
        self.assertIn(str(missing), message)
        self.assertNotIn(f"__{missing}__", message)

    def test_asterisk_emphasis_still_handled(self):
        # Regression guard: asterisk emphasis was already correct (never
        # entered the char class), unaffected by the underscore change.
        entry = "### Task 2: x\n- Consumes: thing at **dir/x.py** for details\n"
        findings = task_brief.find_consumes_pointers(entry)
        self.assertEqual([p.raw for p in findings.pointers], ["dir/x.py"])


# --- dedupe pointers by raw text (recommended, applied): a path named
# twice in one entry produces one failure, not two ---

class TestDedupePointers(TaskBriefTestCase):
    def test_repeated_pointer_errors_once(self):
        missing = self.tmp / "gone" / "missing.py"
        entry = (
            "### Task 2: x\n"
            f"- Consumes: a → `{missing}`\n"
            f"- Consumes: b → `{missing}`\n"
        )
        with self.assertRaises(task_brief.BriefValidationError) as ctx:
            task_brief.validate_consumes(entry, None)
        message = str(ctx.exception)
        self.assertEqual(message.count(str(missing)), 1)


# --- get_store_dir RuntimeError -> UsageError (previously untested and
# deletable without failing the suite: every other test passes --store,
# so run() never reached the branch that catches it) ---

class TestGetStoreDirErrorMapping(TaskBriefTestCase):
    def test_runtime_error_from_get_store_dir_maps_to_usage_error(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        args = self._args(spec=str(self.spec_path), store=None)
        with mock.patch.object(task_brief.ledger, "get_store_dir",
                                side_effect=RuntimeError("not inside a git repository")):
            with self.assertRaises(task_brief.UsageError):
                task_brief.run(args)


# --- --spec naming a missing file ---

class TestSpecFileMissing(TaskBriefTestCase):
    def test_spec_path_missing_file_is_usage_error(self):
        self.plan_path.write_text(PLAN_TEXT, encoding="utf-8")
        args = self._args(spec=str(self.tmp / "no-such-spec.md"))
        with self.assertRaisesRegex(task_brief.UsageError, "no-such-spec.md"):
            task_brief.run(args)


# --- _read_text error mapping ---

class TestReadTextErrorMapping(TaskBriefTestCase):
    def test_missing_file_maps_to_error_cls(self):
        with self.assertRaises(task_brief.UsageError):
            task_brief._read_text(
                self.tmp / "nope.md", error_cls=task_brief.UsageError, label="nope")

    def test_undecodable_bytes_map_to_error_cls(self):
        bad = self.tmp / "bad.md"
        bad.write_bytes(b"\xff\xfe not utf-8")
        with self.assertRaises(task_brief.BriefValidationError):
            task_brief._read_text(
                bad, error_cls=task_brief.BriefValidationError, label="bad file")


# --- output-write OSError -> UsageError (recommended hardening: no
# failure path on the final write escapes as a bare traceback) ---

class TestOutputWriteErrorMapping(TaskBriefTestCase):
    def test_oserror_on_write_maps_to_usage_error(self):
        consumed = self.tmp / "consumed.py"
        consumed.write_text("x = 1\n", encoding="utf-8")
        self.plan_path.write_text(
            _plan_with_pointer(f"contract from spec §6 → `{consumed}`"), encoding="utf-8")
        args = self._args(spec=str(self.spec_path))
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertRaises(task_brief.UsageError):
                task_brief.run(args)


if __name__ == "__main__":
    unittest.main()
