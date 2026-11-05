#!/usr/bin/env python3
"""
ledger.py — typed record store for subagent-driven-development.

One store, one script. Agents write their own JSON record at a
dispatch-supplied path (task-<N>-<agent-name>.json, or
final-<agent-name>.json for the whole-change gate); this script derives
queryable views over those files on the fly — no fold/sync step, no drift.

Store: <repo toplevel>/.sdd/ by default, or --store DIR. The store is
uncommitted working-tree scratch: creation seeds a `.gitignore` containing
`*` inside it, so git never sees the contents no matter what the repo's
own ignore rules say. progress.jsonl in that same dir is append-only and
written only through this script; every command that writes the store
holds an exclusive lock on its `.lock` file while it reads, checks and
writes.

Philosophy (spec Sec 4/7, amended 2026-08-27): failures are loud, not
defensively rendered away. `check` is the write-time gate — an agent runs
it on its own freshly written record and fixes until it exits 0. Loading
records for a query isolates each file: one malformed record becomes one
malformed entry, never hides its siblings. Required-ness is scoped to
decision-driving fields only; informational fields are unvalidated.
Totality ("never crash on any input") is explicitly not a goal.

Usage: python3 ledger.py read|open|shapes|completed|store-dir|stats|run-state|report [--store DIR]
       python3 ledger.py clear [--discard-open] [--store DIR]
       python3 ledger.py append --type progress|complete --task N|final|run --note "..." [--store DIR]
       python3 ledger.py note --kind KIND --text "..." [--for N] [--owner N|close] [--from N|final|run] [--store DIR]
       python3 ledger.py notes --task N [--deliver | --waive ID --reason "..."] [--store DIR]
       python3 ledger.py stage --task N --stage K --files PATH... [--store DIR]
       python3 ledger.py handle --task N|final --role NAME --agent ID [--store DIR]
       python3 ledger.py close-round --expect 1|2 --note "..." [--store DIR]
       python3 ledger.py triage --task N|final [--store DIR]
       python3 ledger.py snapshot --task N --label "..." [--store DIR]
       python3 ledger.py baseline <tree> --task N [--store DIR]
       python3 ledger.py findings <decision-path> [--store DIR]
       python3 ledger.py diff-since <tree> [<path>...]   (takes no --store)
       python3 ledger.py labels <tree> [<path>...]       (takes no --store)
       python3 ledger.py resolve <id> [--note "..."] [--store DIR]
       python3 ledger.py check <record-path> [--store DIR]

A per-task decision is itself a record (role "decision", written by
remediating-issues' per-task variant). Beyond its own shape, `check`
verifies it against the store and the repo: it accounts for every
finding on every reviewer record in its scope (task-N, final, or
final-r2, from the file names), reconciles with every decision written
before it, and cites precedents that exist. Only a holistic round has
one, and its fix implements it case by case.

The review-fix loop's routing is computed, not declared: `triage` reads a
task's tagged findings and its coder's evidence, applies the rules in
triage.py, and logs the step. A fix's `check` holds it to that step.

Importable API: see __all__ below — the module's public query/validate/
render surface (data classes, `get_store_dir`, the `load_*`/`compute_*`/
`list_*`/`render_*` functions). `task_brief.py` imports a subset of it
(`get_store_dir`, `ensure_store`, `load_records`, `list_shapes`,
`render_shapes`, `load_progress_log`, `required_notes`, `record_delivery`);
the CLI
subcommand handlers (`cmd_*`), `build_parser`, and `main` are plumbing
invoked only through this script's own `main()` and are not part of the
importable surface. Functions raise instead of calling sys.exit, so
callers (task_brief.py, tests) own exit codes.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import store_state  # this script's directory: what the store holds, as pure rules
import triage as triage_rules  # this script's directory: the loop's pure routing rules

__all__ = [
    "RecordError", "Record", "OpenItem", "Shape",
    "get_store_dir", "ensure_store", "validate_record",
    "load_records", "load_progress_log", "resolutions_from_log",
    "compute_open_items", "list_shapes", "render_shapes", "render_store_markdown",
    "completed_task_ids", "close_rounds", "CLOSE_ROUND_CAP",
    "snapshot_tree", "diff_since", "diff_trees", "missing_paths", "submodule_paths",
    "LabelHit", "find_process_labels", "HISTORY_FILENAME", "load_history",
    "check_record", "finding_ids", "find_baseline", "fix_round",
    "triage_inputs", "triage_entries", "latest_triage", "task_footprint",
    "store_lock", "NOTE_KINDS", "note_id", "notes_from_log", "open_notes",
    "required_notes", "delivered_note_ids", "undelivered_notes", "owned_open_notes",
    "tasks_in_flight", "record_delivery", "stage_map", "latest_handles",
    "render_run_state", "render_report",
]

SCHEMA_VERSION = 2
# Stores are per-run and not converted: a run started on schema 1 finishes
# on the release that wrote it.
SCHEMA_1_MESSAGE = ("schema: got 1, expected 2. This record was written by an earlier "
                    "chris-code release: finish that run on the release that started it, "
                    "or clear the store (`ledger.py clear`) and start over")
ENVELOPE_FIELDS = ("schema", "agent", "role", "task")

STATUS_ENUMS = {
    "coder": {"done", "done_with_concerns", "needs_context", "blocked"},
    "spec-reviewer": {"compliant", "issues"},
    "quality-reviewer": {"approved", "issues"},
    "review-lite": {"clean", "block", "escalate"},
    # A per-task decision: `escalated` when any finding goes to the user.
    "decision": {"decided", "escalated"},
    # The scripted commit gate (labels, lint, the task's Verify command).
    "gate": {"pass", "fail"},
}
# Derived, never restated: a role added to STATUS_ENUMS alone (or vice
# versa) would turn `check`'s corrective RecordError into a raw KeyError
# at the STATUS_ENUMS[role] lookup below.
VALID_ROLES = frozenset(STATUS_ENUMS)
CODER_OPEN_STATUSES = {"blocked", "needs_context"}
REVIEWER_OPEN_STATUSES = {"issues", "block", "escalate", "fail"}
REVIEWER_ROLES = VALID_ROLES - {"coder", "decision"}
# Roles whose records carry a validated `cycle`.
CYCLE_ROLES = ("coder", "decision")

# Decision-driving list fields beyond `status`, by role: required present,
# must be a list, and each entry must be an object. Everything else
# (changed_files, tests, concerns, report, issues, findings, linter,
# cycle, ...) is informational and unvalidated (spec Sec 7 amendment).
DECISION_LIST_FIELDS = {
    "coder": ("duplication_pending", "new_shared_symbols"),
    "spec-reviewer": ("cannot_verify", "recurring", "issues"),
    "quality-reviewer": ("recurring", "findings"),
    "review-lite": ("findings",),
    "gate": ("findings",),
}

# Decision-driving list fields validated only when present (2026-10-06).
OPTIONAL_LIST_FIELDS = {
    "spec-reviewer": ("introduced_by_fix",),
    "quality-reviewer": ("introduced_by_fix",),
}

# Finding tags (schema 2). Every reviewer finding carries a severity, a
# reach, the rule it breaks, and the sites it was seen at; triage routes on
# severity and reach alone. Spec findings live in `issues`, the rest in
# `findings`.
FINDING_LIST_FIELD = {"spec-reviewer": "issues", "quality-reviewer": "findings",
                      "review-lite": "findings", "gate": "findings"}
MAX_SEVERITY = 5
SERIOUS_SEVERITY = 3
REACHES = ("local", "class", "contract")
# path, path:line, or path:start-end, relative to the repo toplevel.
SITE_RE = re.compile(r"^(?P<path>[^:\s][^:]*?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")
# A reviewer's status says whether it found anything serious.
SERIOUS_STATUS = {"spec-reviewer": "issues", "quality-reviewer": "issues"}
FLAG_FIELDS = ("recurring", "introduced_by_fix")
# A re-checking reviewer answers each contest it was sent.
CONTEST_VERDICTS = ("concede", "hold")

# Fix-loop fields (2026-08-28): a coder re-dispatched to fix findings
# self-derives `cycle` (prior record's cycle + 1, else 1); from cycle 2 a
# `diagnosis` is required — the fix must state its cause, not just patch
# sites. Keys are the slots reviewers verify the fix against.
DIAGNOSIS_KEYS = ("root_cause", "end_state", "resolves_cluster")
DIAGNOSIS_STATUSES = STATUS_ENUMS["coder"] - CODER_OPEN_STATUSES  # done, done_with_concerns

# Fix-mode fields (2026-10-06), required alongside `diagnosis`: a fix maps
# every hunk to the finding or decision-doc choice it implements, and
# lists the consumers it verified for each symbol whose signature or
# behavior it changed. Field -> keys each entry must carry as a non-empty
# string. consumers_checked entries also carry a `consumers` list.
FIX_MODE_FIELDS = {
    "hunk_map": ("site", "implements"),
    "consumers_checked": ("symbol", "verified"),
}

# Coder evidence (schema 2), each field optional and empty when unused.
# A sweep proves "no other site" with a search (a textual rule) or an
# itemized inspection (a rule no search expresses).
SEARCH_KEYS = ("command", "result")
INSPECTED_KEYS = ("target", "found_by")
# Why a serious finding gets no new failing test.
TESTS_FIRST_NA = ("structural", "docs", "unreachable", "existing")
TESTS_FIRST_RUN_KEYS = ("test", "command", "failed_output")
CONTEST_REASONS = ("wrong", "plan-conflict")
TEST_CHANGE_KINDS = ("changed", "deleted", "skipped")
# A root cause outside the brief names the code it traces to, first.
ROOT_CAUSE_PREFIX = "root cause:"
ROOT_CAUSE_RE = re.compile(r"^root cause:\s*(?P<site>\S+)\s+\S", re.I)

# Decision records (2026-10-09). A reviewer finding is an `issues` or
# `findings` entry, and a decision must account for every one: a choice
# or an exclusion with its reason. `cannot_verify` entries may be decided
# too, but aren't required. Each fix choice weighs at least two
# candidates, each citing the code it mirrors as path:line or
# path:start-end (relative to the repo toplevel). A coder's `concerns`
# entry (a root cause outside its brief) may be decided as well, so a
# researched decision can route its fix before any review has run.
FINDING_FIELDS = ("issues", "findings")
OPTIONAL_FINDING_FIELDS = ("cannot_verify",)
CONCERN_FIELD = "concerns"
CHOICE_KEYS = {"fix": ("reframe", "choice", "completeness"), "escalate": ("why", "evidence")}
CANDIDATE_KEYS = ("name", "precedent", "why")
# Every case names the site it lives at and the test that pins it; its
# `under_fix` is that test's expected result.
CASE_KEYS = ("case", "site", "test", "today", "under_fix", "result")
COUPLING_KEYS = ("site", "effect")
PREMISE_KEYS = ("assumption", "probe")
MIN_CANDIDATES = 2
# A record's scope is the prefix of its dispatch-supplied file name: one
# task, the whole-change gate, or that gate in a close-gate remediation run
# (final-r2-*). A decision covers the reviewer records of its own scope, so
# its file name carries its scope and cycle.
SCOPE_RE = re.compile(r"^(?P<scope>task-(?P<task>\d+)|final-r2|final)-")
DECISION_STEM_RE = re.compile(r"^(?P<scope>task-\d+|final-r2|final)-decision-c(?P<cycle>\d+)$")
# An escalated decision choice is open until the user's ruling resolves it.
ESCALATION_KIND = "escalation"
RULING_PREFIX = "user ruling:"
PRECEDENT_RE = re.compile(r"^(?P<path>[^:]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
# Coders run on sonnet. Opus only under the user's ruling for the task,
# logged as a progress note with this prefix.
CODER_MODEL = "sonnet"
OPUS_CODER_MODEL = "opus"
OPUS_RULING_PREFIX = f"{RULING_PREFIX} opus coder"

PROGRESS_FILENAME = "progress.jsonl"
# Every command that appends to or deletes from the store holds an
# exclusive flock on this file across its read, its checks and its write.
LOCK_FILENAME = ".lock"
# `append --type progress --task run` logs a ruling about the run as a whole.
RUN_SCOPE = "run"

# Orchestrator notes (2026-10-30): the run's cross-task knowledge as typed
# progress entries, so it reaches briefs, gates, resume and the report
# instead of living in a free-form notes file.
NOTE_KINDS = ("task-note", "run-note", "disclosure", "question", "follow-up",
              "disposition", "checkpoint")
# Owed by a task or by the close; each blocks its owner until resolved.
OWNED_NOTE_KINDS = ("disclosure", "question")
# Closed with `resolve`. A disposition is an audit entry and a checkpoint is
# superseded by the next one, so neither is ever open.
RESOLVABLE_NOTE_KINDS = frozenset({"task-note", "run-note", "follow-up", "disclosure", "question"})
CLOSE_OWNER = "close"
NOTE_ID_PREFIX = "note#"
# A coder's `concerns` entry for a case its brief's Cases: line didn't list.
UNLISTED_CASE_PREFIX = "unlisted case:"

# Per-cycle history (2026-10-08): records are overwritten each cycle, so a
# passing `check` appends one summary line per record here. `stats` reads it.
HISTORY_FILENAME = "history.jsonl"

# Close-gate rounds (2026-10-04): each run of verification-before-
# completion's review gates is one round. Round 1 is the first close;
# round 2 re-checks a batched remediation. Findings after the last round
# escalate to the user — a further round is refused, not counted.
CLOSE_ROUND_CAP = 2

# Process labels (2026-10-08): the run's own vocabulary leaking into code
# comments. ANYWHERE patterns are specific enough to flag on any added line;
# COMMENT_ONLY patterns (process words, short ids, hex runs) are ordinary in
# code and count only in comment or docstring text.
LABEL_PATTERNS_ANYWHERE = {
    "sdd-path": re.compile(r"\.sdd/"),
    "decision-doc": re.compile(r"\bdecision[- ]docs?\b", re.I),
    "reviewer-role": re.compile(r"\b(?:spec|quality)[- ]reviewers?\b|\breview-lite\b", re.I),
    "record-field": re.compile(r"\b(?:introduced_by_fix|hunk_map|consumers_checked)\b"),
    "fix-baseline": re.compile(r"\bfix baseline\b", re.I),
    "task-id": re.compile(r"\bT\d+'s\b"),
}
LABEL_PATTERNS_COMMENT_ONLY = {
    # Ordinary domain words in code (color cycles, schedulers, k8s).
    "orchestrator": re.compile(r"\borchestrator\b", re.I),
    "cycle": re.compile(r"\bcycle[- ]\d+\b", re.I),
    "task-number": re.compile(r"\btask[- ]\d+\b", re.I),
    "finding-id": re.compile(r"\([A-Z]\d{1,2}\)|#\d+ [A-Z]\d+\b"),
    # 7-40 hex chars with at least one digit and one letter; a leading `#`
    # (a color) or word char (0x..., identifiers) rules it out.
    "commit-hash": re.compile(r"(?<![#\w])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"),
}
# Prose may legitimately discuss the process; only code and tests are scanned.
LABEL_SKIPPED_SUFFIXES = (".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc")
# "* " and "*/" continue a block comment; a bare "*" starts a dereference.
COMMENT_PREFIXES = ("#", "//", "/*", "* ", "*/", "--", '"""', "'''", "<!--")
NOT_COMMENT_PREFIXES = ("#[", "#!")
TRAILING_COMMENT_RE = re.compile(r"\s(?:#|//)")
# Build files whose suffix would otherwise mark them as prose.
LABEL_SCANNED_NAMES = ("cmakelists.txt",)
# A docstring may carry a string prefix: r"""..., rb"""..., u"""...
DOCSTRING_OPEN_RE = re.compile(r"^[rRbBuUfF]{0,2}(?:\"\"\"|''')")
HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class RecordError(Exception):
    """A record violates the contract; message names field, value, allowed set."""


class UsageError(Exception):
    """A command was given an argument it can't use; the CLI exits 2."""


@dataclass
class Record:
    stem: str
    ok: bool
    error: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class OpenItem:
    id: str
    kind: str  # duplication_pending | cannot_verify | status | malformed
    summary: str
    source: str  # record stem it came from


@dataclass
class Shape:
    symbol: str
    path: str
    why: str
    source: str  # record stem it came from


@dataclass
class LabelHit:
    path: str
    line: int  # line number in the new file
    label: str
    text: str


def get_store_dir(override: str | None = None) -> Path:
    """--store override, else `.sdd/` at the repo toplevel. Does not create it.

    `git rev-parse --show-toplevel` resolves per-worktree, so each linked
    worktree gets its own store, and the path is in the working tree —
    never under `.git/`, whose contents tooling treats as off-limits."""
    if override is not None:
        return Path(override).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError("not inside a git repository; pass --store DIR") from e
    return (Path(out) / ".sdd").resolve()


def ensure_store(store_dir: Path) -> Path:
    """Create the store directory and seed a self-ignoring `.gitignore`
    (`*`) so its contents stay untracked without touching the repo's own
    ignore rules. Idempotent; never overwrites an existing `.gitignore`."""
    store_dir.mkdir(parents=True, exist_ok=True)
    gitignore = store_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    return store_dir


def validate_record(data: object) -> None:
    """Raise RecordError on the first contract violation found; used both
    at load time (per-record isolated) and by `check`."""
    if not isinstance(data, dict):
        raise RecordError("record is not a JSON object")

    missing = [f for f in ENVELOPE_FIELDS if f not in data]
    if missing:
        raise RecordError(f"missing required field(s): {', '.join(missing)}")
    if data["schema"] == 1 and _positive_int_value(data["schema"]):
        raise RecordError(SCHEMA_1_MESSAGE)
    if data["schema"] != SCHEMA_VERSION or isinstance(data["schema"], bool):
        raise RecordError(f"schema: got {data['schema']!r}, expected {SCHEMA_VERSION}")
    # Records are matched to tasks by value: a "1" would hide from task 1.
    if data["task"] != "final" and not _positive_int_value(data["task"]):
        raise RecordError(f"task: got {data['task']!r}, expected a positive integer or 'final'")

    role = data["role"]
    # isinstance guard, not a type table: role/status must be hashable
    # strings before a set-membership test is safe. An unhashable value
    # (e.g. a list) must raise this RecordError, not a bare TypeError.
    if not isinstance(role, str) or role not in VALID_ROLES:
        raise RecordError(f"role: got {role!r}, allowed set: {sorted(VALID_ROLES)}")

    if "status" not in data:
        raise RecordError("missing required field(s): status")
    status = data["status"]
    allowed_statuses = STATUS_ENUMS[role]
    if not isinstance(status, str) or status not in allowed_statuses:
        raise RecordError(
            f"status: got {status!r}, allowed set: {sorted(allowed_statuses)}")

    required = DECISION_LIST_FIELDS.get(role, ())
    for field_name in (*required, *OPTIONAL_LIST_FIELDS.get(role, ())):
        if field_name not in data:
            if field_name in required:
                raise RecordError(f"missing required field(s): {field_name}")
            continue
        value = data[field_name]
        if not isinstance(value, list):
            raise RecordError(
                f"{field_name}: got {value!r} (type {type(value).__name__}), "
                f"expected a list")
        for idx, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise RecordError(
                    f"{field_name}[{idx}]: got {entry!r}, expected an object")

    if role in CYCLE_ROLES:
        # Required: every fix-mode check keys off `cycle`, so a record that
        # omitted it would skip them all.
        if "cycle" not in data:
            raise RecordError("missing required field(s): cycle")
        cycle = data["cycle"]
        if not _positive_int_value(cycle):
            hint = ("1 on a first attempt, prior + 1 on a fix" if role == "coder"
                    else "the coder's upcoming fix cycle")
            raise RecordError(f"cycle: got {cycle!r}, expected a positive integer ({hint})")
    if role == "coder":
        # Optional here so records from before it existed still load; `check`
        # requires it (_check_coder_model).
        if "model" in data and not _non_empty_str(data["model"]):
            raise RecordError(f"model: got {data['model']!r}, expected a non-empty string")
        # Same for a fix's baseline: `check` requires it (_check_fix_baseline).
        if "baseline" in data and not _non_empty_str(data["baseline"]):
            raise RecordError(f"baseline: got {data['baseline']!r}, expected the "
                              "`Fix baseline:` tree from the dispatch")
        # Only a coder reporting a finished fix owes the fix-mode fields: one
        # that stopped mid-fix (blocked / needs_context) has fixed nothing yet.
        if data["cycle"] >= 2 and data["status"] in DIAGNOSIS_STATUSES:
            _validate_fix(data)
        _validate_coder_evidence(data)
    elif role == "decision":
        _validate_decision(data)
    if role in FINDING_LIST_FIELD:
        _validate_finding_tags(data, role)


def _optional_objects(data: dict, field_name: str) -> list[dict]:
    return _require_objects(data, field_name) if field_name in data else []


def _validate_search_evidence(entry: dict, where: str) -> None:
    """A `searched` command with its result, or a non-empty `inspected` list."""
    if "searched" in entry:
        searched = entry["searched"]
        if not isinstance(searched, dict):
            raise RecordError(f"{where}.searched: got {searched!r}, expected an object with "
                              f"{', '.join(SEARCH_KEYS)}")
        _require_strs(searched, SEARCH_KEYS, f"{where}.searched")
    elif entry.get("inspected"):
        for idx, item in enumerate(_require_objects(entry, "inspected")):
            _require_strs(item, INSPECTED_KEYS, f"{where}.inspected[{idx}]")
    else:
        raise RecordError(f"{where}: needs `searched` (the command and its result) or "
                          "`inspected` (what was examined and how it was found)")


