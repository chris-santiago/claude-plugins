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
own ignore rules say. progress.jsonl in that same dir is append-only,
orchestrator-only.

Philosophy (spec Sec 4/7, amended 2026-08-27): failures are loud, not
defensively rendered away. `check` is the write-time gate — an agent runs
it on its own freshly written record and fixes until it exits 0. Loading
records for a query isolates each file: one malformed record becomes one
malformed entry, never hides its siblings. Required-ness is scoped to
decision-driving fields only; informational fields are unvalidated.
Totality ("never crash on any input") is explicitly not a goal.

Usage: python3 ledger.py read|open|shapes|completed|store-dir|stats|clear [--store DIR]
       python3 ledger.py append --type progress|complete --task N|final --note "..." [--store DIR]
       python3 ledger.py close-round --expect 1|2 --note "..." [--store DIR]
       python3 ledger.py snapshot --task N --label "..." [--non-trivial (--decision RECORD | --settled-by cases|ruling)] [--store DIR]
       python3 ledger.py baseline <tree> --task N [--store DIR]
       python3 ledger.py findings <decision-path> [--store DIR]
       python3 ledger.py fix-count --task N [--store DIR]
       python3 ledger.py diff-since <tree> [<path>...]   (takes no --store)
       python3 ledger.py labels <tree> [<path>...]       (takes no --store)
       python3 ledger.py resolve <id> [--note "..."] [--store DIR]
       python3 ledger.py check <record-path> [--store DIR]

A per-task decision is itself a record (role "decision", written by
remediating-issues' per-task variant). Beyond its own shape, `check`
verifies it against the store and the repo: it accounts for every
finding on every reviewer record in its scope (task-N, final, or
final-r2, from the file names), reconciles with every decision written
before it, and cites precedents that exist. A
non-trivial `snapshot` takes one (or names why none is owed), so a fix
cannot start from a decision nobody researched.

Importable API: see __all__ below — the module's public query/validate/
render surface (data classes, `get_store_dir`, the `load_*`/`compute_*`/
`list_*`/`render_*` functions). `task_brief.py` imports a subset of it
(`get_store_dir`, `ensure_store`, `load_records`, `list_shapes`,
`render_shapes`); the CLI
subcommand handlers (`cmd_*`), `build_parser`, and `main` are plumbing
invoked only through this script's own `main()` and are not part of the
importable surface. Functions raise instead of calling sys.exit, so
callers (task_brief.py, tests) own exit codes.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RecordError", "Record", "OpenItem", "Shape",
    "get_store_dir", "ensure_store", "validate_record",
    "load_records", "load_progress_log", "resolutions_from_log",
    "compute_open_items", "list_shapes", "render_shapes", "render_store_markdown",
    "completed_task_ids", "close_rounds", "CLOSE_ROUND_CAP",
    "snapshot_tree", "diff_since", "diff_trees", "missing_paths", "submodule_paths",
    "LabelHit", "find_process_labels", "HISTORY_FILENAME", "load_history",
    "non_trivial_fix_count", "check_record", "finding_ids", "find_baseline",
]

SCHEMA_VERSION = 1
ENVELOPE_FIELDS = ("schema", "agent", "role", "task")

STATUS_ENUMS = {
    "coder": {"done", "done_with_concerns", "needs_context", "blocked"},
    "spec-reviewer": {"compliant", "issues"},
    "quality-reviewer": {"approved", "issues"},
    "review-lite": {"clean", "block", "escalate"},
    # A per-task decision: `escalated` when any finding goes to the user.
    "decision": {"decided", "escalated"},
}
# Derived, never restated: a role added to STATUS_ENUMS alone (or vice
# versa) would turn `check`'s corrective RecordError into a raw KeyError
# at the STATUS_ENUMS[role] lookup below.
VALID_ROLES = frozenset(STATUS_ENUMS)
CODER_OPEN_STATUSES = {"blocked", "needs_context"}
REVIEWER_OPEN_STATUSES = {"issues", "block", "escalate"}
REVIEWER_ROLES = VALID_ROLES - {"coder", "decision"}
# Roles whose records carry a validated `cycle`.
CYCLE_ROLES = ("coder", "decision")