def _validate_coder_evidence(data: dict) -> None:
    """The evidence fields a coder writes when it fixes, declares, contests,
    or changes a test. Shape only; what they must cover is checked by
    `check_record` against the store and the diff."""
    for idx, sweep in enumerate(_optional_objects(data, "sweeps")):
        where = f"sweeps[{idx}]"
        findings = sweep.get("findings")
        if not isinstance(findings, list) or not findings or not all(map(_non_empty_str, findings)):
            raise RecordError(f"{where}.findings: got {findings!r}, expected a non-empty list of "
                              "finding ids")
        _require_strs(sweep, ("rule",), where)
        for r_idx, row in enumerate(_require_objects(sweep, "rows", min_len=1)):
            row_where = f"{where}.rows[{r_idx}]"
            _validate_site(row.get("site"), f"{row_where}.site")
            if "hunk" in row:
                _validate_site(row["hunk"], f"{row_where}.hunk")
            elif not _non_empty_str(row.get("already_correct")):
                raise RecordError(f"{row_where}: needs the `hunk` that fixes it, or "
                                  "`already_correct` with evidence")
        _validate_search_evidence(sweep, where)
        sites_outside = sweep.get("sites_outside", [])
        if not isinstance(sites_outside, list):
            raise RecordError(f"{where}.sites_outside: got {sites_outside!r}, expected a list")
        for s_idx, site in enumerate(sites_outside):
            _validate_site(site, f"{where}.sites_outside[{s_idx}]")
    for idx, entry in enumerate(_optional_objects(data, "tests_first")):
        where = f"tests_first[{idx}]"
        _require_strs(entry, ("finding",), where)
        if "n/a" not in entry:
            _require_strs(entry, TESTS_FIRST_RUN_KEYS, where)
            continue
        if entry["n/a"] not in TESTS_FIRST_NA:
            raise RecordError(f"{where}.n/a: got {entry['n/a']!r}, allowed set: "
                              f"{list(TESTS_FIRST_NA)}")
        _require_strs(entry, ("reason", "test") if entry["n/a"] == "existing" else ("reason",),
                      where)
    for idx, entry in enumerate(_optional_objects(data, "open")):
        where = f"open[{idx}]"
        _require_strs(entry, ("question", "choice"), where)
        if "precedent" in entry:
            _validate_site(entry["precedent"], f"{where}.precedent")
        elif not _non_empty_str(entry.get("no_precedent")):
            raise RecordError(f"{where}: needs the `precedent` site it follows, or "
                              "`no_precedent` with the reasoning")
    for idx, entry in enumerate(_optional_objects(data, "contested")):
        _require_strs(entry, ("finding", "evidence"), f"contested[{idx}]")
        if entry.get("reason") not in CONTEST_REASONS:
            raise RecordError(f"contested[{idx}].reason: got {entry.get('reason')!r}, "
                              f"allowed set: {list(CONTEST_REASONS)}")
    for idx, entry in enumerate(_optional_objects(data, "reach_raised")):
        _require_strs(entry, ("finding", "evidence"), f"reach_raised[{idx}]")
    for idx, entry in enumerate(_optional_objects(data, "notes_skipped")):
        _require_strs(entry, ("finding", "reason"), f"notes_skipped[{idx}]")
    for idx, entry in enumerate(_optional_objects(data, "test_changes")):
        _require_strs(entry, ("test", "reason"), f"test_changes[{idx}]")
        if entry.get("kind") not in TEST_CHANGE_KINDS:
            raise RecordError(f"test_changes[{idx}].kind: got {entry.get('kind')!r}, "
                              f"allowed set: {list(TEST_CHANGE_KINDS)}")
    for idx, entry in enumerate(_optional_objects(data, "decision_rows")):
        where = f"decision_rows[{idx}]"
        for key in ("choice", "case"):
            value = entry.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RecordError(f"{where}.{key}: got {value!r}, expected an index from 0")
        _validate_site(entry.get("hunk"), f"{where}.hunk")
    if "decision" in data and not _non_empty_str(data["decision"]):
        raise RecordError(f"decision: got {data['decision']!r}, expected this round's "
                          "decision doc path")
    for concern in data.get(CONCERN_FIELD, []):
        if (isinstance(concern, str) and concern.lower().startswith(ROOT_CAUSE_PREFIX)
                and root_cause_path(concern) is None):
            raise RecordError(f"concerns: {concern!r}: a root cause starts with the path it "
                              "names: 'root cause: <path>[:<line>] <evidence>'")


def root_cause_path(concern: str) -> str | None:
    """The path a `root cause:` concern names first, or None when its first
    token isn't a file path (one with a directory or an extension)."""
    match = ROOT_CAUSE_RE.match(concern)
    site = SITE_RE.match(match["site"]) if match else None
    if site is None or not ("/" in site["path"] or "." in site["path"]):
        return None
    return site["path"]


def _validate_site(site: object, where: str) -> None:
    match = SITE_RE.match(site) if isinstance(site, str) else None
    if match is None or (match["start"] is not None and (
            int(match["start"]) < 1
            or (match["end"] is not None and int(match["end"]) < int(match["start"])))):
        raise RecordError(f"{where}: got {site!r}, expected path, path:line, or "
                          "path:start-end (lines from 1, start <= end)")


def _validate_finding_tags(data: dict, role: str) -> None:
    """Each finding's severity, reach, rule and sites; the status agrees with
    whether any finding is serious; every recurring/introduced_by_fix flag
    points at a site some finding names; contest answers are well-formed."""
    field_name = FINDING_LIST_FIELD[role]
    sites_seen: set[str] = set()
    serious = False
    for idx, entry in enumerate(data[field_name]):
        where = f"{field_name}[{idx}]"
        severity = entry.get("severity")
        if not _positive_int_value(severity) or severity > MAX_SEVERITY:
            raise RecordError(f"{where}.severity: got {severity!r}, expected an integer 1-5")
        if entry.get("reach") not in REACHES:
            raise RecordError(f"{where}.reach: got {entry.get('reach')!r}, "
                              f"allowed set: {list(REACHES)}")
        _require_strs(entry, ("rule",), where)
        sites = entry.get("sites")
        if not isinstance(sites, list) or not sites:
            raise RecordError(f"{where}.sites: got {sites!r}, expected a non-empty list of sites")
        for site_idx, site in enumerate(sites):
            _validate_site(site, f"{where}.sites[{site_idx}]")
        sites_seen.update(sites)
        if role == "spec-reviewer" and "case" in entry:
            _require_strs(entry, ("case",), where)
            if severity < SERIOUS_SEVERITY:
                raise RecordError(f"{where}: names the listed case {entry['case']!r} at "
                                  f"severity {severity}; a missed listed case is "
                                  f"severity {SERIOUS_SEVERITY} or higher")
        if "reopens" in entry:
            _require_strs(entry, ("reopens",), where)
        serious = serious or severity >= SERIOUS_SEVERITY
    if role in SERIOUS_STATUS and (data["status"] == SERIOUS_STATUS[role]) != serious:
        expected = SERIOUS_STATUS[role] if serious else "the passing status"
        raise RecordError(f"status: got {data['status']!r} with "
                          f"{'a' if serious else 'no'} finding of severity "
                          f"{SERIOUS_SEVERITY}+; expected {expected}")
    for flag in FLAG_FIELDS:
        for idx, entry in enumerate(data.get(flag, [])):
            if entry.get("site") not in sites_seen:
                raise RecordError(f"{flag}[{idx}].site: got {entry.get('site')!r}, which no "
                                  f"{field_name} entry lists in its sites")
    # Present only on a re-check that was sent contests.
    for idx, entry in enumerate(_require_objects(data, "contests") if "contests" in data else []):
        where = f"contests[{idx}]"
        _require_strs(entry, ("finding", "reason"), where)
        if entry.get("verdict") not in CONTEST_VERDICTS:
            raise RecordError(f"{where}.verdict: got {entry.get('verdict')!r}, "
                              f"allowed set: {list(CONTEST_VERDICTS)}")


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int_value(value: object) -> bool:
    # bool is an int subclass; True would silently read as 1.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _require_strs(entry: dict, keys: tuple[str, ...], where: str) -> None:
    for key in keys:
        if not _non_empty_str(entry.get(key)):
            raise RecordError(f"{where}.{key}: got {entry.get(key)!r}, expected a non-empty string")


def _require_objects(data: dict, field_name: str, min_len: int = 0) -> list[dict]:
    value = data.get(field_name)
    if not isinstance(value, list):
        raise RecordError(f"{field_name}: got {value!r}, expected a list")
    if len(value) < min_len:
        raise RecordError(f"{field_name}: got {len(value)} entries, expected at least {min_len}")
    for idx, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RecordError(f"{field_name}[{idx}]: got {entry!r}, expected an object")
    return value


def _validate_decision(data: dict) -> None:
    """A decision record's own shape: the reviewer records it answers, a
    defended choice (or an escalation) per finding cluster, exclusions
    with reasons, and its reconciliation with the run's other decisions.
    What it must cover in the store is checked by `check_record`."""
    stems = data.get("reviewer_records")
    if not isinstance(stems, list) or not all(map(_non_empty_str, stems)):
        raise RecordError(f"reviewer_records: got {stems!r}, expected a list of record "
                          "names (e.g. task-3-spec-reviewer; empty before any review)")
    seen: set[str] = set()
    escalated = False
    # A decision may only exclude: a round started for a lone root cause the
    # engine defers has nothing to choose.
    min_choices = 0 if data.get("excluded") else 1
    for idx, choice in enumerate(_require_objects(data, "choices", min_len=min_choices)):
        where = f"choices[{idx}]"
        kind = choice.get("kind")
        if not isinstance(kind, str) or kind not in CHOICE_KEYS:
            raise RecordError(f"{where}.kind: got {kind!r}, allowed set: {sorted(CHOICE_KEYS)}")
        findings = choice.get("findings")
        if not isinstance(findings, list) or not findings or not all(map(_non_empty_str, findings)):
            raise RecordError(f"{where}.findings: got {findings!r}, expected a non-empty list "
                              "of finding ids (from `ledger.py findings`)")
        _claim_findings(findings, seen, where)
        _require_strs(choice, CHOICE_KEYS[kind], where)
        if kind == "escalate":
            escalated = True
        else:
            _validate_candidates(choice, where)
            _validate_cases_and_couplings(choice, where)
    for idx, entry in enumerate(_require_objects(data, "excluded")):
        _require_strs(entry, ("finding", "reason"), f"excluded[{idx}]")
        _claim_findings([entry["finding"]], seen, f"excluded[{idx}]")
    for idx, entry in enumerate(_require_objects(data, "reconciled")):
        _require_strs(entry, ("decision", "relation"), f"reconciled[{idx}]")
    expected = "escalated" if escalated else "decided"
    if data["status"] != expected:
        raise RecordError(f"status: got {data['status']!r}, expected {expected!r} "
                          "(escalated exactly when a choice has kind 'escalate')")


def _claim_findings(findings: list[str], seen: set[str], where: str) -> None:
    for finding in findings:
        if finding in seen:
            raise RecordError(f"{where}: {finding!r} is accounted for twice")
        seen.add(finding)


def _validate_cases_and_couplings(choice: dict, where: str) -> None:
    """Each case has a site and a test; each coupling the choice touches is
    also a case, so a named coupling is always tested; the premise records
    what the choice assumes and how that was confirmed."""
    case_sites = set()
    for idx, case in enumerate(_require_objects(choice, "cases", min_len=1)):
        _require_strs(case, CASE_KEYS, f"{where}.cases[{idx}]")
        _validate_site(case["site"], f"{where}.cases[{idx}].site")
        case_sites.add(case["site"])
    for idx, coupling in enumerate(_require_objects(choice, "couplings")):
        _require_strs(coupling, COUPLING_KEYS, f"{where}.couplings[{idx}]")
        if coupling["site"] not in case_sites:
            raise RecordError(f"{where}.couplings[{idx}].site: {coupling['site']!r} is a coupling "
                              "no case covers; add a case with its test")
    premise = choice.get("premise")
    if not isinstance(premise, dict):
        raise RecordError(f"{where}.premise: got {premise!r}, expected an object with "
                          f"{', '.join(PREMISE_KEYS)}")
    _require_strs(premise, PREMISE_KEYS, f"{where}.premise")


def _validate_candidates(choice: dict, where: str) -> None:
    """At least MIN_CANDIDATES, each with a precedent, exactly one chosen."""
    candidates = _require_objects(choice, "candidates", min_len=MIN_CANDIDATES)
    for idx, candidate in enumerate(candidates):
        _require_strs(candidate, CANDIDATE_KEYS, f"{where}.candidates[{idx}]")
        if not PRECEDENT_RE.match(candidate["precedent"]):
            raise RecordError(f"{where}.candidates[{idx}].precedent: got "
                              f"{candidate['precedent']!r}, expected path:line or "
                              "path:start-end citing the code this candidate mirrors")
    chosen = [c for c in candidates if c.get("chosen") is True]
    if len(chosen) != 1:
        raise RecordError(f"{where}.candidates: {len(chosen)} marked \"chosen\": true, "
                          "expected exactly one")


def _validate_fix(data: dict) -> None:
    """A finished fix's record: `diagnosis` (its cause) plus the fix-mode
    fields (FIX_MODE_FIELDS), each entry carrying its keys as non-empty
    strings."""
    diagnosis = data.get("diagnosis")
    if not isinstance(diagnosis, dict):
        raise RecordError(
            "diagnosis: required from cycle 2 — a fix must state its "
            f"cause, not just patch sites; expected an object with "
            f"{', '.join(DIAGNOSIS_KEYS)}, got {diagnosis!r}")
    for key in DIAGNOSIS_KEYS:
        if not _non_empty_str(diagnosis.get(key)):
            raise RecordError(
                f"diagnosis.{key}: got {diagnosis.get(key)!r}, expected a "
                "non-empty string")

    for field_name, keys in FIX_MODE_FIELDS.items():
        entries = data.get(field_name)
        if not isinstance(entries, list):
            raise RecordError(
                f"{field_name}: required from cycle 2 on a finished fix; expected "
                f"a list of objects with {', '.join(keys)}, got {entries!r}")
        if field_name == "hunk_map" and not entries and _claims_a_hunk(data):
            raise RecordError(
                "hunk_map: the record claims hunks (sweep rows or decision_rows), so "
                "map each one; got an empty list")
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise RecordError(f"{field_name}[{idx}]: got {entry!r}, expected an object")
            for key in keys:
                if not _non_empty_str(entry.get(key)):
                    raise RecordError(
                        f"{field_name}[{idx}].{key}: got {entry.get(key)!r}, "
                        "expected a non-empty string")
            if field_name == "consumers_checked" and not isinstance(entry.get("consumers"), list):
                raise RecordError(
                    f"consumers_checked[{idx}].consumers: got {entry.get('consumers')!r}, "
                    "expected a list (empty when the symbol has no consumers)")
            # "No consumers" is a negative claim: it carries the search behind it.
            if field_name == "consumers_checked" and not entry["consumers"]:
                _validate_search_evidence(entry, f"consumers_checked[{idx}]")


def _claims_a_hunk(data: dict) -> bool:
    """Whether a fix says it changed code: a sweep row with a hunk, or a
    decision case mapped to one. A round whose findings were all contested,
    raised or skipped, or a polish that changed nothing, claims none."""
    rows = [row for sweep in data.get("sweeps", []) if isinstance(sweep, dict)
            for row in sweep.get("rows", []) if isinstance(row, dict)]
    return any("hunk" in row for row in rows) or bool(data.get("decision_rows"))


def load_records(store_dir: Path) -> list[Record]:
    """One Record per *.json file. A missing store dir is an empty list,
    not an error — an empty store is a valid, empty history. store_dir is
    required (not defaulted) so a caller can't accidentally combine
    records from one store with resolutions or shapes from another."""
    if not store_dir.is_dir():
        return []
    return [_load_record(path) for path in sorted(store_dir.glob("*.json"))]


def _parse_record_file(path: Path) -> dict:
    """Read, strict-parse, and validate one record file, raising RecordError
    with the path named. The single pipeline behind both query-time loading
    and the write-time `check` gate — shared so "passes `check`" and "parses
    at query time" are structurally the same test, not two copies that
    happen to agree."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RecordError(f"cannot read {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RecordError(f"invalid JSON in {path}: {e}") from e
    validate_record(data)
    return data


def _load_record(path: Path) -> Record:
    # Every failure mode is caught right here, so one bad file becomes one
    # malformed Record instead of crashing the caller's whole query
    # (per-record isolation — one bad file must never hide its siblings).
    stem = path.stem
    try:
        data = _parse_record_file(path)
    except Exception as e:
        return Record(stem, ok=False, error=str(e))
    return Record(stem, ok=True, data=data)


def load_progress_log(store_dir: Path) -> list[dict]:
    """Parse progress.jsonl; a malformed or unreadable line raises
    RecordError. Loud failure, not skip-with-warning (user ruling
    2026-08-27): this log feeds resolve's already-resolved gate, so a
    silently dropped resolution line would silently re-open an item.
    store_dir is required (not defaulted), same as load_records/list_shapes/
    compute_open_items, so it's always sourced from an explicit store."""
    path = store_dir / PROGRESS_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RecordError(f"cannot read {path}: {e}") from e
    entries = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as e:
            raise RecordError(f"malformed {path} line {lineno}: {e}") from e
        if not isinstance(parsed, dict):
            raise RecordError(f"malformed {path} line {lineno}: not a JSON object")
        entries.append(parsed)
    return entries


def resolutions_from_log(log: list[dict]) -> dict[str, str]:
    """Every resolution entry's id -> note. `open` needs only the id set
    (`set(resolutions_from_log(log))`); `resolve`'s already-resolved
    corrective message needs the note too — one scan of the log serves
    both instead of each keeping its own near-identical loop."""
    return {entry["resolves"]: entry.get("note", "") for entry in log
            if entry.get("type") == "resolution" and isinstance(entry.get("resolves"), str)}


@contextlib.contextmanager
def store_lock(store_dir: Path) -> Iterator[None]:
    """Hold the store's exclusive lock: a mutating command's read, checks
    and append happen as one step, so two writers can neither interleave
    lines nor both pass a check only one of them should. Only an existing
    store (one `ensure_store` seeded) is locked: locking must not create
    or seed anything, so a refusal writes nothing and a directory that
    isn't a store is never touched. A store doesn't exist until its first
    append (normally the session's `store-dir`), so that write alone runs
    unlocked."""
    if not _is_store(store_dir):
        yield
        return
    with (store_dir / LOCK_FILENAME).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _append_progress(store_dir: Path, entry: dict) -> None:
    """Append one entry to the progress log, seeding the store on its first
    write: the only point where a command creates the store."""
    ensure_store(store_dir)
    _append_jsonl(store_dir / PROGRESS_FILENAME, entry)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_jsonl(path: Path, entry: dict) -> None:
    # Guard against merging with a final line lacking a trailing newline
    # (e.g. a truncated or hand-edited file), which would corrupt both.
    needs_newline = False
    if path.is_file() and path.stat().st_size > 0:
        with path.open("rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")


def compute_open_items(
    records: list[Record],
    resolved_ids: set[str],
) -> list[OpenItem]:
    """Every unresolved item. Only entry-level kinds are resolvable;
    status/malformed items always appear regardless of resolutions. Both
    arguments are required (not defaulted) so a partially-defaulted call
    can't silently mix records from one store with resolutions from
    another — callers compute and pass both from the same store_dir."""
    items = [item for rec in records for item in _open_items_for_record(rec)]
    return [item for item in items
            if item.kind not in RESOLVABLE_KINDS or item.id not in resolved_ids]


def _open_items_for_record(rec: Record) -> list[OpenItem]:
    if not rec.ok:
        return [OpenItem(id=f"{rec.stem}#malformed", kind="malformed",
                          summary=rec.error, source=rec.stem)]
    # Isolation must cover item *construction*, not just load-time
    # validation: an informational sub-field (e.g. a non-string entry in
    # duplication_pending[].sites) passes validate_record but can still
    # blow up str.join here. Catching per record — instead of just
    # per file at _load_record — keeps that failure from taking down
    # every other record's items in the same `open` call.
    try:
        return _build_open_items(rec)
    except Exception as e:
        return [OpenItem(id=f"{rec.stem}#malformed", kind="malformed",
                          summary=f"error building open items: {e}", source=rec.stem)]


def _entry_digest(entry: dict | str) -> str:
    """First 8 hex of the sha1 of the entry's canonical JSON — the
    content-derived component of an entry-level id (spec Sec 6, amended
    2026-08-27): a resolution id names *what the entry says*, not *where
    it sits*, so a record rewritten with a different entry at the same
    position gets a new id and the old resolution can't suppress it."""
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]


def _item_id(stem: str, field_name: str, entry: dict | str) -> str:
    """An entry-level id: the record, the field, and the entry's digest."""
    return f"{stem}#{field_name}[{_entry_digest(entry)}]"


def _describe_duplication(entry: dict) -> str:
    sites = ", ".join(entry.get("sites", []))
    return (f"sites=[{sites}] wants_owner={entry.get('wants_owner', '')} "
            f"why={entry.get('why', '')}")


def _describe_cannot_verify(entry: dict) -> str:
    return (f"{entry.get('requirement', '')} — {entry.get('why', '')} "
            f"(should_check: {entry.get('should_check', '')})")


_FIELD_DESCRIBERS = {
    "duplication_pending": _describe_duplication,
    "cannot_verify": _describe_cannot_verify,
}

# The resolvable kinds are exactly the fields with a describer — derived,
# never restated, so a kind cannot exist in one table and not the other.
# Whole-record items (status, malformed) are state, not work items: they
# clear only when the record is rewritten, never via `resolve` — otherwise
# a stale resolution could suppress a later, different problem at the same
# id (spec Sec 6 amended `open` semantics).
RESOLVABLE_KINDS = frozenset(_FIELD_DESCRIBERS) | {ESCALATION_KIND}


def _build_open_items(rec: Record) -> list[OpenItem]:
    role, status = rec.data["role"], rec.data["status"]
    items: list[OpenItem] = []
    is_open_status = (
        (role == "coder" and status in CODER_OPEN_STATUSES)
        or (role != "coder" and status in REVIEWER_OPEN_STATUSES)
    )
    if is_open_status:
        items.append(OpenItem(id=f"{rec.stem}#status", kind="status",
                               summary=f"{role} status: {status}", source=rec.stem))

    # Entry-level items are read only from fields the per-role validation
    # table (DECISION_LIST_FIELDS) actually requires for this record's
    # role, filtered to the kinds that are open-item-producing
    # (RESOLVABLE_KINDS) rather than shape-producing (new_shared_symbols).
    # A field an unvalidated role happens to carry (e.g. a stray
    # duplication_pending on a spec-reviewer record) is never read: it
    # was never validated, so it must never drive an open item either.
    seen_ids: set[str] = set()
    for field_name in DECISION_LIST_FIELDS.get(role, ()):
        describe = _FIELD_DESCRIBERS.get(field_name)
        if describe is None:  # shape-producing field (new_shared_symbols), not an open item
            continue
        for entry in rec.data.get(field_name, []):
            item_id = _item_id(rec.stem, field_name, entry)
            if item_id in seen_ids:
                # Two entries with identical content hash to the same id
                # (spec Sec 6: ids are content-derived) — they're one
                # claim, not two, so they print as one line and resolve
                # with one `resolve` call, not a silently-doubled report.
                continue
            try:
                summary = describe(entry)
            except Exception as e:
                # Names the offending sub-field, not just "something in
                # this record failed to render" — the error is `check`'s
                # correction (spec Sec 7).
                raise RuntimeError(f"{field_name} entry {entry!r} failed to render: {e}") from e
            seen_ids.add(item_id)
            items.append(OpenItem(id=item_id, kind=field_name, summary=summary, source=rec.stem))

    if role == "decision" and _scope(rec.stem) in _task_scopes("final"):
        # Waiting on the user: open until `resolve` logs the ruling. A task's
        # own decision escalates through its coder's contest instead, which
        # the raising reviewer concedes or holds for the user.
        for choice in rec.data["choices"]:
            if choice["kind"] == "escalate":
                items.append(OpenItem(
                    id=_item_id(rec.stem, ESCALATION_KIND, choice), kind=ESCALATION_KIND,
                    summary=f"{', '.join(choice['findings'])}: {choice['why']}",
                    source=rec.stem))
    return items


def list_shapes(records: list[Record]) -> list[Shape]:
    """new_shared_symbols entries across well-formed coder records. Never
    included in `open` — shapes are advisory, not work items. records is
    required (not defaulted) so it's always sourced from an explicit
    store_dir, same as load_records and compute_open_items."""
    shapes = []
    for rec in records:
        if not rec.ok or rec.data.get("role") != "coder":
            continue
        for entry in rec.data.get("new_shared_symbols", []):
            shapes.append(Shape(entry.get("symbol", ""), entry.get("path", ""),
                                 entry.get("why", ""), rec.stem))
    return shapes


def render_shapes(shapes: list[Shape]) -> str:
    """Empty input renders as a placeholder, never blank — spec Sec 6:
    no flag disables the shared-shapes section."""
    if not shapes:
        return "(none recorded yet)"
    lines = []
    for s in shapes:
        why = f" — {s.why}" if s.why else ""
        lines.append(f"- `{s.symbol}` ({s.path}){why}  [{s.source}]")
    return "\n".join(lines)