# Decision-driving list fields beyond `status`, by role: required present,
# must be a list, and each entry must be an object. Everything else
# (changed_files, tests, concerns, report, issues, findings, linter,
# cycle, ...) is informational and unvalidated (spec Sec 7 amendment).
DECISION_LIST_FIELDS = {
    "coder": ("duplication_pending", "new_shared_symbols"),
    "spec-reviewer": ("cannot_verify", "recurring"),
    "quality-reviewer": ("recurring",),
}

# Decision-driving list fields validated only when present (2026-10-06).
# Contracts still tell agents to always write them; absence is tolerated
# so a mid-run plugin upgrade doesn't turn every earlier record malformed.
OPTIONAL_LIST_FIELDS = {
    "spec-reviewer": ("introduced_by_fix", "issues"),
    "quality-reviewer": ("introduced_by_fix", "findings"),
    "review-lite": ("findings",),
}

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

# Decision records (2026-10-09). A reviewer finding is an `issues` or
# `findings` entry, and a decision must account for every one: a choice
# or an exclusion with its reason. `cannot_verify` entries may be decided
# too, but aren't required. Each fix choice weighs at least two
# candidates, each citing the code it mirrors as path:line or
# path:start-end (relative to the repo toplevel).
FINDING_FIELDS = ("issues", "findings")
OPTIONAL_FINDING_FIELDS = ("cannot_verify",)
CHOICE_KEYS = {"fix": ("reframe", "choice", "completeness"), "escalate": ("why", "evidence")}
CANDIDATE_KEYS = ("name", "precedent", "why")
CASE_KEYS = ("case", "today", "under_fix", "result")
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
# Why a non-trivial fix owes no decision record: the brief's Cases: line
# already settles it, or the user ruled on it.
SETTLED_BY = ("cases", "ruling")

PROGRESS_FILENAME = "progress.jsonl"

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
    if data["schema"] != SCHEMA_VERSION:
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
        # Only a coder reporting a finished fix owes the fix-mode fields: one
        # that stopped mid-fix (blocked / needs_context) has fixed nothing yet.
        if data["cycle"] >= 2 and data["status"] in DIAGNOSIS_STATUSES:
            _validate_fix(data)
    elif role == "decision":
        _validate_decision(data)


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
    if not isinstance(stems, list) or not stems or not all(map(_non_empty_str, stems)):
        raise RecordError(f"reviewer_records: got {stems!r}, expected a non-empty list of "
                          "record names (e.g. task-3-spec-reviewer)")
    seen: set[str] = set()
    escalated = False
    for idx, choice in enumerate(_require_objects(data, "choices", min_len=1)):
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
            for c_idx, case in enumerate(_require_objects(choice, "cases", min_len=1)):
                _require_strs(case, CASE_KEYS, f"{where}.cases[{c_idx}]")
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
        if field_name == "hunk_map" and not entries:
            raise RecordError(
                "hunk_map: a finished fix changed something, so it needs at least "
                "one entry; got an empty list")
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


def _entry_digest(entry: dict) -> str:
    """First 8 hex of the sha1 of the entry's canonical JSON — the
    content-derived component of an entry-level id (spec Sec 6, amended
    2026-08-27): a resolution id names *what the entry says*, not *where
    it sits*, so a record rewritten with a different entry at the same
    position gets a new id and the old resolution can't suppress it."""
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]


def _item_id(stem: str, field_name: str, entry: dict) -> str:
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

    if role == "decision":
        # Waiting on the user: open until `resolve` logs the ruling.
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
        if entry.get("type") == "progress":
            lines.append(f"- task {entry.get('task')}: {entry.get('note', '')}")
        elif entry.get("type") == "complete":
            lines.append(f"- task {entry.get('task')} **COMPLETE**: {entry.get('note', '')}")
        elif entry.get("type") == "resolution":
            lines.append(f"- resolves `{entry.get('resolves')}`: {entry.get('note', '')}")
        elif entry.get("type") == "snapshot":
            lines.append(f"- task {entry.get('task')} snapshot `{entry.get('tree')}`: "
                          f"{entry.get('label', '')} ({_route_text(entry)})")
        elif entry.get("type") == "close_round":
            lines.append(f"- **close round {entry.get('round')}** at `{entry.get('head', '')}`: "
                          f"{entry.get('note', '')}")
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