def render_store_markdown(records: list[Record], log: list[dict]) -> str:
    lines = ["# SDD Ledger", "", "## Records"]
    if not records:
        lines += ["", "(none)"]
    for rec in records:
        lines.append("")
        if not rec.ok:
            lines += [f"### {rec.stem} — MALFORMED", f"- error: {rec.error}"]
            continue
        data = rec.data
        lines.append(f"### {rec.stem}  (role: {data['role']}, task: {data['task']}, "
                      f"status: {data['status']})")
        lines.append("```json")
        lines.append(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        lines.append("```")

    lines += ["", "## Progress log"]
    if not log:
        lines += ["", "(none)"]
    for entry in log:
        lines.append("")
        if entry.get("type") == "progress" and entry.get("task") == RUN_SCOPE:
            lines.append(f"- run: {entry.get('note', '')}")
        elif entry.get("type") == "progress":
            lines.append(f"- task {entry.get('task')}: {entry.get('note', '')}")
        elif entry.get("type") == "complete":
            lines.append(f"- task {entry.get('task')} **COMPLETE**: {entry.get('note', '')}")
        elif entry.get("type") == "resolution":
            lines.append(f"- resolves `{entry.get('resolves')}`: {entry.get('note', '')}")
        elif entry.get("type") == "snapshot":
            lines.append(f"- task {entry.get('task')} snapshot `{entry.get('tree')}`: "
                          f"{entry.get('label', '')}")
        elif entry.get("type") == "close_round":
            lines.append(f"- **close round {entry.get('round')}** at `{entry.get('head', '')}`: "
                          f"{entry.get('note', '')}")
        elif entry.get("type") == TRIAGE_ENTRY:
            lines.append(f"- {_scope_name(entry.get('task'))} triage: {entry.get('kind')} "
                          f"(round {entry.get('round')}, recheck {entry.get('recheck')})")
        elif entry.get("type") == "note":
            lines.append(f"- note `{entry.get('id')}` {_describe_note(entry)}")
        elif entry.get("type") == "delivery":
            ids = ", ".join(f"`{n}`" for n in entry.get("notes", [])) or "(none)"
            lines.append(f"- task {entry.get('task')} received notes via "
                          f"{entry.get('via')}: {ids}")
        elif entry.get("type") == "stage" and entry.get("task") == "final":
            lines.append(f"- the whole-change gate's footprint adds: "
                          f"{', '.join(entry.get('files', []))}")
        elif entry.get("type") == "stage":
            lines.append(f"- task {entry.get('task')} in stage {entry.get('stage')}: "
                          f"{', '.join(entry.get('files', []))}")
        elif entry.get("type") == "handle":
            lines.append(f"- task {entry.get('task')} {entry.get('role')} is agent "
                          f"`{entry.get('agent')}`")
        elif entry.get("type") == "waiver":
            lines.append(f"- task {entry.get('task')} waived `{entry.get('note')}`: "
                          f"{entry.get('reason', '')}")
        elif entry.get("type") == "plan":
            lines.append(f"- plan `{entry.get('path')}`")
        else:
            lines.append(f"- unknown entry: {entry}")
    return "\n".join(lines)


def completed_task_ids(log: list[dict]) -> list[str]:
    """Task ids with a typed `"type": "complete"` entry in progress.jsonl,
    in first-seen order, deduplicated. The machine-readable answer to
    "what's done" — post-compaction recovery queries this instead of
    pattern-matching a prose note in rendered markdown (spec Sec 6,
    amended 2026-08-27)."""
    return list(dict.fromkeys(
        str(entry.get("task")) for entry in log if entry.get("type") == "complete"))


def recorded_plans(log: list[dict]) -> list[str]:
    """The plans this store has run, in the order first recorded."""
    return list(dict.fromkeys(e["path"] for e in log
                              if e.get("type") == "plan" and isinstance(e.get("path"), str)))


def plan_key(store_dir: Path, plan: str, base: Path | None = None) -> str:
    """A plan's identity in the store: its path relative to the store's repo
    toplevel, POSIX-style, so `./x.md`, `x.md` and the absolute path are one
    plan. A relative path resolves against `base` (default: the current
    directory). A plan outside the repo keeps its absolute path."""
    path = Path(plan)
    resolved = (path if path.is_absolute() else (base or Path.cwd()) / path).resolve()
    repo = _store_repo(store_dir)
    if repo is not None:
        try:
            return resolved.relative_to(repo.resolve()).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def record_plan(store_dir: Path, plan: str) -> None:
    """Log the plan a brief was built from, once per plan."""
    key = plan_key(store_dir, plan)
    with store_lock(store_dir):
        if key not in recorded_plans(load_progress_log(store_dir)):
            _append_progress(store_dir, {"type": "plan", "path": key, "at": _now()})


def store_verdict(store_dir: Path, plan: str | None) -> tuple[str, str]:
    """`store_state.classify`'s verdict and next action for `plan` (default:
    the latest recorded plan), from the facts the progress log holds."""
    log = load_progress_log(store_dir)
    plans = recorded_plans(log)
    repo = _store_repo(store_dir)
    if plan is not None:
        if not Path(plan).is_file():
            raise UsageError(f"--plan {plan}: no such file")
        key: str | None = plan_key(store_dir, plan)
        plan_file: Path | None = Path(plan)
    else:
        key = plans[-1] if plans else None
        plan_file = None if key is None else (Path(key) if Path(key).is_absolute()
                                              else (repo or Path.cwd()) / key)
    tasks = _plan_tasks(plan_file) if plan_file is not None and plan_file.is_file() else []
    notes = [store_state.parse_remediation_note(str(e.get("note", ""))) for e in log
             if e.get("type") == "progress" and e.get("task") == "final"]
    remediation = next((n for n in reversed(notes) if n is not None), None)
    if remediation is not None:
        remediation = {**remediation,
                       "plan": plan_key(store_dir, remediation["plan"], base=repo)}
    return store_state.classify(
        has_entries=bool(log), plans=plans, plan=key,
        plan_first_index=next((i for i, e in enumerate(log) if e.get("type") == "plan"
                               and e.get("path") == key), None),
        completed=set(completed_task_ids(log)), plan_tasks=tasks,
        close_round_indices=[i for i, e in enumerate(log) if e.get("type") == "close_round"],
        remediation=remediation)


def _plan_tasks(plan_file: Path) -> list[int]:
    # Imported here: task_brief imports this module, so a module-level
    # import would be a cycle.
    import task_brief
    return task_brief.plan_task_numbers(plan_file.read_text(encoding="utf-8"))


def close_rounds(log: list[dict]) -> int:
    """How many close-gate rounds have started in this store — a typed
    count, so the round cap survives compaction instead of living in the
    orchestrator's memory."""
    return sum(1 for entry in log if entry.get("type") == "close_round")


def note_id(kind: str, text: str, for_task: int | None = None, owner: int | str | None = None,
            source: int | str | None = None) -> str:
    """A note's content-derived id: the same note filed twice is one note."""
    content: dict = {"kind": kind, "text": text}
    for key, value in (("for", for_task), ("owner", owner), ("from", source)):
        if value is not None:
            content[key] = value
    return f"{NOTE_ID_PREFIX}{kind}[{_entry_digest(content)}]"


def notes_from_log(log: list[dict]) -> list[dict]:
    return [e for e in log if e.get("type") == "note" and isinstance(e.get("id"), str)]


def open_notes(log: list[dict]) -> list[dict]:
    """Notes still owed: unresolved, of a resolvable kind, and, for a
    task-note, aimed at a task that hasn't completed (completing the target
    closes it)."""
    resolved = set(resolutions_from_log(log))
    done = set(completed_task_ids(log))
    return [n for n in notes_from_log(log)
            if n.get("kind") in RESOLVABLE_NOTE_KINDS and n["id"] not in resolved
            and not (n.get("kind") == "task-note" and str(n.get("for")) in done)]


def required_notes(log: list[dict], task: int) -> list[dict]:
    """The notes `task` must receive before it completes: its open
    task-notes, every active run-note, and the open disclosures it owns.
    Questions it owns block it too, but go to the user, never the coder. A
    completed task requires nothing."""
    if str(task) in set(completed_task_ids(log)):
        return []
    return [n for n in open_notes(log)
            if (n.get("kind") == "task-note" and n.get("for") == task)
            or n.get("kind") == "run-note"
            or (n.get("kind") == "disclosure" and n.get("owner") == task)]


def delivered_note_ids(log: list[dict], task: int) -> set[str]:
    """Ids a delivery for `task` listed (a brief or the session), plus the
    ones waived for it."""
    ids: set[str] = set()
    for e in log:
        if e.get("task") != task:
            continue
        if e.get("type") == "delivery" and isinstance(e.get("notes"), list):
            ids.update(n for n in e["notes"] if isinstance(n, str))
        elif e.get("type") == "waiver" and isinstance(e.get("note"), str):
            ids.add(e["note"])
    return ids


def undelivered_notes(log: list[dict], task: int) -> list[dict]:
    delivered = delivered_note_ids(log, task)
    return [n for n in required_notes(log, task) if n["id"] not in delivered]


def owned_open_notes(log: list[dict], owner: int | str | None = None) -> list[dict]:
    """Open disclosures and questions, those of one owner when given."""
    return [n for n in open_notes(log) if n.get("kind") in OWNED_NOTE_KINDS
            and (owner is None or n.get("owner") == owner)]


def tasks_in_flight(log: list[dict], records: list[Record]) -> list[int]:
    """Numbered tasks that have started (a delivery, snapshot, handle or
    record names them) and not completed."""
    started = {e["task"] for e in log if e.get("type") in ("delivery", "snapshot", "handle")
               and _positive_int_value(e.get("task"))}
    started |= {rec.data["task"] for rec in records
                if rec.ok and _positive_int_value(rec.data.get("task"))}
    done = set(completed_task_ids(log))
    return sorted(t for t in started if str(t) not in done)


def record_delivery(store_dir: Path, task: int, ids: list[str], via: str) -> None:
    """Log that `task` received the notes `ids` (via "brief" or "session")."""
    with store_lock(store_dir):
        _append_progress(store_dir,
                      {"type": "delivery", "task": task, "notes": list(ids), "via": via,
                       "at": _now()})


def cmd_notes(store_dir: Path, task: int, deliver: bool = False, waive: str | None = None,
              reason: str | None = None) -> None:
    """Print the notes `task` must receive, marked delivered or not, and the
    questions it owns. `deliver` records the session delivering every one
    of them; `waive` records one that doesn't apply, with its reason."""
    if reason is not None and waive is None:
        raise RecordError("--reason goes with --waive ID")
    if waive is not None:
        if not _non_empty_str(reason):
            raise RecordError("a waiver needs --reason saying why the note doesn't apply "
                              f"to task {task}")
        with store_lock(store_dir):
            required = [n["id"] for n in required_notes(load_progress_log(store_dir), task)]
            if waive not in required:
                raise RecordError(f"{waive!r} is not a note task {task} still needs; its "
                                  f"required notes: {required}")
            _append_progress(store_dir,
                          {"type": "waiver", "task": task, "note": waive, "reason": reason,
                           "at": _now()})
    elif deliver:
        with store_lock(store_dir):
            required = [n["id"] for n in required_notes(load_progress_log(store_dir), task)]
            _append_progress(store_dir,
                          {"type": "delivery", "task": task, "notes": required,
                           "via": "session", "at": _now()})
    log = load_progress_log(store_dir)
    delivered = delivered_note_ids(log, task)
    required_list = required_notes(log, task)
    questions = [n for n in owned_open_notes(log, task) if n.get("kind") == "question"]
    if not required_list and not questions:
        print(f"No notes for task {task}.")
    for n in required_list:
        mark = "delivered" if n["id"] in delivered else "UNDELIVERED"
        print(f"[{n['id']}] {mark} {_describe_note(n)}")
    for n in questions:
        print(f"[{n['id']}] for the user: {_describe_note(n)}")


def _check_close_notes(log: list[dict]) -> None:
    """The close starts with no debt left: no open disclosure or question,
    and no task-note still waiting on a task that never completed."""
    owed = [n["id"] for n in owned_open_notes(log)]
    stranded = [n["id"] for n in open_notes(log) if n.get("kind") == "task-note"]
    if owed or stranded:
        raise RecordError(
            "the close cannot start: "
            + "; ".join(part for part in (
                f"open disclosures or questions {owed} (land each and `resolve` it, or ask "
                "the user)" if owed else "",
                f"task-notes for tasks that never completed {stranded} (run the task, or "
                "`resolve` the note as superseded)" if stranded else "") if part))


def stage_map(log: list[dict]) -> dict[int, dict]:
    """Each task's latest stage entry: re-staging a task replaces its
    stage and footprint."""
    return {e["task"]: e for e in log if e.get("type") == "stage"
            and _positive_int_value(e.get("task"))}


def latest_handles(log: list[dict]) -> dict[tuple, dict]:
    """The latest handle per (task, role)."""
    return {(e.get("task"), e.get("role")): e for e in log if e.get("type") == "handle"}


def _normalize_path(path: str) -> str:
    return posixpath.normpath(path.strip().replace("\\", "/"))


def cmd_stage(store_dir: Path, task: int | str, stage: int | None, files: list[str]) -> None:
    """Record `task`'s stage and file footprint. Tasks in one stage run in
    parallel on one working tree, so a footprint sharing a path with another
    unfinished task in the same stage is refused. `final` takes no stage: its
    files join the whole-change gate's footprint (a fix outside every task)."""
    footprint = sorted({_normalize_path(f) for f in files if f.strip()})
    if not footprint or "." in footprint:
        raise RecordError(f"--files: got {files!r}, expected the paths task {task} will touch")
    if task == "final":
        if stage is not None:
            raise RecordError("the whole-change gate runs in no stage: drop --stage")
        with store_lock(store_dir):
            _append_progress(store_dir, {"type": "stage", "task": "final", "files": footprint,
                                         "at": _now()})
        return
    if stage is None:
        raise RecordError(f"task {task} needs --stage: the stage it runs in")
    with store_lock(store_dir):
        log = load_progress_log(store_dir)
        done = set(completed_task_ids(log))
        for other, entry in sorted(stage_map(log).items()):
            if other == task or str(other) in done or entry.get("stage") != stage:
                continue
            shared = sorted(set(footprint) & set(entry.get("files", [])))
            if shared:
                raise RecordError(f"task {task} and task {other} both touch {shared} in stage "
                                  f"{stage}; tasks that share a file go in different stages")
        _append_progress(store_dir,
                      {"type": "stage", "task": task, "stage": stage, "files": footprint,
                       "at": _now()})


def cmd_handle(store_dir: Path, task: int | str, role: str, agent: str) -> None:
    """Record the agent id behind a task's role, so the original agent can
    be continued after a compaction instead of dispatching a cold one."""
    if not _non_empty_str(role) or not _non_empty_str(agent):
        raise RecordError("a handle needs a non-empty --role and --agent")
    with store_lock(store_dir):
        _append_progress(store_dir,
                      {"type": "handle", "task": task, "role": role.strip(),
                       "agent": agent.strip(), "at": _now()})


def render_run_state(log: list[dict], records: list[Record]) -> str:
    """Where the run stands, from the store alone: what a resume reads."""
    done = set(completed_task_ids(log))
    in_flight = tasks_in_flight(log, records)
    stages = stage_map(log)

    def state(task: int) -> str:
        if str(task) in done:
            return "complete"
        return "in flight" if task in in_flight else "not started"

    lines = ["# Run state", "", "## Stages"]
    for stage in sorted({e.get("stage") for e in stages.values()}):
        lines.append(f"- stage {stage}:")
        lines += [f"  - task {task} ({state(task)}): {', '.join(entry.get('files', []))}"
                  for task, entry in sorted(stages.items()) if entry.get("stage") == stage]
    if not stages:
        lines.append("(no stage map recorded)")
    known = set(in_flight) | {int(t) for t in done if t.isdigit()}
    unstaged = sorted(known - set(stages))
    if unstaged:
        lines += ["", "## Unstaged tasks"]
        lines += [f"- task {task} ({state(task)})" for task in unstaged]

    lines += ["", "## Rounds"]
    lines += ([f"- task {task}: " + (" → ".join(e["kind"] for e in triage_entries(log, task))
                                     or "(no triage yet)") for task in in_flight]
              or ["(no task in flight)"])

    lines += ["", "## Parked (for the stage's batched question)"]
    parked = [f"- task {task}: {item}" for task in in_flight for item in _parked_items(log, records, task)]
    lines += parked or ["(none)"]

    lines += ["", "## Notes owed"]
    owed = [f"- task {task}: [{n['id']}] {_describe_note(n)}"
            for task in in_flight for n in undelivered_notes(log, task)]
    owed += [f"- task {n.get('for')} (not started): [{n['id']}] {_describe_note(n)}"
             for n in open_notes(log) if n.get("kind") == "task-note"
             and n.get("for") not in in_flight]
    lines += owed or ["(none)"]

    lines += ["", "## Open disclosures and questions"]
    lines += [f"- [{n['id']}] {_describe_note(n)}" for n in owned_open_notes(log)] or ["(none)"]

    lines += ["", "## Blocking items", f"{len(_open_lines(log, records))} open (see `open`)"]

    lines += ["", "## Agent handles (valid only in the session that created them)"]
    live = [f"- task {task} {role}: `{entry.get('agent')}`"
            for (task, role), entry in latest_handles(log).items()
            if task == "final" or (_positive_int_value(task) and str(task) not in done)]
    lines += live or ["(none)"]

    checkpoints = [n for n in notes_from_log(log) if n.get("kind") == "checkpoint"]
    lines += ["", "## Latest checkpoint"]
    lines.append(f"{checkpoints[-1].get('at', '')}: {checkpoints[-1].get('text', '')}"
                 if checkpoints else "(none)")
    return "\n".join(lines)


def render_report(log: list[dict], records: list[Record]) -> str:
    """What the completion report lists, from the store alone."""
    resolutions = resolutions_from_log(log)
    notes = notes_from_log(log)

    def of_kind(kind: str) -> list[dict]:
        return [n for n in notes if n.get("kind") == kind]

    lines = ["# Run report", "", "## User rulings"]
    rulings = []
    for e in log:
        if not str(e.get("note", "")).lower().startswith(RULING_PREFIX):
            continue
        if e.get("type") == "progress":
            rulings.append(f"- {_scope_name(e.get('task'))}: {e['note']}")
        elif e.get("type") == "resolution":
            rulings.append(f"- `{e.get('resolves')}`: {e['note']}")
    lines += rulings or ["(none)"]

    lines += ["", "## Follow-ups"]
    open_follow_ups = [n for n in of_kind("follow-up") if n["id"] not in resolutions]
    by_rule: dict[str, list[dict]] = {}
    for n in open_follow_ups:
        by_rule.setdefault(n.get("rule") or "", []).append(n)
    for rule in sorted(by_rule, key=lambda r: (r == "", r)):
        lines += ["", f"### {rule or '(no rule)'}"]
        lines += [f"- [{n['id']}] {_describe_note(n)}" for n in by_rule[rule]]
    if open_follow_ups:
        lines += ["", "Decide each: fix, file, or ignore. The fixes go through "
                  "remediating-issues' Batch Path as one change."]
    else:
        lines.append("(none open)")
    lines += ["", "### Unlisted cases the coders reported"]
    unlisted = [f"- [{cid}] {concern} ({rec.stem})" for rec in records
                if rec.ok and rec.data.get("role") == "coder"
                for cid, concern in concern_ids(rec).items()
                if concern.strip().lower().startswith(UNLISTED_CASE_PREFIX)]
    lines += unlisted or ["(none)"]
    lines += ["", "### Follow-ups settled during the run"]
    lines += [f"- [{n['id']}] {n.get('text', '')}: {resolutions[n['id']]}"
              for n in of_kind("follow-up") if n["id"] in resolutions] or ["(none)"]

    lines += ["", "## Orchestrator dispositions and waivers"]
    judged = [f"- [{n['id']}] {_describe_note(n)}" for n in of_kind("disposition")]
    judged += [f"- task {e.get('task')} waived `{e.get('note')}`: {e.get('reason', '')}"
               for e in log if e.get("type") == "waiver"]
    lines += judged or ["(none)"]

    for kind, heading in (("disclosure", "Disclosures"), ("question", "Questions for the user")):
        lines += ["", f"## {heading}"]
        lines += [f"- [{n['id']}] {_describe_note(n)}: {resolutions[n['id']]}"
                  if n["id"] in resolutions else f"- [{n['id']}] OPEN {_describe_note(n)}"
                  for n in of_kind(kind)] or ["(none)"]

    lines += ["", "## Ran light (executing-plans: no triage, lighter assurance)"]
    lines += [f"- {_scope_name(e.get('task'))}" for e in log
              if e.get("type") == "complete" and e.get("light")] or ["(none)"]
    return "\n".join(lines)


def _parked_items(log: list[dict], records: list[Record], task: int) -> list[str]:
    """What waits on the user for `task`: an escalation, held findings, and
    open behavior choices nobody has answered."""
    items = []
    entry = latest_triage(log, task)
    if entry and entry["kind"] == "escalate":
        open_ids = [f["id"] for f in entry["findings"] if f["tier"] in ("patch", "holistic")]
        items.append(f"escalated after round {entry['round']}: {', '.join(open_ids) or 'held only'}")
    if entry and entry.get("held"):
        items.append(f"held: {', '.join(entry['held'])}")
    coders = [r for r in records if r.ok and r.data["role"] == "coder"
              and _scope(r.stem) == f"task-{task}"]
    coder = _latest_coder(coders)
    if coder is not None:
        waived = _user_waived(log)
        for choice in coder.data.get("open", []):
            cid = _item_id(coder.stem, "open", choice)
            if cid not in waived:
                items.append(f"open choice [{cid}] {choice['question']} → {choice['choice']}")
    return items


def cmd_run_state(store_dir: Path, plan: str | None = None) -> None:
    verdict, action = store_verdict(store_dir, plan)
    print(f"Verdict: {verdict}")
    print(f"Next: {action}")
    print(render_run_state(load_progress_log(store_dir), load_records(store_dir)))


def cmd_report(store_dir: Path) -> None:
    print(render_report(load_progress_log(store_dir), load_records(store_dir)))


def _describe_note(note: dict) -> str:
    target = ""
    if note.get("kind") == "task-note":
        target = f" for task {note.get('for')}"
    elif note.get("kind") in OWNED_NOTE_KINDS:
        owner = note.get("owner")
        target = " owned by the close" if owner == CLOSE_OWNER else f" owned by task {owner}"
    source = f", from {_scope_name(note['from'])}" if note.get("from") is not None else ""
    return f"{note.get('kind')}{target}{source}: {note.get('text', '')}"


def _scope_name(scope: int | str) -> str:
    return f"task {scope}" if isinstance(scope, int) else str(scope)


def cmd_note(store_dir: Path, kind: str, text: str, for_task: int | None = None,
             owner: int | str | None = None, source: int | str | None = None,
             rule: str | None = None) -> None:
    """File a note and print its id. Refused: a flag the kind doesn't take
    or lacks, empty text, a target that has already completed (the note
    could never be consumed), or a note already filed. A follow-up may
    carry the rule it falls under, which groups it in the report."""
    _check_note_flags(kind, text, for_task, owner)
    if rule is not None and (kind != "follow-up" or not _non_empty_str(rule)):
        raise RecordError("--rule takes a non-empty rule, and only on a follow-up")
    with store_lock(store_dir):
        nid = _file_note(store_dir, load_progress_log(store_dir), kind, text, for_task,
                         owner, source, rule)
    print(nid)


def _file_note(store_dir: Path, log: list[dict], kind: str, text: str,
               for_task: int | None = None, owner: int | str | None = None,
               source: int | str | None = None, rule: str | None = None) -> str:
    """Append a note entry and return its id; the caller holds the lock.
    `rule` (a follow-up's rule) groups follow-ups in the report and isn't
    part of the id."""
    _check_note_target(log, kind, for_task, owner)
    nid = note_id(kind, text, for_task, owner, source)
    existing = next((n for n in notes_from_log(log) if n["id"] == nid), None)
    if existing is not None:
        raise RecordError(f"this note is already filed as {nid} "
                          f"({_note_state(log, existing)}); file a different text to "
                          "say something new")
    entry: dict = {"type": "note", "id": nid, "kind": kind, "text": text}
    for key, value in (("for", for_task), ("owner", owner), ("from", source), ("rule", rule)):
        if value is not None:
            entry[key] = value
    entry["at"] = _now()
    _append_progress(store_dir, entry)
    return nid


def _note_state(log: list[dict], note: dict) -> str:
    if note["id"] in resolutions_from_log(log):
        return "resolved"
    if note.get("kind") not in RESOLVABLE_NOTE_KINDS:
        return f"a {note.get('kind')} is never open or resolved"
    if any(n["id"] == note["id"] for n in open_notes(log)):
        return "open"
    return f"closed when task {note.get('for')} completed"


def _check_note_flags(kind: str, text: str, for_task: int | None,
                      owner: int | str | None) -> None:
    if kind not in NOTE_KINDS:
        raise RecordError(f"kind: got {kind!r}, allowed set: {list(NOTE_KINDS)}")
    if not _non_empty_str(text):
        raise RecordError("a note needs non-empty --text")
    if kind == "task-note" and for_task is None:
        raise RecordError("a task-note needs --for N, the task whose brief carries it")
    if kind != "task-note" and for_task is not None:
        raise RecordError(f"--for is only for a task-note, not a {kind}")
    if kind in OWNED_NOTE_KINDS and owner is None:
        raise RecordError(f"a {kind} needs --owner N|{CLOSE_OWNER}: the task that settles "
                          "it, or the close")
    if kind not in OWNED_NOTE_KINDS and owner is not None:
        raise RecordError(f"--owner is only for a disclosure or question, not a {kind}")


def _check_note_target(log: list[dict], kind: str, for_task: int | None,
                       owner: int | str | None) -> None:
    done = set(completed_task_ids(log))
    if for_task is not None and str(for_task) in done:
        raise RecordError(f"task {for_task} is complete, so a task-note for it would never "
                          "be delivered; file a follow-up, or a disclosure with "
                          f"--owner {CLOSE_OWNER}")
    if isinstance(owner, int) and str(owner) in done:
        raise RecordError(f"task {owner} is complete, so it can no longer settle this {kind}; "
                          f"use --owner {CLOSE_OWNER}")


def cmd_read(store_dir: Path) -> None:
    print(render_store_markdown(load_records(store_dir), load_progress_log(store_dir)))


def cmd_open(store_dir: Path) -> None:
    lines = _open_lines(load_progress_log(store_dir), load_records(store_dir))
    print("\n".join(lines) if lines else "No open items.")


def _open_lines(log: list[dict], records: list[Record]) -> list[str]:
    """Everything that blocks: the records' open items, the notes tasks in
    flight haven't received, and open disclosures and questions."""
    items = compute_open_items(records, set(resolutions_from_log(log)))
    lines = [f"[{item.id}] {item.kind}: {item.summary}" for item in items]
    for task in tasks_in_flight(log, records):
        lines += [f"[{n['id']}] undelivered to task {task}: {_describe_note(n)}"
                  for n in undelivered_notes(log, task)]
    lines += [f"[{n['id']}] {_describe_note(n)}" for n in owned_open_notes(log)]
    return lines


def cmd_shapes(store_dir: Path) -> None:
    print(render_shapes(list_shapes(load_records(store_dir))))


def cmd_completed(store_dir: Path) -> None:
    for task_id in completed_task_ids(load_progress_log(store_dir)):
        print(task_id)


def cmd_store_dir(store_dir: Path) -> None:
    """Print the resolved store, creating and gitignore-seeding it first:
    store-dir is the session's first ledger call (per SKILL.md), and the
    agents that write records afterward use the Write tool directly — so
    this is the one guaranteed spot to seed the ignore file."""
    print(ensure_store(store_dir))


def cmd_append(store_dir: Path, entry_type: str, task: int | str, note: str,
               light: bool = False) -> None:
    if entry_type == "complete" and task == RUN_SCOPE:
        raise RecordError(f"task {RUN_SCOPE!r} is a scope for run-level rulings and is never "
                          "completed; complete a task number or 'final'")
    with store_lock(store_dir):
        entry: dict = {"type": entry_type, "task": task, "note": note}
        if entry_type == "complete":
            blockers = ready_blockers(store_dir, task, light)
            if blockers:
                raise RecordError(f"{_scope_name(task)} cannot complete: " + "; ".join(blockers))
            _check_gate_matches_commit(store_dir, task)
            if light:
                entry["light"] = True
        _append_progress(store_dir, entry)


def ready_blockers(store_dir: Path, task: int | str, light: bool = False) -> list[str]:
    """Everything that stops `task` from committing. `light` (the inline
    executor, which runs no triage) skips the triage, held-finding, and
    open-choice checks."""
    log = load_progress_log(store_dir)
    records = load_records(store_dir)
    resolved = set(resolutions_from_log(log))
    found = _scope_records(store_dir, scope_prefix(log, task))
    blockers = []
    if light and (latest_triage(log, task) is not None
                  or any(r.data.get("agent") != INLINE_EXECUTOR_AGENT for r in found.coders)):
        blockers.append("--light is executing-plans' path, but this task runs the triage loop "
                        "(it has a triage entry or a dispatched coder's record); drop --light")
    if not light:
        entry = latest_triage(log, task)
        if entry is None:
            blockers.append("no triage entry yet (run `ledger.py triage`)")
        elif entry["kind"] != "done":
            blockers.append(f"the last triage step is {entry['kind']}, not done")
        if entry and entry.get("held"):
            blockers.append(f"held for the user: {', '.join(entry['held'])}")
        coder = _latest_coder(found.coders)
        unanswered = [_item_id(coder.stem, "open", e) for e in coder.data.get("open", [])
                      ] if coder else []
        unanswered = [i for i in unanswered if i not in _user_waived(log)]
        if unanswered:
            blockers.append(f"open behavior choices awaiting the user: {', '.join(unanswered)}")
    if isinstance(task, int):
        undelivered = [n["id"] for n in undelivered_notes(log, task)]
        owned = [n["id"] for n in owned_open_notes(log, task)]
        if undelivered:
            blockers.append(f"undelivered notes {undelivered} (rebuild the brief, or "
                            "`notes --deliver`, or `notes --waive ID --reason ...`)")
        if owned:
            blockers.append(f"open disclosures or questions it owns {owned} (`resolve` each: "
                            f"where a disclosure landed, or \"{RULING_PREFIX} ...\" for a question)")
    items = compute_open_items(records, resolved)
    scopes = _task_scopes(task)
    escalations = [i.id for i in items if i.kind == ESCALATION_KIND and _scope(i.source) in scopes]
    if escalations:
        blockers.append(f"escalations awaiting the user's ruling: {escalations}; `resolve` each "
                        f"with --note \"{RULING_PREFIX} <the ruling, verbatim>\"")
    unverified = [i.id for i in items if i.kind == "cannot_verify" and _scope(i.source) in scopes]
    if unverified:
        blockers.append(f"open cannot_verify items: {', '.join(unverified)}")
    if found.problems:
        blockers.append("malformed or misfiled records: " + "; ".join(found.problems))
    if task == "final":
        pending = [i.id for i in items if i.kind == "duplication_pending"]
        if pending:
            blockers.append(f"open duplication_pending items: {', '.join(pending)}")
    return blockers


def cmd_ready(store_dir: Path, task: int | str, light: bool = False) -> int:
    """Print each blocker and return 1, or say the task is ready and return 0."""
    blockers = ready_blockers(store_dir, task, light)
    for blocker in blockers:
        print(f"- {blocker}")
    print(f"{_scope_name(task)}: {'not ready' if blockers else 'ready'}")
    return 1 if blockers else 0


def _task_scopes(task: int | str) -> tuple[str, ...]:
    return ("final", "final-r2") if task == "final" else (f"task-{task}",)


def cmd_close_round(store_dir: Path, note: str, head: str, expect: int) -> None:
    """Start the next close-gate round and print its number. `expect` is
    the round the caller believes it is starting (1 for a fresh close, 2
    on return from a close-gate remediation); a mismatch means the store
    belongs to another run, so it raises instead of silently starting a
    new run at round 2. The entry records the HEAD the round reviews, so
    round 2 can name the remediation range (round-1 head..HEAD). Past
    CLOSE_ROUND_CAP this raises and appends nothing: the cap is the
    escalation trigger, so a further round must never start silently."""
    with store_lock(store_dir):
        log = load_progress_log(store_dir)
        _check_close_round(log, expect)
        _check_close_notes(log)
        started = close_rounds(log)
        _append_progress(store_dir,
                      {"type": "close_round", "round": started + 1, "head": head, "note": note})
    print(started + 1)


def _check_close_round(log: list[dict], expect: int) -> None:
    started = close_rounds(log)
    if expect == 1 and started >= CLOSE_ROUND_CAP:
        raise RecordError(
            f"expected round 1, but this store already records {started} close "
            "rounds. If the latest round's note names the work you are closing, "
            "this run's close has used both rounds: finish round 2's triage and "
            "escalate any non-trivial finding to the user. Otherwise the rounds "
            "belong to an earlier, finished run: `clear` the store, then retry.")
    if expect == 1 and started >= 1:
        raise RecordError(
            f"expected round 1, but this store already records {started} close "
            "round(s). If the latest round's note names the work you are "
            "closing, it is this run's round 1: resume its triage instead, and "
            "after the remediation start round 2 with --expect 2. Otherwise the "
            "rounds belong to an earlier, finished run: `clear` the store, then retry.")
    if started < CLOSE_ROUND_CAP and expect != started + 1:
        raise RecordError(
            f"expected round {expect}, but this store records {started} close "
            f"round(s): round {expect} only follows round {expect - 1} of the same run.")
    if started >= CLOSE_ROUND_CAP:
        raise RecordError(
            f"close-round cap ({CLOSE_ROUND_CAP}) reached: escalate the open "
            "gate findings to the user instead of starting another round, and "
            "never clear the store to get past the cap.")


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    # errors="replace": a diff of a non-UTF-8 file must not crash the CLI.
    return subprocess.check_output(["git", *args], cwd=repo, env=env,
                                   stderr=subprocess.PIPE).decode(errors="replace")


def _toplevel(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--show-toplevel").strip())


def snapshot_tree(repo: Path) -> str:
    """The working tree as a git tree object, untracked files included.
    Coders never commit before review passes, so a fix's edits share the
    working tree with the uncommitted cycle-1 work; this tree is the fix's
    baseline. It goes through a throwaway copy of the index, so the real
    index and working tree are never touched. It does write git objects,
    and the repo's clean filters (e.g. Git LFS) run as for any `git add`.
    Edits inside a submodule are not captured (see submodule_paths)."""
    top = _toplevel(repo)
    real_index = top / _git(top, "rev-parse", "--git-path", "index").strip()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_index = Path(tmp) / "index"
        if real_index.is_file():
            # copy2 keeps the index's mtime: git re-reads "racily clean"
            # entries (mtime >= the index's) by content, and a fresh mtime on
            # the copy would make a same-size edit in that second invisible.
            shutil.copy2(real_index, tmp_index)
        env = {**os.environ, "GIT_INDEX_FILE": str(tmp_index)}
        # Under core.splitIndex=true, any write of the throwaway index would
        # re-split it and leave an orphan .git/sharedindex.*; every call that
        # writes it overrides the config.
        no_split = ("-c", "core.splitIndex=false")
        _git(top, *no_split, "add", "-A", env=env)
        return _git(top, *no_split, "write-tree", env=env).strip()


def submodule_paths(repo: Path) -> list[str]:
    """Paths of submodules (gitlink entries). A snapshot records only each
    submodule's commit, so uncommitted edits inside one are invisible to
    snapshot and diff-since; the CLI warns when any exist."""
    return [line.split("\t", 1)[1]
            for line in _git(_toplevel(repo), "ls-files", "--stage").splitlines()
            if line.startswith("160000 ")]


def diff_since(repo: Path, base_tree: str, paths: list[str] | tuple[str, ...] = ()) -> str:
    """What changed in the working tree since `base_tree` (a snapshot_tree
    result), new untracked files included: exactly the fix's own edits.
    `paths` limits it to the task's own files, since tasks in one SDD
    stage share the working tree and edit it concurrently. Plain output
    regardless of the user's diff config (color, external diff,
    textconv), since agents read it."""
    return diff_trees(repo, base_tree, snapshot_tree(repo), paths)


def diff_trees(repo: Path, base_tree: str, tree: str,
               paths: list[str] | tuple[str, ...] = ()) -> str:
    """The diff between two trees, limited to `paths`, in git's default
    format whatever the user's diff config says (color, external diff,
    textconv, relative paths, prefixes)."""
    if base_tree.startswith("-"):
        # Agents pass this argument; it must never reach git as an option.
        raise RecordError(f"tree id must not start with '-': got {base_tree!r}")
    return _git(repo, "-c", "core.quotePath=true", "diff", "--no-color", "--no-ext-diff",
                "--no-textconv",
                "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
                base_tree, tree, "--", *paths)


def missing_paths(repo: Path, paths: list[str] | tuple[str, ...], *trees: str) -> list[str]:
    """Paths that match nothing in any of `trees`: a typo in a task's file
    list would otherwise read as "no changes"."""
    return [path for path in paths
            if not any(_git(repo, "ls-tree", "-r", "--name-only", tree, "--", path).strip()
                       for tree in trees)]


def find_process_labels(diff: str) -> list[LabelHit]:
    """Review-process labels on the added lines of a unified diff: task,
    cycle and finding ids, decision-doc and reviewer vocabulary, store
    paths, commit hashes. Comments must state behavior, and a grep written
    by the label's author shares the author's blind spot, so this is a
    script. Prose files (LABEL_SKIPPED_SUFFIXES) are skipped. Comment
    detection is a heuristic: comment-marker lines, trailing `#`/`//`
    comments, and docstring bodies tracked within each hunk."""
    hits: list[LabelHit] = []
    path, line_no, in_docstring = None, 0, False
    old_left = new_left = 0  # lines still owed to the current hunk
    prev = None  # the hunk's last code line (not blank, not a # comment)
    hunk_start = 0  # new-file line the current hunk starts at
    # Split on \n only: str.splitlines() also breaks on form feeds and
    # Unicode line separators inside a line, which would shift the hunk counts.
    for raw in (line.removesuffix("\r") for line in diff.split("\n")):
        if old_left > 0 or new_left > 0:
            tag, text = raw[:1], raw[1:]
            if tag == "\\":
                continue  # "\ No newline at end of file"
            if tag == "-":
                old_left -= 1
                continue
            if tag == "+":
                new_left -= 1
                # Docstring state follows added lines only: a hunk's context
                # can open mid-docstring, where its quotes would invert it.
                if path is not None:
                    may_open = _docstring_may_open(prev, hunk_start)
                    comment, in_docstring = _comment_text(text, in_docstring, may_open)
                    hits.extend(LabelHit(path, line_no, label, text.strip())
                                for label in _labels_in(text, comment))
            else:  # context
                old_left, new_left = old_left - 1, new_left - 1
                # Track a docstring only from an opening the hunk shows, so a
                # line added inside it counts as comment text; a closing quote
                # with no visible opening stays ignored.
                quotes = text.count('"""') + text.count("'''")
                may_open = _docstring_may_open(prev, hunk_start)
                if quotes % 2 == 1 and (in_docstring or may_open):
                    in_docstring = not in_docstring
            # A comment between a signature (or the file's top) and its
            # docstring doesn't change where the docstring may open.
            if text.strip() and not text.strip().startswith("#"):
                prev = text.strip()
            line_no += 1
            continue
        if raw.startswith("+++ "):
            path = _diff_target(raw[4:])
            continue
        header = HUNK_HEADER_RE.match(raw)
        if header:
            old_left = int(header.group(1) or 1)
            line_no = int(header.group(2))
            new_left = int(header.group(3) or 1)
            in_docstring, prev, hunk_start = False, None, line_no
    return hits


def _docstring_may_open(prev: str | None, hunk_start: int) -> bool:
    """Whether a docstring can open here: at the top of the file (no code
    yet in a hunk that starts at line 1; a shebang or license comment
    doesn't count as code), or right after a line ending in `:` (a def or
    class signature), ignoring a trailing comment such as `# noqa`."""
    if prev is None:
        return hunk_start == 1
    return TRAILING_COMMENT_RE.split(prev, 1)[0].rstrip().endswith(":")


def _diff_target(target: str) -> str | None:
    """The new-side path from a `+++ ` line, or None for /dev/null and
    prose files. Git appends a tab to a name with a space and C-quotes a
    non-ASCII one under its default core.quotePath."""
    target = target.rstrip("\t")
    if target.startswith('"') and target.endswith('"'):
        target = (target[1:-1].encode("latin-1").decode("unicode_escape")
                  .encode("latin-1").decode("utf-8", errors="replace"))
    if not target.startswith("b/"):
        return None
    name = target.rsplit("/", 1)[-1].lower()
    if name.endswith(LABEL_SKIPPED_SUFFIXES) and name not in LABEL_SCANNED_NAMES:
        return None
    return target[2:]


def _comment_text(text: str, in_docstring: bool,
                  may_open: bool = True) -> tuple[str | None, bool]:
    """The comment or docstring part of a line (None if there is none),
    and whether a docstring is still open after it. An odd count of
    triple quotes opens a docstring only when the line starts with them
    where one can start (`may_open`); otherwise it closes one whose
    opening the diff didn't show, and the state stays closed."""
    stripped = text.strip()
    quotes = stripped.count('"""') + stripped.count("'''")
    if in_docstring:
        return stripped, quotes % 2 == 0
    if quotes:
        opens = quotes % 2 == 1 and may_open and bool(DOCSTRING_OPEN_RE.match(stripped))
        return stripped, opens
    if stripped.startswith(COMMENT_PREFIXES) and not stripped.startswith(NOT_COMMENT_PREFIXES):
        return stripped, False
    trailing = TRAILING_COMMENT_RE.search(text)
    return (text[trailing.end():] if trailing else None), False


def _labels_in(text: str, comment: str | None) -> list[str]:
    labels = [name for name, pattern in LABEL_PATTERNS_ANYWHERE.items() if pattern.search(text)]
    if comment is not None:
        labels += [name for name, pattern in LABEL_PATTERNS_COMMENT_ONLY.items()
                   if pattern.search(comment)]
    return labels


def _warn_submodules(repo: Path) -> None:
    paths = submodule_paths(repo)
    if paths:
        print(f"WARNING: edits inside submodule(s) {', '.join(paths)} are not "
              "captured by snapshot/diff-since; check them by hand.", file=sys.stderr)


def cmd_snapshot(store_dir: Path, task: int | str, label: str,
                 tree: str | Callable[[], str]) -> None:
    """Record a fix baseline as a typed progress entry (so it survives
    compaction) and print the tree id for the dispatch. The fix's round
    comes from the triage entry before it, not from the snapshot."""
    with store_lock(store_dir):
        tree = tree() if callable(tree) else tree
        _append_progress(store_dir, {"type": "snapshot", "task": task, "label": label,
                                     "tree": tree})
    print(tree)


def find_baseline(log: list[dict], tree: str, task: int | str) -> dict:
    """The last snapshot entry recording `tree` for `task`."""
    matches = [e for e in log if e.get("type") == "snapshot"
               and e.get("tree") == tree and e.get("task") == task]
    if not matches:
        raise RecordError(f"no snapshot of tree {tree!r} for task {task!r}: a fix "
                          "baseline comes only from `ledger.py snapshot`")
    return matches[-1]


def fix_round(log: list[dict], tree: str, task: int | str) -> dict:
    """The triage entry that routes the fix starting from `tree`: the last
    one logged after the task's previous snapshot and before this one,
    which must be a fix kind. Every fix starts from its own snapshot,
    routed by the triage entry before it; one that triage has since moved
    past (to done or escalate) is stale."""
    scoped = _scope_log(log, task)
    at = max((i for i, e in enumerate(scoped) if e.get("type") == "snapshot"
              and e.get("tree") == tree and e.get("task") == task), default=None)
    if at is None:
        raise RecordError(f"no snapshot of tree {tree!r} for task {task!r}: a fix "
                          "baseline comes only from `ledger.py snapshot`")
    start = max((i for i, e in enumerate(scoped[:at]) if e.get("type") == "snapshot"
                 and e.get("task") == task), default=-1)
    steps = [e for e in scoped[start + 1:at] if e.get("type") == TRIAGE_ENTRY
             and e.get("task") == task]
    if not steps:
        raise RecordError(f"no triage entry routes the fix from {tree!r}: run `ledger.py "
                          "triage` and act on the step it prints before taking the snapshot")
    if steps[-1].get("kind") not in triage_rules.FIX_KINDS:
        raise RecordError(f"the last triage step before snapshot {tree!r} is "
                          f"{steps[-1].get('kind')}, not a fix round; act on that step instead")
    return steps[-1]


def cmd_baseline(store_dir: Path, tree: str, task: int | str) -> None:
    """Print the round a fix baseline starts: its kind, who re-checks it,
    the decision doc a holistic round implements, and the findings sent."""
    entry = fix_round(load_progress_log(store_dir), tree, task)
    print(f"round: {entry['kind']}")
    print(f"recheck: {entry['recheck']}")
    if entry.get("decision"):
        print(f"decision: {store_dir / (entry['decision'] + '.json')}")
    for finding in entry["findings"]:
        if finding["tier"] not in ("defer", "held"):
            print(f"  [{finding['id']}] {finding['tier']}: {finding['rule']}")
    for cid in entry.get("root_causes", []):
        print(f"  [{cid}] holistic: root cause")


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError("close-round needs a git HEAD to record; run it inside the repo") from e


def cmd_resolve(store_dir: Path, resolve_id: str, note: str) -> None:
    """Record a resolution — but only for an id that is currently open and
    resolvable. A resolve that matches nothing is not a silent no-op: it
    raises RecordError distinguishing "already resolved" (the id has a
    prior resolution — the corrective message quotes that resolution's own
    note) from "never was open" (the id never matched a resolvable item;
    the message lists what's actually open right now)."""
    with store_lock(store_dir):
        _check_resolvable(store_dir, resolve_id, note)
        _append_progress(store_dir,
                      {"type": "resolution", "resolves": resolve_id, "note": note})


def _check_resolvable(store_dir: Path, resolve_id: str, note: str) -> None:
    log = load_progress_log(store_dir)
    already_resolved = resolutions_from_log(log)
    if resolve_id in already_resolved:
        raise RecordError(
            f"{resolve_id!r} already resolved (note: {already_resolved[resolve_id]!r})")
    if resolve_id.startswith(NOTE_ID_PREFIX):
        _check_note_resolvable(log, resolve_id, note)
        return

    records = load_records(store_dir)
    if resolve_id in _user_settleable_ids(records):
        if not note.lower().startswith(RULING_PREFIX):
            raise RecordError(f"{resolve_id!r} is settled only by the user: resolve it with "
                              f"--note \"{RULING_PREFIX} <the ruling, verbatim>\"")
        return
    items = compute_open_items(records, set(already_resolved))
    open_ids = sorted([item.id for item in items if item.kind in RESOLVABLE_KINDS]
                      + [n["id"] for n in open_notes(log)])
    if resolve_id not in open_ids:
        message = (f"{resolve_id!r} matches no open resolvable item; "
                    f"currently open resolvable ids: {open_ids}")
        # The id may be real but belong to a whole-record kind (status,
        # malformed) — those are never resolvable, so name that rule
        # instead of leaving an orchestrator to guess why a pasted id
        # straight from `open` still didn't work.
        if any(item.id == resolve_id and item.kind not in RESOLVABLE_KINDS for item in items):
            message += (": status and malformed items are not resolvable — "
                         "they clear when the record is rewritten")
        raise RecordError(message)

    if f"#{ESCALATION_KIND}[" in resolve_id and not note.lower().startswith(RULING_PREFIX):
        raise RecordError(f"{resolve_id!r} waits on the user: resolve it with --note "
                          f"\"{RULING_PREFIX} <the ruling, verbatim>\"")


def _user_settleable_ids(records: list[Record]) -> set[str]:
    """Ids only the user settles: reviewer findings (a waiver), a coder's
    open behavior choices (an acceptance or an override), and its `root
    cause:` concerns (a waiver, when the task can't wait for the fix)."""
    ids = set()
    for rec in records:
        if not rec.ok:
            continue
        role = rec.data["role"]
        if role in FINDING_LIST_FIELD or role == "gate":
            ids |= set(finding_ids(rec, (FINDING_LIST_FIELD.get(role, "findings"),)))
        elif role == "coder":
            ids |= {_item_id(rec.stem, "open", e) for e in rec.data.get("open", [])}
            ids |= {cid for cid, text in concern_ids(rec).items()
                    if text.lower().startswith(ROOT_CAUSE_PREFIX)}
    return ids


# What a note's resolution must say, by kind.
_NOTE_RESOLUTION_HINTS = {
    "task-note": "why it no longer applies (superseded or withdrawn)",
    "run-note": "why the rule is retired",
    "follow-up": "how it was settled",
    "disclosure": "where it landed (file and commit)",
}


def _check_note_resolvable(log: list[dict], resolve_id: str, note: str) -> None:
    found = next((n for n in notes_from_log(log) if n["id"] == resolve_id), None)
    if found is None:
        raise RecordError(f"{resolve_id!r} matches no filed note; currently open note ids: "
                          f"{sorted(n['id'] for n in open_notes(log))}")
    kind = found.get("kind")
    if kind not in RESOLVABLE_NOTE_KINDS:
        why = ("an audit entry" if kind == "disposition"
               else "superseded by the next checkpoint")
        raise RecordError(f"{resolve_id!r} is a {kind}, {why}: it is never resolved")
    if all(n["id"] != resolve_id for n in open_notes(log)):
        raise RecordError(f"{resolve_id!r} closed when task {found.get('for')} completed")
    if kind == "question":
        if not note.lower().startswith(RULING_PREFIX):
            raise RecordError(f"{resolve_id!r} is a question for the user: resolve it with "
                              f"--note \"{RULING_PREFIX} <the ruling, verbatim>\"")
    elif not _non_empty_str(note):
        raise RecordError(f"{resolve_id!r} needs --note saying {_NOTE_RESOLUTION_HINTS[kind]}")


# Store-managed handoff files beyond the JSON records (decision docs are
# records): briefs, reports, gate reports, and review packages. Gate
# reviewers read their own report path as their prior verdict, so these
# must not outlive the run that wrote them.
HANDOFF_FILE_PATTERNS = ("task-*-*.md", "final-*.md", "gate-*-report.md", "intent-issue.md",
                         "review-*.diff",
                         # names from before `path` named every report
                         "design-review-*.md", "intent-recheck.md", "mutation-review.md")
# `path` scopes beyond a task number, and the kinds of file it names.
PATH_SCOPES = ("final", "close", "ruling", "gate")
PATH_KINDS = ("record", "report", "brief")


def handoff_path(store_dir: Path, log: list[dict], scope: int | str, agent: str | None,
                 kind: str = "record") -> Path:
    """The store path of a handoff file: a task's or a scope's record or
    report for `agent`, a gate's report, or a task's brief. `final` follows
    `scope_prefix` (final-r2 once a close round has started), `close` the
    latest close round, and `gate` keeps one path across rounds so a re-run
    reads its prior report."""
    if kind == "brief":
        if not isinstance(scope, int):
            raise UsageError("a brief belongs to a task: --task N --kind brief")
        return store_dir / f"task-{scope}-brief.md"
    if not agent or "/" in agent or "\\" in agent or ".." in agent:
        raise UsageError(f"--agent {agent!r}: give the agent's registered name")
    if scope == "gate":
        if kind != "report":
            raise UsageError("the close-round gates write reports only: --kind report")
        stem = f"gate-{agent}"
    elif scope in ("close", "ruling"):
        rounds = close_rounds(log)
        if not rounds:
            raise UsageError(f"--task {scope} names a close-round fix, but no close round "
                             "has started")
        stem = f"final-close-r{rounds}-{agent}" if scope == "close" \
            else f"final-close-ruling-{agent}"
    else:
        stem = f"{scope_prefix(log, scope)}-{agent}"
    return store_dir / (f"{stem}.json" if kind == "record" else f"{stem}-report.md")


def cmd_path(store_dir: Path, scope: int | str, agent: str | None, kind: str = "record") -> None:
    print(handoff_path(store_dir, load_progress_log(store_dir), scope, agent, kind))


def cmd_clear(store_dir: Path, discard_open: bool = False) -> None:
    """Refuse while the log holds follow-ups, disclosures or questions not
    yet settled (they would vanish unreported) unless `discard_open` says
    the user confirmed the loss; then clear (`_clear_store`)."""
    if not store_dir.is_dir():
        return
    with store_lock(store_dir):
        if not discard_open:
            _check_nothing_owed(store_dir)
        _clear_store(store_dir)


def _check_nothing_owed(store_dir: Path) -> None:
    try:
        log = load_progress_log(store_dir)
    except RecordError as e:
        raise RecordError(f"{e}; the log can't be checked for open notes, so clearing it "
                          "needs --discard-open") from e
    owed = [n["id"] for n in open_notes(log)
            if n.get("kind") in ("follow-up", *OWNED_NOTE_KINDS)]
    if owed:
        raise RecordError(f"the store still holds open follow-ups, disclosures or questions "
                          f"{owed}: put them in the completion report (`report`) or resolve "
                          "them; clear anyway only with the user's confirmation, via "
                          "--discard-open")


def _clear_store(store_dir: Path) -> None:
    """Delete files whose stem matches the record naming convention
    (task-*-* or final-*), the handoff files the run wrote
    (HANDOFF_FILE_PATTERNS), the progress log and the check history —
    content validity is
    irrelevant: a malformed record-attempt is clearable, an unrelated
    notes.json is not. The lock file stays: another writer may hold it."""
    for path in sorted(store_dir.glob("*.json")):
        if fnmatch.fnmatch(path.stem, "task-*-*") or fnmatch.fnmatch(path.stem, "final-*"):
            path.unlink()
    for pattern in HANDOFF_FILE_PATTERNS:
        for path in sorted(store_dir.glob(pattern)):
            path.unlink()
    for name in (PROGRESS_FILENAME, HISTORY_FILENAME):
        if (store_dir / name).is_file():
            (store_dir / name).unlink()


def _resolve_check_path(record_path: str, store: str | None) -> Path:
    """A bare filename (no path separator, e.g. "task-1-python-coder.json")
    resolves against the store directory; anything else — relative or
    absolute, with a directory component — is used exactly as given,
    relative to the current working directory, and never touches the
    store at all. --store must never be accepted-and-ignored for `check`
    (spec Sec 6, amended 2026-08-27), but resolving it is deferred to
    exactly the bare-filename case, so a fully-qualified record path
    (the common case: the dispatch hands agents an absolute path) doesn't
    gain a new git-repository dependency it never had."""
    if "/" in record_path or "\\" in record_path:
        return Path(record_path)
    return get_store_dir(store) / record_path


def cmd_check(record_path: str, store: str | None = None) -> None:
    """Write-time gate (`check_record`). Silent on success. A passing
    record inside a store (a directory ensure_store seeded) is summarized
    into HISTORY_FILENAME there, since the next cycle overwrites it."""
    path = _resolve_check_path(record_path, store)
    # The lock covers check_record's reads of the log and the history (the
    # baseline-reuse check) as well as the history append. check_record
    # itself never locks: `snapshot` calls it while holding the lock.
    with store_lock(path.parent):
        data = check_record(path)
        if _is_store(path.parent):
            _append_jsonl(path.parent / HISTORY_FILENAME, _history_entry(path.stem, data))


def check_record(path: Path) -> dict:
    """Strict parse + validation, then the same item-construction path
    `open` uses (spec Sec 6, amended 2026-08-27), so a record that passes
    cannot later render as malformed at query time. A decision record is
    also checked against its store and repo (`_check_decision_context`)."""
    data = _parse_record_file(path)
    rec = Record(stem=path.stem, ok=True, data=data)
    try:
        _build_open_items(rec)
    except Exception as e:
        raise RecordError(
            f"{path}: passes validation but fails to render as an open item: {e}") from e
    if data["role"] == "decision":
        _check_decision_context(path, data)
    elif data["role"] in FINDING_LIST_FIELD and _is_store(path.parent):
        _check_contest_answers(path, data)
        _check_reraised_findings(path, data)
    elif data["role"] == "coder":
        _check_coder_model(path, data)
        _check_fix_baseline(path, data)
        if _is_store(path.parent):
            _check_deferrals_outside_footprint(path, data)
            repo = _store_repo(path.parent)
            if repo is not None:
                _check_open_precedents(repo, data)
                _check_fix_labels(repo, data)
            if data["cycle"] >= 2 and data["status"] in DIAGNOSIS_STATUSES:
                _check_fix_round(path, data, repo)
    return data


TEST_FILE_RE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.(py|rs)$|(^|/)tests\.rs$")
ASSERTION_RE = re.compile(r"\bassert\w*!?\s*[\s(]|\bassert_(?:eq|ne)!|pytest\.raises|\bexpect\(")
SKIP_MARKER_RE = re.compile(
    r"pytest\.mark\.(?:skip|xfail)|pytest\.(?:skip|importorskip)\(|unittest\.skip|\bskipTest\("
    r"|\bSkipTest\b|@skip(?:If|Unless)?\b|\bexpectedFailure\b|#\[ignore\]")
TEST_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>test_\w*)|^\s*#\[test\]")


def _check_fix_round(path: Path, data: dict, repo: Path | None) -> None:
    """A finished fix implements the round triage sent it: it covers each
    sent finding once, maps its rows and decision cases to hunks it really
    changed, writes failing tests first in a patch or ruling round, and
    justifies edits to tests that already existed."""
    log = load_progress_log(path.parent)
    entry = fix_round(log, data["baseline"], data["task"])
    # A finding the user waived after triage sent it is no longer the round's work.
    waived = _user_waived(log)
    sent = [f for f in entry["findings"]
            if f["tier"] not in ("defer", "held") and f["id"] not in waived]
    if entry["kind"] in ("patch", "polish", "ruling"):
        _check_coverage(data, sent)
    if entry["kind"] in ("patch", "ruling"):
        _check_tests_first(data, [f for f in sent if f["tier"] != "note"])
    if entry["kind"] == "holistic":
        _check_holistic_decision(path, data, entry, sent)
    if repo is None:
        return
    # Tasks in a stage share the working tree: read only this task's files,
    # its footprint as well as what it says it changed.
    footprint = task_footprint(log, data["task"]) or set()
    paths = sorted(footprint | {f for f in data.get("changed_files", []) if _non_empty_str(f)})
    diff = diff_trees(repo, data["baseline"], snapshot_tree(repo), paths)
    changed = changed_lines(diff)
    for sweep in data.get("sweeps", []):
        for row in sweep["rows"]:
            if "hunk" in row and not site_touches(row["hunk"], changed):
                raise RecordError(f"{path}: row {row['site']} claims hunk {row['hunk']}, which "
                                  "the fix didn't change; fix it or list it already_correct")
    for row in data.get("decision_rows", []):
        if not site_touches(row["hunk"], changed):
            raise RecordError(f"{path}: decision case {row['choice']}/{row['case']} claims hunk "
                              f"{row['hunk']}, which the fix didn't change")
    _check_flagged_rows(path, data, {f["id"] for f in sent} - _left_unfixed(data))
    for test in data.get("tests_first", []):
        if "n/a" not in test and test["test"].split("::")[0] not in changed:
            raise RecordError(f"{path}: tests_first names {test['test']}, which the fix diff "
                              "doesn't touch; write the failing test as part of the fix")
    _check_test_changes(path, data, diff)


def _check_coverage(data: dict, sent: list[dict]) -> None:
    """Each sent finding appears exactly once among the coder's sweeps,
    contests, reach raises, and (notes only) skips."""
    claims: dict[str, int] = {}
    for sweep in data.get("sweeps", []):
        for fid in sweep["findings"]:
            claims[fid] = claims.get(fid, 0) + 1
    for field_name in ("contested", "reach_raised", "notes_skipped"):
        for item in data.get(field_name, []):
            claims[item["finding"]] = claims.get(item["finding"], 0) + 1
    missing = sorted(f["id"] for f in sent if f["id"] not in claims)
    twice = sorted(f["id"] for f in sent if claims.get(f["id"], 0) > 1)
    if missing:
        raise RecordError(f"the round sent {', '.join(missing)}; cover each in a sweep, a "
                          "contest, a reach raise, or (a note) notes_skipped")
    if twice:
        raise RecordError(f"{', '.join(twice)} covered more than once; each sent finding "
                          "goes in exactly one place")
    skipped = {i["finding"] for i in data.get("notes_skipped", [])}
    not_notes = sorted(f["id"] for f in sent if f["id"] in skipped and f["tier"] != "note")
    if not_notes:
        raise RecordError(f"{', '.join(not_notes)} isn't a note, so it can't be skipped")


def _left_unfixed(data: dict) -> set[str]:
    """Sent findings the fix leaves as they are. A contested finding isn't
    fixed, one raised to contract reach stops before its fix, and a skipped
    note is skipped; none has a test to write or a flagged site to row."""
    return {e["finding"] for field in ("contested", "reach_raised", "notes_skipped")
            for e in data.get(field, [])}


def _check_tests_first(data: dict, serious: list[dict]) -> None:
    covered = {t["finding"] for t in data.get("tests_first", [])}
    missing = sorted(f["id"] for f in serious if f["id"] not in covered | _left_unfixed(data))
    if missing:
        raise RecordError(f"tests_first: no entry for {', '.join(missing)}; write a failing "
                          f"test first, or give an n/a category ({', '.join(TESTS_FIRST_NA)})")


def _check_holistic_decision(path: Path, data: dict, entry: dict, sent: list[dict]) -> None:
    """A holistic fix implements this round's decision doc, which passes
    `check`: it maps every case of every fix choice to a hunk, contests each
    finding the doc escalates (the raising reviewer answers in the round's
    re-check), and fixes or skips each sent note no fix choice took."""
    expected = entry.get("decision")
    named = Path(data.get("decision", "")).stem
    if named != expected:
        raise RecordError(f"{path}: decision: got {data.get('decision')!r}; this holistic round "
                          f"implements {expected}")
    doc = check_record(path.parent / f"{expected}.json")
    mapped = {(r["choice"], r["case"]) for r in data.get("decision_rows", [])}
    unmapped = [f"{c_idx}/{k_idx}" for c_idx, choice in enumerate(doc["choices"])
                if choice["kind"] == "fix" for k_idx in range(len(choice["cases"]))
                if (c_idx, k_idx) not in mapped]
    if unmapped:
        raise RecordError(f"{path}: decision cases {', '.join(unmapped)} (choice/case) have no "
                          "decision_rows entry mapping them to a hunk")
    contested = {c["finding"] for c in data.get("contested", [])}
    uncontested = sorted(f for c in doc["choices"] if c["kind"] == "escalate"
                         for f in c["findings"] if f not in contested)
    if uncontested:
        raise RecordError(f"{path}: the decision escalates {', '.join(uncontested)}; contest "
                          "each with the decision's evidence (reason wrong or plan-conflict)")
    fixed = {f for c in doc["choices"] if c["kind"] == "fix" for f in c["findings"]}
    _check_coverage(data, [f for f in sent if f["tier"] == "note" and f["id"] not in fixed])


def _check_flagged_rows(path: Path, data: dict, sent_ids: set[str]) -> None:
    """Every site a reviewer flagged recurring or fix-introduced, on a
    finding the fix fixes, is a row of the fix."""
    rows = {row["site"] for sweep in data.get("sweeps", []) for row in sweep["rows"]}
    scope = _scope(path.stem)
    for rec in _scope_records(path.parent, scope).reviewers if scope else []:
        flagged = {e.get("site") for flag in FLAG_FIELDS for e in rec.data.get(flag, [])}
        field_name = FINDING_LIST_FIELD.get(rec.data["role"], "findings")
        for fid, finding in finding_ids(rec, (field_name,)).items():
            missing = sorted(s for s in finding["sites"] if s in flagged and s not in rows)
            if fid in sent_ids and missing:
                raise RecordError(f"{path}: {fid} was flagged at {', '.join(missing)}; list each "
                                  "flagged site as a row")


def _test_file_edits(diff: str) -> dict[str, set[str]]:
    """For each test file that existed before the fix: the kinds of change
    (changed, deleted, skipped) its removed assertions, removed test
    functions, and added skip markers call for."""
    edits: dict[str, set[str]] = {}
    for path, removed, added in _file_line_changes(diff):
        if not TEST_FILE_RE.search(path):
            continue
        kept = {line.strip() for line in added}
        added_tests = {m["name"] for line in added if (m := TEST_FUNCTION_RE.search(line)) and m["name"]}
        for line in removed:
            match = TEST_FUNCTION_RE.search(line)
            if match and (match["name"] is None or match["name"] not in added_tests):
                edits.setdefault(path, set()).add("deleted")
            elif not match and ASSERTION_RE.search(line) and line.strip() not in kept:
                edits.setdefault(path, set()).add("changed")
        if any(SKIP_MARKER_RE.search(line) for line in added):
            edits.setdefault(path, set()).add("skipped")
    return edits


def _file_line_changes(diff: str) -> list[tuple[str, list[str], list[str]]]:
    """Per file that existed before the change: its path and its removed and
    added lines. Hunk line counts are tracked, so a line whose text starts
    with `--` or `++` is never read as a file header. A deleted file is
    named by its `--- a/` side."""
    out: list[tuple[str, list[str], list[str]]] = []
    old_path = None
    current: tuple[str, list[str], list[str]] | None = None
    old_left = new_left = 0
    for raw in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            tag, text = raw[:1], raw[1:]
            if tag == "-":
                old_left -= 1
                if current:
                    current[1].append(text)
            elif tag == "+":
                new_left -= 1
                if current:
                    current[2].append(text)
            elif tag != "\\":
                old_left, new_left = old_left - 1, new_left - 1
            continue
        if raw.startswith("--- "):
            old_path = _diff_side(raw[4:], "a/")
            continue
        if raw.startswith("+++ "):
            new_path = _diff_side(raw[4:], "b/")
            current = (new_path or old_path, [], []) if old_path else None
            if current:
                out.append(current)
            continue
        header = HUNK_HEADER_RE.match(raw)
        if header:
            old_left = int(header.group(1) or 1)
            new_left = int(header.group(3) or 1)
    return out


def _diff_side(target: str, prefix: str) -> str | None:
    """A `---`/`+++` path without its a/ or b/ prefix, C-quoting decoded;
    None for /dev/null."""
    target = target.rstrip("\t")
    if target.startswith('"') and target.endswith('"'):
        target = (target[1:-1].encode("latin-1").decode("unicode_escape")
                  .encode("latin-1").decode("utf-8", errors="replace"))
    return target[len(prefix):] if target.startswith(prefix) else None


def _check_test_changes(path: Path, data: dict, diff: str) -> None:
    """Edits to tests that existed before the fix carry a test_changes entry
    of the matching kind for that file. A removed assertion may be a change
    or a deletion."""
    declared: dict[str, set[str]] = {}
    for change in data.get("test_changes", []):
        declared.setdefault(change["test"].split("::")[0], set()).add(change["kind"])
    for file, kinds in sorted(_test_file_edits(diff).items()):
        have = declared.get(file, set())
        for kind in sorted(kinds):
            accepted = {"changed", "deleted"} if kind == "changed" else {kind}
            if not have & accepted:
                raise RecordError(f"{path}: {file} has a {kind} test the fix didn't justify; add "
                                  f"a test_changes entry (kind {kind}) with the reason")


# The inline executor writes its own coder record and runs on whatever
# model the session runs on.
INLINE_EXECUTOR_AGENT = "executing-plans"
FALSE_POSITIVE_PREFIX = "label false positive:"


def task_footprint(log: list[dict], task: int | str) -> set[str] | None:
    """The files a task said it would touch (its latest `stage` entry), or
    the union of every task's at the whole-change gate. None when an
    integer task has no stage entry."""
    stages = stage_map(log)
    if task == "final":
        added = [e for e in log if e.get("type") == "stage" and e.get("task") == "final"]
        return {f for entry in [*stages.values(), *added] for f in entry.get("files", [])}
    entry = stages.get(task)
    return None if entry is None else set(entry.get("files", []))


def _deferred_paths(data: dict) -> list[str]:
    """Paths a coder says lie outside its scope: sweep sites it routed
    elsewhere, and the code a `root cause:` concern traces to."""
    paths = [SITE_RE.match(site)["path"] for sweep in data.get("sweeps", [])
             for site in sweep.get("sites_outside", [])]
    paths += [p for c in data.get(CONCERN_FIELD, []) if isinstance(c, str)
              and c.lower().startswith(ROOT_CAUSE_PREFIX) and (p := root_cause_path(c))]
    return paths


def _check_deferrals_outside_footprint(path: Path, data: dict) -> None:
    """A deferral can't point into the scope: work inside the footprint
    filed as "outside" would never be done or decided."""
    deferred = _deferred_paths(data)
    if not deferred:
        return
    footprint = task_footprint(load_progress_log(path.parent), data["task"])
    if footprint is None:
        raise RecordError(f"{path}: defers work outside task {data['task']}, but the task has "
                          "no recorded footprint; record it with `ledger.py stage` first")
    inside = sorted({p for p in deferred if _normalize_path(p) in footprint})
    if inside:
        raise RecordError(f"{path}: {', '.join(inside)} is inside task {data['task']}'s own "
                          "footprint, so it can't be deferred: fix it in this task")


def _store_repo(store_dir: Path) -> Path | None:
    """The toplevel of the repository the store lives in, or None when the
    store isn't inside a git work tree."""
    try:
        return _toplevel(store_dir)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _check_open_precedents(repo: Path, data: dict) -> None:
    for idx, entry in enumerate(data.get("open", [])):
        cited = entry.get("precedent")
        if cited and not (repo / SITE_RE.match(cited)["path"]).is_file():
            raise RecordError(f"open[{idx}].precedent: {cited!r} names a file that doesn't "
                              "exist; cite the code the choice follows")


def _excused_label_hits(hits: list[LabelHit], concerns: list) -> list[LabelHit]:
    """The hits no `label false positive: <file>: <line text>` concern excuses."""
    excused = set()
    for concern in concerns:
        if isinstance(concern, str) and concern.lower().startswith(FALSE_POSITIVE_PREFIX):
            file, _, text = concern[len(FALSE_POSITIVE_PREFIX):].partition(":")
            excused.add((file.strip(), text.strip()))
    return [hit for hit in hits if (hit.path, hit.text) not in excused]


def _check_fix_labels(repo: Path, data: dict) -> None:
    """A finished fix's added lines carry no process labels beyond the ones
    the coder listed as false positives."""
    if data["cycle"] < 2 or data["status"] not in DIAGNOSIS_STATUSES:
        return
    files = [f for f in data.get("changed_files", []) if isinstance(f, str) and f.strip()]
    if not files:
        return
    now = snapshot_tree(repo)
    unmatched = missing_paths(repo, files, data["baseline"], now)
    if unmatched:
        raise RecordError(f"changed_files: {', '.join(unmatched)} match nothing before or "
                          "after the fix; list the files the fix changed")
    hits = _excused_label_hits(find_process_labels(diff_trees(repo, data["baseline"], now, files)),
                               data.get(CONCERN_FIELD, []))
    if hits:
        listed = "; ".join(f"{h.path}:{h.line}: {h.label}" for h in hits)
        raise RecordError(f"process labels in the fix's added lines: {listed}. Rewrite each to "
                          f"state the behavior, or list a real false positive as "
                          f"'{FALSE_POSITIVE_PREFIX} <file>: <line text>'")


def _check_fix_baseline(path: Path, data: dict) -> None:
    """A finished fix names the snapshot it started from, and that snapshot
    is its own: a fix that reused an earlier cycle's baseline (or had none)
    would have no triage entry of its own routing it, and its diff would
    mix in the earlier fix. A fix resumed after needs_context or blocked
    keeps its cycle, so its baseline is still its own."""
    if data["cycle"] < 2 or data["status"] not in DIAGNOSIS_STATUSES:
        return
    baseline = data.get("baseline")
    if not _non_empty_str(baseline):
        raise RecordError(f"{path}: missing required field(s): baseline (the `Fix baseline:` "
                          "tree from your dispatch)")
    if not _is_store(path.parent):
        return
    find_baseline(load_progress_log(path.parent), baseline, data["task"])
    reused = sorted(e["cycle"] for e in load_history(path.parent)
                    if e.get("record") == path.stem and e.get("baseline") == baseline
                    and type(e.get("cycle")) is int and e["cycle"] < data["cycle"])
    if reused:
        raise RecordError(f"{path}: baseline {baseline} already started cycle {reused[0]}; "
                          "each fix starts from its own snapshot, so this fix needs a new "
                          "`snapshot` (return needs_context naming it)")


def _check_coder_model(path: Path, data: dict) -> None:
    """A coder that did work ran on sonnet, or on opus under the user's
    ruling for its task. One that stopped (needs_context, blocked) changed
    nothing, which is how a coder refuses a model it wasn't allowed."""
    if "model" not in data:
        raise RecordError(f"{path}: missing required field(s): model (the model family "
                          "your system prompt names, lowercase)")
    family = _model_family(data["model"])
    if (data["status"] not in DIAGNOSIS_STATUSES or family == CODER_MODEL
            or data.get("agent") == INLINE_EXECUTOR_AGENT):
        return
    if family == OPUS_CODER_MODEL and _opus_ruling_logged(load_progress_log(path.parent), data["task"]):
        return
    raise RecordError(f"{path}: coders run on {CODER_MODEL}; model {data['model']!r} needs a "
                      f"logged \"{OPUS_RULING_PREFIX} ...\" progress note for task "
                      f"{data['task']!r}, and only opus can be authorized")


def _model_family(model: str) -> str | None:
    """The family a model string names ("Sonnet 5.5", "claude-sonnet-5-5"
    and "sonnet" are all sonnet), or None when it names neither family a
    coder may run on."""
    words = re.split(r"[^a-z]+", model.lower())
    return next((f for f in (CODER_MODEL, OPUS_CODER_MODEL) if f in words), None)


def _opus_ruling_logged(log: list[dict], task: int | str) -> bool:
    return any(e.get("type") == "progress" and e.get("task") == task
               and str(e.get("note", "")).lower().startswith(OPUS_RULING_PREFIX) for e in log)


def finding_ids(rec: Record, fields: tuple[str, ...] = FINDING_FIELDS) -> dict[str, dict]:
    """Content-derived ids (as `open` derives them) for a reviewer record's
    entries in `fields`, mapped to the entry."""
    ids = {}
    for field_name in fields:
        entries = rec.data.get(field_name)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                ids[_item_id(rec.stem, field_name, entry)] = entry
    return ids


def concern_ids(rec: Record) -> dict[str, str]:
    """Content-derived ids for a coder record's `concerns` entries."""
    concerns = rec.data.get(CONCERN_FIELD)
    return {_item_id(rec.stem, CONCERN_FIELD, c): c
            for c in (concerns if isinstance(concerns, list) else []) if _non_empty_str(c)}


def _scope(stem: str) -> str | None:
    match = SCOPE_RE.match(stem)
    return match["scope"] if match else None


def _scope_task(scope: str) -> int | str:
    return int(scope.removeprefix("task-")) if scope.startswith("task-") else "final"


@dataclass
class ScopeRecords:
    reviewers: list[Record]  # well-formed reviewer records named for the scope
    coders: list[Record]     # well-formed coder records named for the scope
    problems: list[str]      # malformed or misfiled records named for the scope
    decisions: list[Record]  # every well-formed decision record in the store


def _scope_records(store_dir: Path, scope: str) -> ScopeRecords:
    """Records belong to a scope by file name (the dispatch supplies it);
    one whose `task` disagrees with its name is misfiled, and a malformed
    one hides its findings. Either is a problem for the scope's decision."""
    records = [r for r in load_records(store_dir) if r.ok or _scope(r.stem) == scope]
    in_scope = [r for r in records if _scope(r.stem) == scope]
    problems = [f"{r.stem}: {r.error}" for r in in_scope if not r.ok]
    problems += [f"{r.stem}: says task {r.data['task']!r}, but its name is for "
                 f"{_scope_task(scope)!r}" for r in in_scope
                 if r.ok and r.data["task"] != _scope_task(scope)]
    return ScopeRecords(
        reviewers=[r for r in in_scope if r.ok and r.data["role"] in REVIEWER_ROLES],
        coders=[r for r in in_scope if r.ok and r.data["role"] == "coder"],
        problems=problems,
        decisions=[r for r in records if r.ok and r.data["role"] == "decision"])


# --- triage: the per-task review-fix loop (schema 2) ---

TRIAGE_ENTRY = "triage"


def _scope_log(log: list[dict], task: int | str) -> list[dict]:
    """The log entries that count for `task`: everything for a numbered
    task, and only what follows the last close round for the whole-change
    gate, whose remediation run starts fresh (final-r2-* records)."""
    if task != "final":
        return log
    starts = [i for i, e in enumerate(log) if e.get("type") == "close_round"]
    return log[starts[-1] + 1:] if starts else log


def scope_prefix(log: list[dict], task: int | str) -> str:
    """The record-name prefix of `task`'s current records."""
    if task != "final":
        return f"task-{task}"
    return "final-r2" if close_rounds(log) else "final"


def triage_entries(log: list[dict], task: int | str) -> list[dict]:
    return [e for e in _scope_log(log, task) if e.get("type") == TRIAGE_ENTRY
            and e.get("task") == task]


def latest_triage(log: list[dict], task: int | str) -> dict | None:
    entries = triage_entries(log, task)
    return entries[-1] if entries else None


def _latest_coder(coders: list[Record]) -> Record | None:
    return max(coders, key=lambda r: (r.data.get("cycle", 0), r.stem), default=None)


def _finding_inputs(reviewers: list[Record]) -> list[dict]:
    """Each raised finding as triage reads it: its tags, and whether its
    reviewer flagged one of its sites as recurring or fix-introduced."""
    findings = []
    for rec in reviewers:
        field_name = FINDING_LIST_FIELD.get(rec.data["role"], "findings")
        flagged = {flag: {e.get("site") for e in rec.data.get(flag, [])} for flag in FLAG_FIELDS}
        for fid, entry in finding_ids(rec, (field_name,)).items():
            sites = set(entry["sites"])
            findings.append({"id": fid, "source": rec.stem, "gate": rec.data["role"] == "gate",
                             "severity": entry["severity"], "reach": entry["reach"],
                             "rule": entry["rule"], "sites": entry["sites"],
                             "recurring": bool(sites & flagged["recurring"]),
                             "introduced": bool(sites & flagged["introduced_by_fix"])})
    return findings


def _coder_deferrals(coder: Record | None, rules: dict[str, str]) -> list[dict]:
    """A coder's skipped notes and outside sites, each with an id, the rule
    it falls under, and the follow-up text to file."""
    if coder is None:
        return []
    out = []
    for entry in coder.data.get("notes_skipped", []):
        out.append({"id": _item_id(coder.stem, "notes_skipped", entry),
                    "rule": rules.get(entry["finding"], entry["reason"]),
                    "text": f"skipped note {entry['finding']}: {entry['reason']}"})
    for sweep in coder.data.get("sweeps", []):
        for site in sweep.get("sites_outside", []):
            out.append({"id": _item_id(coder.stem, "sites_outside", {"site": site,
                                                                     "rule": sweep["rule"]}),
                        "rule": sweep["rule"], "site": site,
                        "text": f"outside site {site}: {sweep['rule']}"})
    return out


def _ruled_since_last_entry(log: list[dict], task: int | str) -> bool:
    """A user ruling logged for `task` after its last triage entry. Which
    model codes the task is no ruling on the work, so it starts no round."""
    scoped = _scope_log(log, task)
    entries = [i for i, e in enumerate(scoped) if e.get("type") == TRIAGE_ENTRY
               and e.get("task") == task]
    if not entries:
        return False
    notes = (str(e.get("note", "")).lower() for e in scoped[entries[-1] + 1:]
             if e.get("type") == "progress" and e.get("task") == task)
    return any(n.startswith(RULING_PREFIX) and not n.startswith(OPUS_RULING_PREFIX) for n in notes)


def _user_waived(log: list[dict], scope: str | None = None) -> set[str]:
    """Ids the user settled with a ruling; with `scope`, only that scope's."""
    return {i for i, note in resolutions_from_log(log).items()
            if note.lower().startswith(RULING_PREFIX)
            and (scope is None or _scope(i.split("#")[0]) == scope)}


def _deferred_root_causes(decisions: list[Record], scope: str) -> dict[str, str]:
    """Coder `root cause:` concerns a decision of the scope excluded, mapped
    to the reason: deferred, so filed once and no longer open work."""
    return {e["finding"]: e["reason"] for d in decisions if _scope(d.stem) == scope
            for e in d.data["excluded"] if f"#{CONCERN_FIELD}[" in e["finding"]}


def triage_inputs(store_dir: Path, task: int | str) -> tuple[dict, list[Record], Record | None]:
    """Everything `triage.derive` reads for `task`, from the store; plus the
    scope's reviewer records and its latest coder record."""
    log = load_progress_log(store_dir)
    scope = scope_prefix(log, task)
    found = _scope_records(store_dir, scope)
    if found.problems:
        raise RecordError(f"record(s) named for task {task!r} can't be triaged; fix them "
                          "first: " + "; ".join(found.problems))
    if not found.reviewers:
        raise RecordError(f"task {task!r} has no reviewer record yet; triage reads the "
                          "review, so dispatch the reviewers first")
    coder = _latest_coder(found.coders)
    findings = _finding_inputs(found.reviewers)
    coder_data = coder.data if coder else {}
    waived = _user_waived(log, scope)
    deferred = _deferred_root_causes(found.decisions, scope)
    root_causes = [cid for cid, text in (concern_ids(coder).items() if coder else [])
                   if text.lower().startswith(ROOT_CAUSE_PREFIX)
                   and cid not in deferred and cid not in waived]
    # Only the reviewer that raised a finding answers a contest of it.
    answers = {a["finding"]: a["verdict"] for rec in found.reviewers
               for a in rec.data.get("contests", []) if a["finding"].startswith(f"{rec.stem}#")}
    rules = {f["id"]: f["rule"] for f in findings}
    inputs = {
        "findings": findings, "root_causes": root_causes,
        "reach_raised": {e["finding"] for e in coder_data.get("reach_raised", [])},
        "answers": answers, "waived": waived,
        "prior": triage_entries(log, task), "ruled": _ruled_since_last_entry(log, task),
        "undelivered_note": isinstance(task, int) and bool(undelivered_notes(log, task)),
        "model": coder_data.get("model"),
        "file_candidates": _coder_deferrals(coder, rules) + [
            {"id": cid, "rule": reason, "text": f"deferred root cause {cid}: {reason}"}
            for cid, reason in deferred.items()],
    }
    return inputs, found.reviewers, coder


def _file_deferrals(store_dir: Path, log: list[dict], task: int | str,
                    to_file: list[dict], texts: dict[str, dict]) -> list[str]:
    """File each new deferral: an outside site a later task's footprint
    covers goes to that task as a task-note; everything else is a
    follow-up carrying its rule, for the close batch."""
    done = set(completed_task_ids(log))
    owners = {f: other for other, entry in stage_map(log).items()
              if other != task and str(other) not in done for f in entry.get("files", [])}
    filed = []
    for item in to_file:
        detail = texts.get(item["id"], item)
        text = detail.get("text") or f"deferred {item['id']}: {item['rule']}"
        site = detail.get("site")
        owner = owners.get(_normalize_path(SITE_RE.match(site)["path"])) if site else None
        source = task if isinstance(task, int) else "final"
        if note_id("task-note" if owner else "follow-up", text, owner, None, source) in {
                n["id"] for n in notes_from_log(log)}:
            continue
        if owner is not None:
            filed.append(_file_note(store_dir, log, "task-note", text, for_task=owner,
                                    source=source))
        else:
            filed.append(_file_note(store_dir, log, "follow-up", text, source=source,
                                    rule=item["rule"]))
        log = load_progress_log(store_dir)
    return filed


def _tree_or_none(store_dir: Path) -> str | None:
    repo = _store_repo(store_dir)
    return snapshot_tree(repo) if repo is not None else None


def cmd_triage(store_dir: Path, task: int | str) -> None:
    """Derive the scope's next step from its records, append it as a triage
    entry, file its new deferrals, and print the step and its dispatch."""
    with store_lock(store_dir):
        inputs, reviewers, coder = triage_inputs(store_dir, task)
        digest = _inputs_digest(inputs, reviewers, coder)
        log = load_progress_log(store_dir)
        latest = latest_triage(log, task)
        baseline = _round_baseline(log, task)
        if latest is not None and (latest.get("inputs") == digest
                                   or _fix_is_open(store_dir, log, task, baseline)):
            # Nothing changed since the last step, or its fix hasn't
            # finished: asking again (after a compaction or a paused coder)
            # must not start another round.
            print(_render_triage(latest, [], baseline, scope_footprint(store_dir, log, task)))
            return
        result = triage_rules.derive(**inputs)
        texts = {c["id"]: c for c in inputs["file_candidates"]}
        log = load_progress_log(store_dir)
        filed_notes = _file_deferrals(store_dir, log, task, result.pop("to_file"), texts)
        recheck_records = _recheck_records(result, reviewers)
        entry = {"type": TRIAGE_ENTRY, "task": task, "tree": _tree_or_none(store_dir),
                 **result, "recheck_records": recheck_records, "inputs": digest, "at": _now()}
        if result["kind"] == "holistic":
            # The decision doc for the coder's upcoming fix cycle. Every fix
            # is cycle 2 or later, the first at `final` included, where no
            # coder wrote a first attempt.
            cycle = (coder.data["cycle"] if coder else 1) + 1
            entry["decision"] = f"{scope_prefix(log, task)}-decision-c{cycle}"
        _append_progress(store_dir, entry)
        snapshot = None
        if entry["kind"] in triage_rules.FIX_KINDS and entry["tree"] is not None:
            # The fix's baseline, taken in the same lock so nothing sits
            # between the step and the snapshot that `fix_round` pairs.
            snapshot = {"type": "snapshot", "task": task, "tree": entry["tree"],
                        "label": f"triage {entry['kind']} round {entry['round']}",
                        "coder_cycle": coder.data["cycle"] if coder else None}
            _append_progress(store_dir, snapshot)
        footprint = scope_footprint(store_dir, load_progress_log(store_dir), task)
    print(_render_triage(entry, filed_notes, snapshot, footprint))


def _round_baseline(log: list[dict], task: int | str) -> dict | None:
    """The snapshot triage took for the scope's latest step, or None when
    that step is not a fix or took none (a store from before triage
    snapshotted, or one outside git)."""
    at = max((i for i, e in enumerate(log) if e.get("type") == TRIAGE_ENTRY
              and e.get("task") == task), default=None)
    if at is None or at + 1 >= len(log):
        return None
    following = log[at + 1]
    if following.get("type") == "snapshot" and following.get("task") == task \
            and str(following.get("label", "")).startswith("triage "):
        return following
    return None


def _fix_is_open(store_dir: Path, log: list[dict], task: int | str,
                 baseline: dict | None) -> bool:
    """True while the latest step's fix hasn't finished: no coder record in
    the scope is done (or done with concerns) from that step's baseline, at
    a cycle newer than the coder record the step saw. The cycle matters when
    a round changed no code, so the next step's snapshot is the same tree."""
    if baseline is None:
        return False
    seen = baseline.get("coder_cycle")
    coders = _scope_records(store_dir, scope_prefix(log, task)).coders
    return not any(r.data.get("status") in DIAGNOSIS_STATUSES
                   and r.data.get("baseline") == baseline["tree"]
                   and (seen is None or r.data.get("cycle", 0) > seen) for r in coders)


def _inputs_digest(inputs: dict, reviewers: list[Record], coder: Record | None) -> str:
    """A digest of what triage read: the whole records (any rewrite, a
    re-check or a fix, is new work) and the user's rulings and waivers.
    The scope's earlier entries are left out, so an unchanged state yields
    the step already logged."""
    current = {key: sorted(value) if isinstance(value, set) else value
               for key, value in inputs.items() if key != "prior"}
    current["records"] = {r.stem: r.data for r in [*reviewers, *([coder] if coder else [])]}
    return _entry_digest(current)


def _recheck_records(result: dict, reviewers: list[Record]) -> list[str]:
    """The reviewer records to re-dispatch for the step. The gate is never
    dispatched: its findings re-check by re-staging and re-running it."""
    agents = [r for r in reviewers if r.data["role"] != "gate"]
    if result["recheck"] == "all":
        return sorted(r.stem for r in agents)
    if result["recheck"] == "spec":
        return sorted(r.stem for r in agents if r.data["role"] == "spec-reviewer")
    if result["recheck"] == "raising":
        stems = {r.stem for r in agents}
        return sorted({f["source"] for f in result["findings"]
                       if f["tier"] in ("patch", "holistic", "held")} & stems)
    return []


def _is_gate_stem(stem: str) -> bool:
    return stem.endswith("-gate")


def _render_triage(entry: dict, filed: list[str], baseline: dict | None = None,
                   footprint: set[str] | None = None) -> str:
    lines = [f"{_scope_name(entry['task'])} triage: {entry['kind']} "
             f"(round {entry['round']}, recheck {entry['recheck']})"]
    if baseline is not None:
        lines.append(f"Fix baseline: {baseline['tree']}")
        lines.append(f"Task files: {' '.join(sorted(footprint or ()))}")
    for finding in entry["findings"]:
        lines.append(f"  [{finding['id']}] {finding['tier']}: {finding['rule']} "
                     f"({finding['source']})")
    for cid in entry["root_causes"]:
        lines.append(f"  [{cid}] holistic: root cause")
    if entry.get("decision"):
        lines.append(f"decision doc: {entry['decision']}.json (written before the fix)")
    if entry["recheck_records"]:
        lines.append("re-check: " + ", ".join(entry["recheck_records"]))
    if entry["kind"] in triage_rules.FIX_KINDS and any(
            _is_gate_stem(f["source"]) and f["tier"] not in ("defer", "held")
            for f in entry["findings"]):
        lines.append("then re-stage and re-run `gate`")
    if entry["held"]:
        lines.append("held for the user: " + ", ".join(entry["held"]))
    if entry["settled"]:
        lines.append("settled: " + ", ".join(entry["settled"]))
    for nid in filed:
        lines.append(f"filed {nid}")
    return "\n".join(lines)


# --- gate: the scripted commit gate ---

GATE_EXCERPT_LINES = 20


def _gate_path(store_dir: Path, log: list[dict], task: int | str) -> Path:
    return store_dir / f"{scope_prefix(log, task)}-gate.json"


def _git_paths(top: Path, *args: str) -> list[str]:
    """A git command's NUL-delimited path list: unquoted, so a name with a
    space or a non-ASCII character comes back exactly as on disk."""
    return [p for p in _git(top, *args).split("\0") if p]


def _staged_scope(top: Path, files: list[str]) -> list[str]:
    return sorted(_git_paths(top, "diff", "--cached", "--name-only", "-z", "--no-relative",
                             "HEAD", "--", *files))


def scope_footprint(store_dir: Path, log: list[dict], task: int | str) -> set[str] | None:
    """The files a scope stages, gates and commits: a task's recorded
    footprint, or at `final` every task's plus the files the scope's coders
    changed, since a whole-change fix has no stage entry of its own."""
    footprint = task_footprint(log, task)
    if task != "final":
        return footprint
    coders = _scope_records(store_dir, scope_prefix(log, task)).coders
    changed = {_normalize_path(f) for r in coders for f in r.data.get("changed_files", [])}
    return (footprint or set()) | changed or None


def _stage_footprint(top: Path, files: list[str]) -> None:
    """Stage every change under the footprint paths (edits, new files and
    deletions) and nothing else. A path that is neither on disk nor tracked
    has nothing to stage."""
    tracked = set(_git_paths(top, "ls-files", "--full-name", "-z", "--", *files))
    present = [f for f in files if (top / f).exists() or f in tracked]
    if present:
        _git(top, "add", "-A", "--", *present)


def _run_shell(top: Path, command: str) -> tuple[bool, str]:
    """Run a gate command through the shell (Verify lines use `!` and
    `&&`); it passes only on exit 0. The command is the plan's own Verify
    or lint line, given on the orchestrator's command line, so it runs
    with the same trust as typing it in the terminal."""
    done = subprocess.run(command, shell=True, cwd=top, capture_output=True, text=True,
                          errors="replace")
    output = (done.stdout + done.stderr).strip().splitlines()
    return done.returncode == 0, "\n".join(output[-GATE_EXCERPT_LINES:])


def cmd_gate(store_dir: Path, task: int | str, test: str, lint: str | None) -> int:
    """Run labels on the staged added lines of the scope's files, then lint,
    then the task's Verify command; write the gate record and return the
    exit code (0 on pass, 1 on fail). A failing test is a serious local
    finding for triage; labels and lint failures go back to the coder.
    The store stays unlocked while lint and the tests run, since parallel
    tasks' agents write it meanwhile."""
    with store_lock(store_dir):
        log = load_progress_log(store_dir)
        footprint = scope_footprint(store_dir, log, task)
        if not footprint:
            raise RecordError(f"task {task!r} has no recorded footprint; record it with "
                              "`ledger.py stage` before gating it")
        top = _store_repo(store_dir)
        if top is None:
            raise RecordError(f"{store_dir} isn't inside a git work tree; the gate reads the "
                              "staged files")
        files = sorted(footprint)
        _stage_footprint(top, files)
        staged = _staged_scope(top, files)
        if not staged and task != "final":
            raise RecordError(f"nothing to gate: task {task!r}'s files ({', '.join(files)}) "
                              "have no changes")
        # At `final` with every fix already committed, the gate still runs
        # the suite, over HEAD.
        tree = _git(top, "write-tree").strip()
        coder = _latest_coder(_scope_records(store_dir, scope_prefix(log, task)).coders)
        hits = _excused_label_hits(find_process_labels(diff_trees(top, "HEAD", tree, staged)),
                                   coder.data.get(CONCERN_FIELD, []) if coder else []) \
            if staged else []
    commands = [{"kind": "labels", "command": "ledger.py labels (staged)",
                 "passed": not hits,
                 "excerpt": "\n".join(f"{h.path}:{h.line}: {h.label}: {h.text}"
                                      for h in hits)}]
    for kind, command in (("lint", lint), ("test", test)):
        if command:
            passed, excerpt = _run_shell(top, command)
            commands.append({"kind": kind, "command": command, "passed": passed,
                             "excerpt": excerpt})
    record = _gate_record(task, tree, commands, files)
    validate_record(record)
    with store_lock(store_dir):
        _write_json(_gate_path(store_dir, log, task), record)
    for command in commands:
        print(f"{command['kind']}: {'pass' if command['passed'] else 'FAIL'}  {command['command']}")
        if not command["passed"] and command["excerpt"]:
            print(command["excerpt"])
    print(f"gate: {record['status']}")
    return 0 if record["status"] == "pass" else 1


def cmd_commit(store_dir: Path, task: int | str, message: str, test: str, lint: str | None,
               light: bool = False) -> int:
    """Take a ready scope from staging to a completed commit: `ready`, the
    footprint check, staging, the gate (skipped when the last passing gate
    checked these very files), `git commit` of the footprint alone, then
    `complete`. Returns 1, printing why, at the first step that stops it;
    a commit already made is never undone."""
    if not message.strip():
        raise RecordError("--message is empty: give the commit its message")
    log = load_progress_log(store_dir)
    # A whole-change fix is committed before review-lite re-checks it, so
    # it commits without `ready` or `complete` once the coder has finished
    # the fix triage routed. The scope completes when triage reaches done.
    final_fix = task == "final" and _round_baseline(log, task) is not None \
        and not _fix_is_open(store_dir, log, task, _round_baseline(log, task))
    blockers = [] if final_fix else ready_blockers(store_dir, task, light)
    if blockers:
        for blocker in blockers:
            print(f"- {blocker}")
        print(f"{_scope_name(task)}: not committed")
        return 1
    footprint = scope_footprint(store_dir, log, task)
    if not footprint:
        raise RecordError(f"task {task!r} has no recorded footprint; record it with "
                          "`ledger.py stage` before committing it")
    top = _store_repo(store_dir)
    if top is None:
        raise RecordError(f"{store_dir} isn't inside a git work tree; nothing to commit")
    files = sorted(footprint)
    _check_coder_inside_footprint(store_dir, log, task, footprint)
    _stage_footprint(top, files)
    if not _gate_passed_on_staged(store_dir, log, task, top, files, test, lint) \
            and cmd_gate(store_dir, task, test, lint) != 0:
        return 1
    rewritten = _git_paths(top, "diff", "--name-only", "-z", "--", *files)
    if rewritten:
        print(f"{', '.join(rewritten)} changed while the gate ran (a formatter, say), so the gate "
              "didn't check what would be committed: run `commit` again to gate the new content")
        return 1
    before = _git(top, "rev-parse", "HEAD").strip()
    staged = _staged_scope(top, files)
    if not staged:
        if task == "final" and not final_fix:
            # Every whole-change fix was committed for its re-check, and
            # the gate just checked HEAD: the scope completes as it stands.
            return _complete(store_dir, task, f"nothing left to commit; the change is at "
                                              f"{before[:7]}", light)
        # An empty path list would commit the whole index, other tasks' too.
        print(f"{_scope_name(task)}: nothing to commit in {', '.join(files)}")
        return 1
    done = subprocess.run(["git", "commit", "--only", "--cleanup=verbatim", "-m", message,
                           "--", *staged], cwd=top, capture_output=True, text=True,
                          errors="replace")
    if done.returncode != 0:
        print((done.stdout + done.stderr).strip())
        print(f"{_scope_name(task)}: git refused the commit")
        return 1
    after = _git(top, "rev-parse", "HEAD").strip()
    print(f"committed {after}")
    if final_fix:
        print("final: the fix is committed; re-check it, then run `triage --task final`")
        return 0
    return _complete(store_dir, task, f"commits {before[:7]}..{after[:7]}", light)


def _complete(store_dir: Path, task: int | str, note: str, light: bool) -> int:
    try:
        cmd_append(store_dir, "complete", task, note, light)
    except RecordError as e:
        print(f"{_scope_name(task)} not completed: {e}")
        return 1
    print(f"{_scope_name(task)} complete")
    return 0


def _check_coder_inside_footprint(store_dir: Path, log: list[dict], task: int | str,
                                  footprint: set[str]) -> None:
    """A task's coder changed only files its footprint lists: a file outside
    it would be left out of the gate and the commit."""
    if not isinstance(task, int):
        return
    coder = _latest_coder(_scope_records(store_dir, scope_prefix(log, task)).coders)
    outside = sorted({_normalize_path(f) for f in (coder.data.get("changed_files", [])
                                                   if coder else [])} - footprint)
    if outside:
        raise RecordError(f"task {task}'s coder changed {', '.join(outside)}, outside its "
                          "recorded footprint: re-issue `ledger.py stage` with those files")


def _gate_passed_on_staged(store_dir: Path, log: list[dict], task: int | str, top: Path,
                           files: list[str], test: str, lint: str | None) -> bool:
    """The scope's last gate passed on these same files, staged exactly as
    they are now, with these same commands, so running it again would check
    nothing new. An unreadable gate record means gate again."""
    try:
        gate = json.loads(_gate_path(store_dir, log, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ran = {c.get("kind"): c.get("command") for c in gate.get("commands", [])
           if c.get("kind") in ("lint", "test")}
    wanted = {"test": test, **({"lint": lint} if lint else {})}
    return gate.get("status") == "pass" and sorted(gate.get("files", [])) == files \
        and ran == wanted and all(_blob(top, gate["tree"], f) == _blob(top, "", f) for f in files)


def _gate_record(task: int | str, tree: str, commands: list[dict], files: list[str]) -> dict:
    """The gate's record. A failing test is one finding whose text never
    carries the run's output (that stays in the command's excerpt), so the
    same failure keeps the same id from run to run."""
    findings = []
    failed_test = next((c for c in commands if c["kind"] == "test" and not c["passed"]), None)
    if failed_test is not None:
        findings.append({"severity": SERIOUS_SEVERITY, "reach": "local",
                         "rule": f"`{failed_test['command']}` passes", "sites": files,
                         "claim": "the test command exits non-zero; its output is the test "
                                  "command's excerpt in this record"})
    return {"schema": SCHEMA_VERSION, "agent": "ledger", "role": "gate", "task": task,
            "status": "pass" if all(c["passed"] for c in commands) else "fail",
            "tree": tree, "files": files, "commands": commands, "findings": findings,
            "recurring": [], "introduced_by_fix": []}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check_gate_matches_commit(store_dir: Path, task: int | str) -> None:
    """A task completes only after a passing gate on exactly what was
    committed: each gated file's blob in the gate's tree equals HEAD's."""
    log = load_progress_log(store_dir)
    path = _gate_path(store_dir, log, task)
    if not path.is_file():
        raise RecordError(f"task {task!r} has no gate record; run `ledger.py gate` on the "
                          "staged files before committing")
    gate = json.loads(path.read_text(encoding="utf-8"))
    if gate.get("status") != "pass":
        raise RecordError(f"task {task!r}'s last gate failed; fix, re-stage, and gate again")
    footprint = scope_footprint(store_dir, log, task)
    if footprint and sorted(footprint) != sorted(gate.get("files", [])):
        raise RecordError(f"task {task!r}'s footprint changed since its last gate; gate again")
    top = _store_repo(store_dir)
    if top is None:
        return
    differ = [f for f in gate.get("files", []) if _blob(top, gate["tree"], f) != _blob(top, "HEAD", f)]
    if differ:
        raise RecordError(f"{', '.join(differ)} changed between the gate and the commit; "
                          "re-stage and gate again")


def _blob(top: Path, tree: str, path: str) -> str | None:
    try:
        return _git(top, "rev-parse", f"{tree}:{path}").strip()
    except subprocess.CalledProcessError:
        return None


def _check_contest_answers(path: Path, data: dict) -> None:
    """A re-checking reviewer answers every contest the coder raised against
    one of its findings, so a finding closes only after it read the evidence."""
    scope = _scope(path.stem)
    coder = _latest_coder(_scope_records(path.parent, scope).coders) if scope else None
    if coder is None:
        return
    sent = {c["finding"] for c in coder.data.get("contested", [])
            if c["finding"].startswith(f"{path.stem}#")}
    missing = sorted(sent - {a["finding"] for a in data.get("contests", [])})
    if missing:
        raise RecordError(f"{path}: the coder contested {', '.join(missing)}; answer each in "
                          "`contests` with a concede or hold verdict and your reason")


def changed_lines(diff: str) -> dict[str, set[int]]:
    """New-side line numbers each file's hunks added or changed; a hunk that
    only deletes marks the line it deleted before. Hunk line counts are
    tracked (as `_file_line_changes` does), so an added line whose text
    starts with `++ ` is never read as a file header."""
    changed: dict[str, set[int]] = {}
    path, line_no, old_left, new_left = None, 0, 0, 0
    for raw in diff.split("\n"):
        if old_left > 0 or new_left > 0:
            tag = raw[:1]
            if tag == "+":
                new_left -= 1
                if path is not None:
                    changed.setdefault(path, set()).add(line_no)
                line_no += 1
            elif tag == "-":
                old_left -= 1
            elif tag != "\\":
                old_left, new_left, line_no = old_left - 1, new_left - 1, line_no + 1
            continue
        if raw.startswith("+++ "):
            path = _diff_side(raw[4:], "b/")
            continue
        header = HUNK_HEADER_RE.match(raw)
        if header:
            old_left = int(header.group(1) or 1)
            line_no, new_left = int(header.group(2)), int(header.group(3) or 1)
            if new_left == 0 and path is not None:
                changed.setdefault(path, set()).add(max(line_no, 1))
    return changed


def site_touches(site: str, changed: dict[str, set[int]]) -> bool:
    """Whether a site overlaps the changed lines (a bare path: any change)."""
    match = SITE_RE.match(site)
    lines = changed.get(_normalize_path(match["path"]), set())
    if match["start"] is None:
        return bool(lines)
    start = int(match["start"])
    end = int(match["end"]) if match["end"] else start
    return any(start <= n <= end for n in lines)


def _check_reraised_findings(path: Path, data: dict) -> None:
    """A settled finding raised again unchanged is refused; one marked
    `reopens` must name a settled finding and sit in code changed since it
    was settled."""
    log = load_progress_log(path.parent)
    settled_at: dict[str, str | None] = {}
    for entry in triage_entries(log, data["task"]):
        for fid in entry.get("settled", []):
            settled_at.setdefault(fid, entry.get("tree"))
    field_name = FINDING_LIST_FIELD[data["role"]]
    rec = Record(stem=path.stem, ok=True, data=data)
    repo = _store_repo(path.parent)
    for fid, finding in finding_ids(rec, (field_name,)).items():
        if fid in settled_at:
            raise RecordError(f"{path}: {fid} was settled; drop it, or mark a new finding "
                              "`reopens` with a site in code changed since")
        target = finding.get("reopens")
        if target is None:
            continue
        if target not in settled_at:
            raise RecordError(f"{path}: `reopens` names {target!r}, which isn't a settled "
                              "finding of this task")
        tree = settled_at[target]
        if repo is None or tree is None:
            continue
        paths = sorted({SITE_RE.match(site)["path"] for site in finding["sites"]})
        changed = changed_lines(diff_trees(repo, tree, snapshot_tree(repo), paths))
        if not any(site_touches(site, changed) for site in finding["sites"]):
            raise RecordError(f"{path}: reopens {target} at {', '.join(finding['sites'])}, but "
                              "none of those lines changed since it was settled")


def _check_decision_context(path: Path, data: dict) -> None:
    """A decision, named for its scope and cycle, answers every reviewer
    record in its scope, accounts for every finding on them, reconciles
    with every decision written before it, and cites precedents that
    exist in the repo. Coverage holds when the decision is written; a
    fix's `snapshot` pins it by digest."""
    scope = _check_decision_name(path, data)
    found = _scope_records(path.parent, scope)
    if found.problems:
        raise RecordError(f"record(s) named for {scope} hide their findings; fix them "
                          "first: " + "; ".join(found.problems))
    reviewers = found.reviewers
    _require_same_set("reviewer_records", set(data["reviewer_records"]),
                      {r.stem for r in reviewers},
                      f"well-formed {scope}-* reviewer records in the store")
    required = {i for r in reviewers for i in finding_ids(r)}
    known = required | {i for r in reviewers for i in finding_ids(r, OPTIONAL_FINDING_FIELDS)}
    known |= {i for r in found.coders for i in concern_ids(r)}
    # A root cause triage sent stays citable after the fix drops it, since
    # the fix's own check re-reads this decision.
    log = load_progress_log(path.parent)
    known |= {cid for e in triage_entries(log, _scope_task(scope)) for cid in e.get("root_causes", [])}
    accounted = {f for c in data["choices"] for f in c["findings"]}
    accounted |= {e["finding"] for e in data["excluded"]}
    unknown = sorted(accounted - known)
    if unknown:
        raise RecordError(f"no such finding on the reviewer records: {unknown} "
                          "(copy ids from `ledger.py findings`; a stale id means a "
                          "reviewer record changed)")
    missing = sorted(required - accounted)
    if missing:
        raise RecordError(f"findings not accounted for: {missing}; each needs a choice "
                          "or an `excluded` entry with its reason")
    _check_reconciled(path, data, found.decisions)
    _check_precedents(path.parent, data["choices"])


def _check_decision_name(path: Path, data: dict) -> str:
    """The decision's scope, from a name that matches its task and cycle."""
    match = DECISION_STEM_RE.match(path.stem)
    if (path.suffix != ".json" or not match or _scope_task(match["scope"]) != data["task"]
            or int(match["cycle"]) != data["cycle"]):
        scope = "final (final-r2 in a close-gate remediation run)" if data["task"] == "final" \
            else f"task-{data['task']}"
        raise RecordError(f"{path.name}: a decision for task {data['task']!r} at cycle "
                          f"{data['cycle']} is named <scope>-decision-c{data['cycle']}.json, "
                          f"scope {scope}")
    return match["scope"]


def _check_reconciled(path: Path, data: dict, decisions: list[Record]) -> None:
    """Every decision written before this one is reconciled; a later one
    may be, but can't be required, or the record would go stale."""
    others = {r.stem for r in decisions if r.stem != path.stem}
    # A decision naming itself is harmless; one naming a markdown decision
    # doc (from before decisions were records) reconciles with it.
    listed = {e["decision"] for e in data["reconciled"]} - {path.stem}
    legacy = {s for s in listed if (path.parent / f"{s}.md").is_file()}
    if listed - others - legacy:
        raise RecordError(f"reconciled: {sorted(listed - others - legacy)} not among the "
                          f"other decision docs in the store: {sorted(others)}")
    written = path.stat().st_mtime_ns
    earlier = {s for s in others if (path.parent / f"{s}.json").stat().st_mtime_ns < written}
    if earlier - listed:
        raise RecordError(f"reconciled: missing {sorted(earlier - listed)}; list every "
                          "decision written before this one")


def _require_same_set(field_name: str, listed: set[str], present: set[str], what: str) -> None:
    if listed - present:
        raise RecordError(f"{field_name}: {sorted(listed - present)} not among the {what}: "
                          f"{sorted(present)}")
    if present - listed:
        raise RecordError(f"{field_name}: missing {sorted(present - listed)}; list every "
                          f"one of the {what}")


def _check_precedents(store_dir: Path, choices: list[dict]) -> None:
    """Each cited path:line names a real file and lines inside it, in the
    store's repo, or the working directory's for a relocated store."""
    repo = None
    for where_from in (store_dir, Path.cwd()):
        try:
            repo = _toplevel(where_from).resolve()
            break
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    if repo is None:
        raise RecordError(f"{store_dir}: precedents resolve against the repo toplevel, but "
                          "neither the store nor the working directory is in a git repository")
    for idx, choice in enumerate(choices):
        for c_idx, candidate in enumerate(choice.get("candidates", [])):
            where = f"choices[{idx}].candidates[{c_idx}].precedent"
            match = PRECEDENT_RE.match(candidate["precedent"])
            target = (repo / match["path"]).resolve()
            if not target.is_relative_to(repo) or not target.is_file():
                raise RecordError(f"{where}: {match['path']!r} is not a file in the repo")
            if target.is_relative_to(store_dir.resolve()):
                raise RecordError(f"{where}: {match['path']!r} is in the store; cite the code")
            start, end = int(match["start"]), int(match["end"] or match["start"])
            n_lines = len(target.read_bytes().splitlines())
            if not 1 <= start <= end <= n_lines:
                raise RecordError(f"{where}: lines {start}-{end} are outside "
                                  f"{match['path']} ({n_lines} lines)")


def cmd_findings(path: Path) -> None:
    """What the decision to be written at `path` must account for: each
    finding id in its scope with a one-line summary, the optional
    cannot_verify and coder-concern ids, and the decisions to reconcile
    with."""
    match = DECISION_STEM_RE.match(path.stem)
    if path.suffix != ".json" or not match:
        raise RecordError(f"{path.name}: a decision is named <scope>-decision-c<cycle>.json "
                          "(scope task-N, final, or final-r2)")
    found = _scope_records(path.parent, match["scope"])
    reviewers = found.reviewers
    decisions = [r for r in found.decisions if r.stem != path.stem]
    print(f"reviewer records: {', '.join(r.stem for r in reviewers) or '(none)'}")
    for problem in found.problems:
        print(f"PROBLEM (a decision can't pass until it's fixed): {problem}")
    for title, fields in (("findings (each needs a choice or an exclusion)", FINDING_FIELDS),
                          ("cannot_verify (optional)", OPTIONAL_FINDING_FIELDS)):
        print(f"{title}:")
        for rec in reviewers:
            for finding_id, entry in finding_ids(rec, fields).items():
                site = f"{entry.get('file', '')}:{entry.get('line', '')}".strip(":")
                claim = str(entry.get("claim") or entry.get("requirement") or "")
                print(f"  [{finding_id}] {site} {claim[:160]}".rstrip())
    print("coder concerns (optional; a root cause sent for research):")
    for rec in found.coders:
        for concern_id, concern in concern_ids(rec).items():
            print(f"  [{concern_id}] {concern[:160]}")
    print(f"decisions to reconcile: {', '.join(r.stem for r in decisions) or '(none)'}")


def _is_store(directory: Path) -> bool:
    gitignore = directory / ".gitignore"
    return gitignore.is_file() and gitignore.read_text(encoding="utf-8").strip() == "*"


def _history_entry(stem: str, data: dict) -> dict:
    def count(key: str) -> int:
        value = data.get(key)
        return len(value) if isinstance(value, list) else 0

    entry = {"record": stem, "task": data.get("task"), "role": data.get("role"),
             # Reviewer cycle isn't validated; keep only an int so stats can sort.
             "cycle": data["cycle"] if type(data.get("cycle")) is int else None,
             "status": data.get("status"),
             "findings": count("issues") + count("findings"),
             "recurring": count("recurring"), "introduced_by_fix": count("introduced_by_fix")}
    if data.get("role") == "coder":
        entry["model"] = data.get("model")
        entry["baseline"] = data.get("baseline")
        na = [t["n/a"] for t in data.get("tests_first", []) if isinstance(t, dict) and "n/a" in t]
        if na:
            entry["tests_first_na"] = {c: na.count(c) for c in sorted(set(na))}
    return entry


def load_history(store_dir: Path) -> list[dict]:
    """The history lines, keeping the last one per (record, cycle): an agent
    may re-run `check` after fixing its record within one cycle."""
    path = store_dir / HISTORY_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RecordError(f"{path}: unreadable check history: {e}") from e
    latest: dict[tuple, dict] = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            raise RecordError(f"{path}:{n}: not a JSON line: {e}") from e
        if not isinstance(entry, dict):
            raise RecordError(f"{path}:{n}: expected a JSON object, got {type(entry).__name__}")
        latest[(entry.get("record"), entry.get("cycle"))] = entry
    return list(latest.values())


def _task_sort_key(task: object) -> tuple:
    return (0, task, "") if isinstance(task, int) else (1, 0, str(task))


def cmd_stats(store_dir: Path) -> None:
    """Per-cycle verdicts by task, then the fix-failure signals: records
    whose reviewers flagged `introduced_by_fix` or `recurring` entries."""
    history = load_history(store_dir)
    if not history:
        print("No history yet: records are logged when `check` passes.")
        return
    history.sort(key=lambda e: (_task_sort_key(e.get("task")), e.get("cycle") or 0,
                                e.get("record") or ""))
    current = object()
    for entry in history:
        if entry.get("task") != current:
            current = entry.get("task")
            print(f"task {current}")
        stem, prefix = entry.get("record") or "", f"task-{current}-"
        agent = stem[len(prefix):] if stem.startswith(prefix) else stem
        model = f"  model={entry['model']}" if entry.get("model") else ""
        print(f"  {agent:<26} c{entry.get('cycle') or '?'}  {entry.get('status')}  "
              f"findings={entry.get('findings', 0)}{model}")
    for signal in ("introduced_by_fix", "recurring"):
        flagged = [f"{e.get('record')} c{e.get('cycle') or '?'} ({e[signal]})"
                   for e in history if e.get(signal)]
        print(f"{signal}: {', '.join(flagged) if flagged else 'none'}")
    _print_rounds(load_progress_log(store_dir))
    na: dict[str, int] = {}
    for entry in history:
        for category, n in (entry.get("tests_first_na") or {}).items():
            na[category] = na.get(category, 0) + n
    print("tests_first n/a: " + (", ".join(f"{c}={n}" for c, n in sorted(na.items())) or "none"))


def _print_rounds(log: list[dict]) -> None:
    """Each triage entry by task: its step, the coder model the review
    judged, and how many findings it closed, saw survive, and saw a fix
    introduce."""
    entries = [e for e in log if e.get("type") == TRIAGE_ENTRY]
    if entries:
        print("rounds:")
    for task in sorted({e.get("task") for e in entries}, key=_task_sort_key):
        print(f"  {_scope_name(task)}")
        for e in (e for e in entries if e.get("task") == task):
            print(f"    round {e.get('round')} {e.get('kind')}  model={e.get('model')}  "
                  f"closed={e.get('closed')}  survived={e.get('survived')}  "
                  f"introduced={e.get('introduced')}")


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = None
    if n is None or n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def _task_arg(value: str) -> int | str:
    """A positive integer, or 'final' for the whole-change commit gate."""
    if value == "final":
        return value
    try:
        return _positive_int(value)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError("must be a positive integer or 'final'") from None


def _append_task_arg(value: str) -> int | str:
    """A task argument for `append`: also 'run', the scope of a ruling about
    the run as a whole."""
    if value == RUN_SCOPE:
        return value
    try:
        return _task_arg(value)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer, 'final' or '{RUN_SCOPE}'") from None


def _path_scope_arg(value: str) -> int | str:
    """A positive task number, or one of the PATH_SCOPES."""
    if value in PATH_SCOPES:
        return value
    try:
        return _positive_int(value)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer or one of {', '.join(PATH_SCOPES)}") from None


def _owner_arg(value: str) -> int | str:
    """A positive task number, or 'close' for the close."""
    if value == CLOSE_OWNER:
        return value
    try:
        return _positive_int(value)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer or '{CLOSE_OWNER}'") from None


def build_parser() -> argparse.ArgumentParser:
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument(
        "--store", default=None,
        help="override the store directory (default: .sdd/ at the repo toplevel)")

    parser = argparse.ArgumentParser(
        description="Typed record store for subagent-driven-development.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("read", parents=[store_parent], help="render the full store as markdown")
    sub.add_parser("open", parents=[store_parent], help="list unresolved open items")
    sub.add_parser("shapes", parents=[store_parent], help="list shared symbols recorded so far")
    sub.add_parser("completed", parents=[store_parent],
                    help="list completed task ids, one per line")
    sub.add_parser("store-dir", parents=[store_parent],
                    help="create the store if needed (seeding a self-ignoring "
                         ".gitignore) and print its resolved absolute path")
    sub.add_parser("stats", parents=[store_parent],
                    help="per-cycle verdicts by task from the check history, plus "
                         "records flagging introduced_by_fix or recurring")

    p_append = sub.add_parser("append", parents=[store_parent], help="append a progress note")
    p_append.add_argument("--type", required=True, choices=["progress", "complete"])
    p_append.add_argument("--task", required=True, type=_append_task_arg,
                           help="positive task number, 'final' for the whole-change gate, "
                                f"or '{RUN_SCOPE}' for a ruling about the whole run")
    p_append.add_argument("--note", required=True)
    p_append.add_argument("--light", action="store_true",
                          help="complete only: executing-plans' light path, which runs no "
                               "triage; recorded so the report shows it")

    p_ready = sub.add_parser("ready", parents=[store_parent],
                             help="list everything that stops the task from committing; "
                                  "exit 1 while anything does")
    p_ready.add_argument("--task", required=True, type=_task_arg)
    p_ready.add_argument("--light", action="store_true",
                         help="executing-plans' light path: skip the triage checks")

    p_note = sub.add_parser("note", parents=[store_parent],
                             help="file an orchestrator note and print its id")
    p_note.add_argument("--kind", required=True, choices=NOTE_KINDS)
    p_note.add_argument("--text", required=True)
    p_note.add_argument("--for", dest="for_task", type=_positive_int,
                         help="task-note only: the task whose brief carries it")
    p_note.add_argument("--owner", type=_owner_arg,
                         help=f"disclosure or question only: the task that settles it, "
                              f"or '{CLOSE_OWNER}'")
    p_note.add_argument("--from", dest="source", type=_append_task_arg,
                         help=f"where it arose: a task number, 'final' or '{RUN_SCOPE}'")
    p_note.add_argument("--rule", help="follow-up only: the rule it falls under; the report "
                                       "groups follow-ups by it")

    p_notes = sub.add_parser("notes", parents=[store_parent],
                              help="list the notes a task must receive; --deliver records "
                                   "the session delivering them, --waive one that doesn't "
                                   "apply")
    p_notes.add_argument("--task", required=True, type=_positive_int)
    notes_action = p_notes.add_mutually_exclusive_group()
    notes_action.add_argument("--deliver", action="store_true")
    notes_action.add_argument("--waive", metavar="ID")
    p_notes.add_argument("--reason", help="why the waived note doesn't apply")

    p_stage = sub.add_parser("stage", parents=[store_parent],
                              help="record a task's stage and file footprint; refuses a "
                                   "path shared with another unfinished task in the stage")
    p_stage.add_argument("--task", required=True, type=_task_arg,
                         help="a task number, or 'final' to add files to the whole-change "
                              "gate's footprint")
    p_stage.add_argument("--stage", type=_positive_int, help="the stage (a task number needs it)")
    p_stage.add_argument("--files", required=True, nargs="+")

    p_handle = sub.add_parser("handle", parents=[store_parent],
                               help="record the agent id behind a task's role, for "
                                    "SendMessage after a compaction")
    p_handle.add_argument("--task", required=True, type=_task_arg)
    p_handle.add_argument("--role", required=True, help="the agent name, e.g. python-coder")
    p_handle.add_argument("--agent", required=True, help="the agent id the dispatch returned")

    p_close = sub.add_parser("close-round", parents=[store_parent],
                              help="start the next close-gate round and print its "
                                   f"number; fails past the cap ({CLOSE_ROUND_CAP})")
    p_close.add_argument("--expect", required=True, type=_positive_int,
                          help="the round you are starting: 1 for a fresh close, "
                               "2 on return from a close-gate remediation")
    p_close.add_argument("--note", required=True)

    p_snapshot = sub.add_parser("snapshot", parents=[store_parent],
                                 help="record the working tree as a fix baseline and "
                                      "print its tree id (real index untouched)")
    p_snapshot.add_argument("--task", required=True, type=_task_arg)
    p_snapshot.add_argument("--label", required=True)

    p_baseline = sub.add_parser("baseline", parents=[store_parent],
                                 help="print the round a fix baseline starts: its kind, "
                                      "who re-checks it, its decision doc, its findings")
    p_baseline.add_argument("tree")
    p_baseline.add_argument("--task", required=True, type=_task_arg)

    p_findings = sub.add_parser("findings", parents=[store_parent],
                                 help="list the finding ids the decision to be written at "
                                      "a path must account for, and the decisions to "
                                      "reconcile with")
    p_findings.add_argument("decision_path", help="the decision's output path; a bare "
                                                  "filename resolves against --store")

    p_triage = sub.add_parser("triage", parents=[store_parent],
                              help="derive the task's next step from its review, log it, file "
                                   "its deferrals, and print the dispatch to make")
    p_triage.add_argument("--task", required=True, type=_task_arg)

    p_gate = sub.add_parser("gate", parents=[store_parent],
                            help="run labels, lint and the task's Verify command on the staged "
                                 "task files; write the gate record; exit 1 on a failure")
    p_gate.add_argument("--task", required=True, type=_task_arg)
    p_gate.add_argument("--test", required=True,
                        help="the task's Verify: command; passes only on exit 0")
    p_gate.add_argument("--lint", help="the project's lint command; passes only on exit 0")

    p_path = sub.add_parser("path", parents=[store_parent],
                            help="print a handoff file's path: a record or report for an "
                                 "agent in a task or scope, a gate's report, or a brief")
    p_path.add_argument("--task", required=True, type=_path_scope_arg,
                        help=f"a task number, or one of {', '.join(PATH_SCOPES)}")
    p_path.add_argument("--agent", help="the agent's registered name (not for a brief)")
    p_path.add_argument("--kind", default="record", choices=PATH_KINDS)

    p_commit = sub.add_parser("commit", parents=[store_parent],
                              help="ready, stage the task's footprint, gate, git commit it "
                                   "with the message, and complete the task; exit 1 at the "
                                   "first step that stops it")
    p_commit.add_argument("--task", required=True, type=_task_arg)
    p_commit.add_argument("--message", required=True, help="the commit message, verbatim")
    p_commit.add_argument("--test", required=True,
                          help="the task's Verify: command (the full suite at final)")
    p_commit.add_argument("--lint", help="the project's lint command")
    p_commit.add_argument("--light", action="store_true",
                          help="executing-plans' light path: no triage")

    p_diff = sub.add_parser("diff-since",
                             help="show what changed since a snapshot tree, new "
                                  "files included (never touches the working tree or "
                                  "index; writes git objects and runs clean filters)")
    p_diff.add_argument("tree")
    p_diff.add_argument("paths", nargs="*",
                        help="limit the diff to these paths (the task's own files)")

    p_labels = sub.add_parser("labels",
                               help="list review-process labels (task/cycle/finding ids, "
                                    "decision-doc vocabulary, hashes) on lines added "
                                    "since a tree; exit 1 if any, 2 on an error or a "
                                    "path that matches nothing")
    p_labels.add_argument("tree", help="the fix baseline, or HEAD for a first attempt")
    p_labels.add_argument("paths", nargs="*", help="limit the scan to these paths")

    p_resolve = sub.add_parser("resolve", parents=[store_parent],
                                help="record a resolution for an open item")
    p_resolve.add_argument("id")
    p_resolve.add_argument("--note", default="")

    p_clear = sub.add_parser("clear", parents=[store_parent],
                              help="remove records matching the naming convention "
                                   "(task-*-*/final-*), the run's handoff files (briefs, "
                                   "reports, gate reports, review packages), and the "
                                   "progress log; refuses while follow-ups, disclosures "
                                   "or questions are open")
    p_clear.add_argument("--discard-open", action="store_true",
                         help="clear even with open notes (the user confirmed the loss)")

    p_run_state = sub.add_parser("run-state", parents=[store_parent],
                                  help="the store's verdict (fresh, resume, remediation, "
                                       "finished, foreign, ambiguous) and next action, then "
                                       "where the run stands")
    p_run_state.add_argument("--plan", help="the plan you are running (default: the latest "
                                            "plan the store recorded)")
    sub.add_parser("report", parents=[store_parent],
                    help="what the completion report lists: rulings, follow-ups, "
                         "unlisted cases, dispositions, disclosures, questions")

    p_check = sub.add_parser("check", parents=[store_parent],
                              help="validate a single record file (write-time gate)")
    p_check.add_argument("record_path", help="path to the record JSON file to validate; "
                                              "a bare filename resolves against --store")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "check":
            cmd_check(args.record_path, args.store)
            return
        if args.command == "diff-since":
            repo = Path.cwd()
            _warn_submodules(repo)
            now = snapshot_tree(repo)
            diff = diff_trees(repo, args.tree, now, args.paths)
            unmatched = missing_paths(repo, args.paths, args.tree, now)
            if unmatched:
                print(f"WARNING: path(s) {', '.join(unmatched)} match nothing in either "
                      "tree; check the task's file list.", file=sys.stderr)
            print(diff, end="")
            return
        if args.command == "labels":
            repo = Path.cwd()
            _warn_submodules(repo)
            if args.tree.startswith("-"):
                raise RecordError(f"tree id must not start with '-': got {args.tree!r}")
            now = snapshot_tree(repo)
            unmatched = missing_paths(repo, args.paths, args.tree, now)
            if unmatched:
                # A typo in the file list must not turn the gate into a pass.
                print(f"ERROR: path(s) {', '.join(unmatched)} match nothing in either "
                      "tree; check the task's file list.", file=sys.stderr)
                sys.exit(2)
            hits = find_process_labels(diff_trees(repo, args.tree, now, args.paths))
            for hit in hits:
                print(f"{hit.path}:{hit.line}: {hit.label}: {hit.text}")
            if hits:
                sys.exit(1)
            return
        store_dir = get_store_dir(args.store)
        if args.command == "read":
            cmd_read(store_dir)
        elif args.command == "open":
            cmd_open(store_dir)
        elif args.command == "shapes":
            cmd_shapes(store_dir)
        elif args.command == "completed":
            cmd_completed(store_dir)
        elif args.command == "store-dir":
            cmd_store_dir(store_dir)
        elif args.command == "stats":
            cmd_stats(store_dir)
        elif args.command == "append":
            cmd_append(store_dir, args.type, args.task, args.note, args.light)
        elif args.command == "ready":
            sys.exit(cmd_ready(store_dir, args.task, args.light))
        elif args.command == "note":
            cmd_note(store_dir, args.kind, args.text, args.for_task, args.owner, args.source,
                     args.rule)
        elif args.command == "notes":
            cmd_notes(store_dir, args.task, args.deliver, args.waive, args.reason)
        elif args.command == "stage":
            cmd_stage(store_dir, args.task, args.stage, args.files)
        elif args.command == "handle":
            cmd_handle(store_dir, args.task, args.role, args.agent)
        elif args.command == "snapshot":
            _warn_submodules(Path.cwd())
            cmd_snapshot(store_dir, args.task, args.label, lambda: snapshot_tree(Path.cwd()))
        elif args.command == "baseline":
            cmd_baseline(store_dir, args.tree, args.task)
        elif args.command == "findings":
            cmd_findings(_resolve_check_path(args.decision_path, args.store))
        elif args.command == "triage":
            cmd_triage(store_dir, args.task)
        elif args.command == "gate":
            sys.exit(cmd_gate(store_dir, args.task, args.test, args.lint))
        elif args.command == "path":
            cmd_path(store_dir, args.task, args.agent, args.kind)
        elif args.command == "commit":
            sys.exit(cmd_commit(store_dir, args.task, args.message, args.test, args.lint,
                                args.light))
        elif args.command == "close-round":
            cmd_close_round(store_dir, args.note, _git_head(), args.expect)
        elif args.command == "resolve":
            cmd_resolve(store_dir, args.id, args.note)
        elif args.command == "clear":
            cmd_clear(store_dir, args.discard_open)
        elif args.command == "run-state":
            cmd_run_state(store_dir, args.plan)
        elif args.command == "report":
            cmd_report(store_dir)
        else:
            # A subcommand registered in build_parser but not wired here
            # must not exit 0 having done nothing.
            raise RuntimeError(f"unhandled command: {args.command}")
    except UsageError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, RecordError) as e:
        _fail(args.command, f"ERROR: {e}")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace").strip() if e.stderr else ""
        _fail(args.command, f"ERROR: git {' '.join(e.cmd[1:])} failed: {stderr}")
    except FileNotFoundError as e:
        _fail(args.command, f"ERROR: {e.filename or 'a required program'} not found: {e.strerror}")


def _fail(command: str, message: str) -> None:
    """Exit with `message`. `labels` uses 1 for "labels found", so its
    errors exit 2; every other command exits 1."""
    print(message, file=sys.stderr)
    sys.exit(2 if command == "labels" else 1)


if __name__ == "__main__":
    main()