def close_rounds(log: list[dict]) -> int:
    """How many close-gate rounds have started in this store — a typed
    count, so the round cap survives compaction instead of living in the
    orchestrator's memory."""
    return sum(1 for entry in log if entry.get("type") == "close_round")


def cmd_read(store_dir: Path) -> None:
    print(render_store_markdown(load_records(store_dir), load_progress_log(store_dir)))


def cmd_open(store_dir: Path) -> None:
    records = load_records(store_dir)
    resolved = set(resolutions_from_log(load_progress_log(store_dir)))
    items = compute_open_items(records, resolved)
    if not items:
        print("No open items.")
        return
    for item in items:
        print(f"[{item.id}] {item.kind}: {item.summary}")


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


def cmd_append(store_dir: Path, entry_type: str, task: int | str, note: str) -> None:
    ensure_store(store_dir)
    _append_jsonl(store_dir / PROGRESS_FILENAME, {"type": entry_type, "task": task, "note": note})


def cmd_close_round(store_dir: Path, note: str, head: str, expect: int) -> None:
    """Start the next close-gate round and print its number. `expect` is
    the round the caller believes it is starting (1 for a fresh close, 2
    on return from a close-gate remediation); a mismatch means the store
    belongs to another run, so it raises instead of silently starting a
    new run at round 2. The entry records the HEAD the round reviews, so
    round 2 can name the remediation range (round-1 head..HEAD). Past
    CLOSE_ROUND_CAP this raises and appends nothing: the cap is the
    escalation trigger, so a further round must never start silently."""
    started = close_rounds(load_progress_log(store_dir))
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
    ensure_store(store_dir)
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "close_round", "round": started + 1, "head": head, "note": note})
    print(started + 1)


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


def cmd_snapshot(store_dir: Path, task: int | str, label: str, tree: str | Callable[[], str],
                 non_trivial: bool = False, decision: str | None = None,
                 settled_by: str | None = None) -> None:
    """Record a fix baseline as a typed progress entry (so it survives
    compaction) and print the tree id for the dispatch. `non_trivial`
    marks a fix whose batch has a non-trivial finding: those are what the
    escalation cap counts (see non_trivial_fix_count). Such a fix names
    its route: a decision record for this task that passes `check`, or
    why none is owed (`settled_by`). `tree` may be a callable, so a
    refused route writes no git objects."""
    route = _fix_route(store_dir, task, non_trivial, decision, settled_by)
    tree = tree() if callable(tree) else tree
    ensure_store(store_dir)
    entry = {"type": "snapshot", "task": task, "label": label, "tree": tree}
    if non_trivial:
        entry["non_trivial"] = True
        entry.update(route)
    _append_jsonl(store_dir / PROGRESS_FILENAME, entry)
    print(tree)


def _fix_route(store_dir: Path, task: int | str, non_trivial: bool,
               decision: str | None, settled_by: str | None) -> dict:
    if not non_trivial:
        if decision or settled_by:
            raise RecordError("--decision and --settled-by route a non-trivial fix; "
                              "add --non-trivial")
        return {}
    if bool(decision) == bool(settled_by):
        raise RecordError("a non-trivial fix needs exactly one of --decision <record> "
                          f"or --settled-by {'|'.join(SETTLED_BY)}")
    if settled_by:
        if settled_by not in SETTLED_BY:
            raise RecordError(f"--settled-by: got {settled_by!r}, allowed set: {list(SETTLED_BY)}")
        if settled_by == "ruling" and not _ruling_logged(load_progress_log(store_dir), task):
            raise RecordError(f"--settled-by ruling: no ruling is logged for task {task!r}; "
                              f"log it first (a progress note or an escalation's resolution "
                              f"starting \"{RULING_PREFIX}\")")
        return {"settled_by": settled_by}
    path = _resolve_check_path(decision, str(store_dir))
    if path.parent.resolve() != store_dir.resolve():
        raise RecordError(f"{path}: a decision record must be in the store it answers "
                          f"({store_dir})")
    data = check_record(path)
    if data["role"] != "decision":
        raise RecordError(f"{path}: role {data['role']!r} is not a decision record")
    if task != data["task"]:
        raise RecordError(f"{path}: decides task {data['task']!r}, not task {task!r}")
    if not any(c["kind"] == "fix" for c in data["choices"]):
        raise RecordError(f"{path}: every choice escalates; there is nothing to fix")
    digest = _file_sha256(path)
    _check_reroute(load_progress_log(store_dir), task, path, digest)
    return {"decision": path.stem, "decision_sha256": digest}


def _check_reroute(log: list[dict], task: int | str, path: Path, digest: str) -> None:
    """A decision routes one fix. The coder may refuse it before changing
    anything, so a rewrite can route that same fix again (fix-count counts
    it once), but only while it is still the task's latest fix and no close
    round has started since; a later fix needs a new decision."""
    routed = [i for i, e in enumerate(log) if e.get("type") == "snapshot"
              and e.get("decision") == path.stem]
    if not routed:
        return
    last = routed[-1]
    label = log[last].get("label")
    if any(log[i].get("decision_sha256") == digest for i in routed):
        raise RecordError(f"{path}: unchanged since it routed fix {label!r}; a further "
                          "fix needs a new decision")
    if any(e.get("type") == "close_round" or (e.get("type") == "snapshot" and e.get("task") == task)
           for e in log[last + 1:]):
        raise RecordError(f"{path}: routed fix {label!r}, and the task has moved on since; "
                          "a later fix needs a new decision at its own cycle")


def _ruling_logged(log: list[dict], task: int | str) -> bool:
    """A user ruling for `task` logged since its last fix baseline: a
    progress note on it, or the resolution of an escalation in one of its
    decisions. An older ruling was already acted on."""
    scopes = ("final", "final-r2") if task == "final" else (f"task-{task}",)
    snapshots = [i for i, e in enumerate(log) if e.get("type") == "snapshot" and e.get("task") == task]
    for e in log[snapshots[-1] + 1:] if snapshots else log:
        note = str(e.get("note", "")).lower()
        if not note.startswith(RULING_PREFIX):
            continue
        if e.get("type") == "progress" and e.get("task") == task:
            return True
        if e.get("type") == "resolution" and _scope(str(e.get("resolves", ""))) in scopes:
            return True
    return False


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_baseline(log: list[dict], tree: str, task: int | str) -> dict:
    """The last snapshot entry recording `tree` for `task`."""
    matches = [e for e in log if e.get("type") == "snapshot"
               and e.get("tree") == tree and e.get("task") == task]
    if not matches:
        raise RecordError(f"no snapshot of tree {tree!r} for task {task!r}: a fix "
                          "baseline comes only from `ledger.py snapshot`")
    return matches[-1]


def cmd_baseline(store_dir: Path, tree: str, task: int | str) -> None:
    """Print how a fix baseline was routed: `decision: <path>`,
    `settled-by: cases|ruling`, `trivial`, or `unrecorded` (a non-trivial
    snapshot from before routes existed). A decision must be byte-for-byte
    the one `snapshot` checked; its coverage was checked then, and later
    records (another task's decision, a re-review) don't reopen it."""
    entry = find_baseline(load_progress_log(store_dir), tree, task)
    kind, value = _route(entry)
    if kind == "decision":
        path = store_dir / f"{value}.json"
        if not path.is_file() or _file_sha256(path) != entry.get("decision_sha256"):
            raise RecordError(f"{path}: missing or changed since the snapshot checked it; "
                              "a changed decision needs `check` and a new snapshot")
        value = str(path)
    print(f"{kind}: {value}" if value else kind)


def _route(entry: dict) -> tuple[str, str]:
    """A snapshot's route as (kind, value): decision, settled-by, trivial,
    or unrecorded (non-trivial, from before routes were logged)."""
    if not entry.get("non_trivial"):
        return "trivial", ""
    if entry.get("decision"):
        return "decision", entry["decision"]
    if entry.get("settled_by"):
        return "settled-by", entry["settled_by"]
    return "unrecorded", ""


def _route_text(entry: dict) -> str:
    return " ".join(part for part in _route(entry) if part)


def non_trivial_fix_count(log: list[dict], task: int | str) -> int:
    """Non-trivial fix attempts dispatched for `task`: one flagged snapshot
    each. A resumed paused fix reuses its baseline, and trivial fixes,
    labels bounces and reviewer re-dispatches take no flagged snapshot,
    so none of them counts. For "final" (the whole-change gate), only
    snapshots after the last close round count."""
    if task == "final":
        # A close-gate remediation run reuses the store, and its whole-change
        # gate (final-r2-* records) starts fresh, so count from the last round.
        starts = [i for i, e in enumerate(log) if e.get("type") == "close_round"]
        log = log[starts[-1] + 1:] if starts else log
    fixes = [e for e in log if e.get("type") == "snapshot"
             and e.get("task") == task and e.get("non_trivial")]
    # A rewritten decision re-routing a fix the coder refused is one attempt.
    decisions = {e["decision"] for e in fixes if e.get("decision")}
    return len(decisions) + sum(1 for e in fixes if not e.get("decision"))


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
    log = load_progress_log(store_dir)
    already_resolved = resolutions_from_log(log)
    if resolve_id in already_resolved:
        raise RecordError(
            f"{resolve_id!r} already resolved (note: {already_resolved[resolve_id]!r})")

    records = load_records(store_dir)
    items = compute_open_items(records, set(already_resolved))
    open_ids = sorted(item.id for item in items if item.kind in RESOLVABLE_KINDS)
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
    ensure_store(store_dir)
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "resolution", "resolves": resolve_id, "note": note})


# Store-managed handoff files beyond the JSON records (decision docs are
# records): briefs, reports, gate reports, and review packages. Gate
# reviewers read their own report path as their prior verdict, so these
# must not outlive the run that wrote them.
HANDOFF_FILE_PATTERNS = ("task-*-*.md", "design-review-*.md", "intent-recheck.md",
                         "intent-issue.md", "mutation-review.md", "review-*.diff")


def cmd_clear(store_dir: Path) -> None:
    """Delete files whose stem matches the record naming convention
    (task-*-* or final-*), the handoff files the run wrote
    (HANDOFF_FILE_PATTERNS), the progress log and the check history —
    content validity is
    irrelevant: a malformed record-attempt is clearable, an unrelated
    notes.json is not."""
    if store_dir.is_dir():
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
    return data


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


def _scope(stem: str) -> str | None:
    match = SCOPE_RE.match(stem)
    return match["scope"] if match else None


def _scope_task(scope: str) -> int | str:
    return int(scope.removeprefix("task-")) if scope.startswith("task-") else "final"


@dataclass
class ScopeRecords:
    reviewers: list[Record]  # well-formed reviewer records named for the scope
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
        problems=problems,
        decisions=[r for r in records if r.ok and r.data["role"] == "decision"])


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
    cannot_verify ids, and the decisions to reconcile with."""
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
    print(f"decisions to reconcile: {', '.join(r.stem for r in decisions) or '(none)'}")


def _is_store(directory: Path) -> bool:
    gitignore = directory / ".gitignore"
    return gitignore.is_file() and gitignore.read_text(encoding="utf-8").strip() == "*"


def _history_entry(stem: str, data: dict) -> dict:
    def count(key: str) -> int:
        value = data.get(key)
        return len(value) if isinstance(value, list) else 0

    return {"record": stem, "task": data.get("task"), "role": data.get("role"),
            # Reviewer cycle isn't validated; keep only an int so stats can sort.
            "cycle": data["cycle"] if type(data.get("cycle")) is int else None,
            "status": data.get("status"),
            "findings": count("issues") + count("findings"),
            "recurring": count("recurring"), "introduced_by_fix": count("introduced_by_fix")}


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
    _print_fix_routes(load_progress_log(store_dir))
    if not history:
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
        print(f"  {agent:<26} c{entry.get('cycle') or '?'}  {entry.get('status')}  "
              f"findings={entry.get('findings', 0)}")
    for signal in ("introduced_by_fix", "recurring"):
        flagged = [f"{e.get('record')} c{e.get('cycle') or '?'} ({e[signal]})"
                   for e in history if e.get(signal)]
        print(f"{signal}: {', '.join(flagged) if flagged else 'none'}")


def _print_fix_routes(log: list[dict]) -> None:
    """Each fix baseline and its route, so a non-trivial fix that skipped
    the decision step shows up without reading the transcript."""
    snapshots = [e for e in log if e.get("type") == "snapshot"]
    if snapshots:
        print("fixes:")
    for entry in snapshots:
        print(f"  task {entry.get('task')} {entry.get('label', '')}: {_route_text(entry)}")


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
    p_append.add_argument("--task", required=True, type=_task_arg,
                           help="positive task number, or 'final' for the whole-change gate")
    p_append.add_argument("--note", required=True)

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
    p_snapshot.add_argument("--non-trivial", action="store_true",
                            help="the fix batch has a non-trivial finding; counted by "
                                 "fix-count, and needs --decision or --settled-by")
    route = p_snapshot.add_mutually_exclusive_group()
    route.add_argument("--decision", metavar="RECORD",
                       help="the decision record the fix implements; must pass check")
    route.add_argument("--settled-by", choices=SETTLED_BY,
                       help="why no decision record is owed: the brief's Cases: line "
                            "settles the batch, or the user ruled on it")

    p_baseline = sub.add_parser("baseline", parents=[store_parent],
                                 help="print how a fix baseline was routed (decision "
                                      "record path, settled-by, trivial), re-checking "
                                      "its decision record")
    p_baseline.add_argument("tree")
    p_baseline.add_argument("--task", required=True, type=_task_arg)

    p_findings = sub.add_parser("findings", parents=[store_parent],
                                 help="list the finding ids the decision to be written at "
                                      "a path must account for, and the decisions to "
                                      "reconcile with")
    p_findings.add_argument("decision_path", help="the decision's output path; a bare "
                                                  "filename resolves against --store")

    p_count = sub.add_parser("fix-count", parents=[store_parent],
                              help="print how many non-trivial fixes the task has had "
                                   "(snapshots taken with --non-trivial)")
    p_count.add_argument("--task", required=True, type=_task_arg)

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

    sub.add_parser("clear", parents=[store_parent],
                    help="remove records matching the naming convention "
                         "(task-*-*/final-*), the run's handoff files (briefs, "
                         "reports, gate reports, review packages), and the "
                         "progress log")

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
            cmd_append(store_dir, args.type, args.task, args.note)
        elif args.command == "snapshot":
            _warn_submodules(Path.cwd())
            cmd_snapshot(store_dir, args.task, args.label, lambda: snapshot_tree(Path.cwd()),
                         args.non_trivial, args.decision, args.settled_by)
        elif args.command == "baseline":
            cmd_baseline(store_dir, args.tree, args.task)
        elif args.command == "findings":
            cmd_findings(_resolve_check_path(args.decision_path, args.store))
        elif args.command == "fix-count":
            print(non_trivial_fix_count(load_progress_log(store_dir), args.task))
        elif args.command == "close-round":
            cmd_close_round(store_dir, args.note, _git_head(), args.expect)
        elif args.command == "resolve":
            cmd_resolve(store_dir, args.id, args.note)
        elif args.command == "clear":
            cmd_clear(store_dir)
        else:
            # A subcommand registered in build_parser but not wired here
            # must not exit 0 having done nothing.
            raise RuntimeError(f"unhandled command: {args.command}")
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
