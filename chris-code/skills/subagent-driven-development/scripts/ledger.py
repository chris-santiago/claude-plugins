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

Usage: python3 ledger.py read|open|shapes|completed|store-dir|clear [--store DIR]
       python3 ledger.py append --type progress|complete --task N|final --note "..." [--store DIR]
       python3 ledger.py close-round --expect 1|2 --note "..." [--store DIR]
       python3 ledger.py resolve <id> [--note "..."] [--store DIR]
       python3 ledger.py check <record-path> [--store DIR]

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
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RecordError", "Record", "OpenItem", "Shape",
    "get_store_dir", "ensure_store", "validate_record",
    "load_records", "load_progress_log", "resolutions_from_log",
    "compute_open_items", "list_shapes", "render_shapes", "render_store_markdown",
    "completed_task_ids", "close_rounds", "CLOSE_ROUND_CAP",
]

SCHEMA_VERSION = 1
ENVELOPE_FIELDS = ("schema", "agent", "role", "task")

STATUS_ENUMS = {
    "coder": {"done", "done_with_concerns", "needs_context", "blocked"},
    "spec-reviewer": {"compliant", "issues"},
    "quality-reviewer": {"approved", "issues"},
    "review-lite": {"clean", "block", "escalate"},
}
# Derived, never restated: a role added to STATUS_ENUMS alone (or vice
# versa) would turn `check`'s corrective RecordError into a raw KeyError
# at the STATUS_ENUMS[role] lookup below.
VALID_ROLES = frozenset(STATUS_ENUMS)
CODER_OPEN_STATUSES = {"blocked", "needs_context"}
REVIEWER_OPEN_STATUSES = {"issues", "block", "escalate"}

# Decision-driving list fields beyond `status`, by role: required present,
# must be a list, and each entry must be an object. Everything else
# (changed_files, tests, concerns, report, issues, findings, linter,
# cycle, ...) is informational and unvalidated (spec Sec 7 amendment).
DECISION_LIST_FIELDS = {
    "coder": ("duplication_pending", "new_shared_symbols"),
    "spec-reviewer": ("cannot_verify", "recurring", "introduced_by_fix"),
    "quality-reviewer": ("recurring", "introduced_by_fix"),
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

PROGRESS_FILENAME = "progress.jsonl"

# Close-gate rounds (2026-10-04): each run of verification-before-
# completion's review gates is one round. Round 1 is the first close;
# round 2 re-checks a batched remediation. Findings after the last round
# escalate to the user — a further round is refused, not counted.
CLOSE_ROUND_CAP = 2


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

    for field_name in DECISION_LIST_FIELDS.get(role, ()):
        if field_name not in data:
            raise RecordError(f"missing required field(s): {field_name}")
        value = data[field_name]
        if not isinstance(value, list):
            raise RecordError(
                f"{field_name}: got {value!r} (type {type(value).__name__}), "
                f"expected a list")
        for idx, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise RecordError(
                    f"{field_name}[{idx}]: got {entry!r}, expected an object")

    if role == "coder" and "cycle" in data:
        cycle = data["cycle"]
        # bool is an int subclass; True would silently read as cycle 1.
        if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 1:
            raise RecordError(
                f"cycle: got {cycle!r}, expected a positive integer "
                "(1 on a first attempt, prior + 1 on a fix)")
        # Only a coder reporting a finished fix owes the fix-mode fields: one
        # that stopped mid-fix (blocked / needs_context) has fixed nothing yet.
        if cycle >= 2 and data["status"] in DIAGNOSIS_STATUSES:
            _validate_fix(data)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
RESOLVABLE_KINDS = frozenset(_FIELD_DESCRIBERS)


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
            digest = _entry_digest(entry)
            item_id = f"{rec.stem}#{field_name}[{digest}]"
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

    ensure_store(store_dir)
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "resolution", "resolves": resolve_id, "note": note})


# Store-managed handoff files beyond the JSON records: briefs, reports,
# per-task decision docs, gate reports, and review packages. Gate
# reviewers read their own report path as their prior verdict, so these
# must not outlive the run that wrote them.
HANDOFF_FILE_PATTERNS = ("task-*-*.md", "design-review-*.md", "intent-recheck.md",
                         "intent-issue.md", "mutation-review.md", "review-*.diff")


def cmd_clear(store_dir: Path) -> None:
    """Delete files whose stem matches the record naming convention
    (task-*-* or final-*), the handoff files the run wrote
    (HANDOFF_FILE_PATTERNS), and the progress log — content validity is
    irrelevant: a malformed record-attempt is clearable, an unrelated
    notes.json is not."""
    if store_dir.is_dir():
        for path in sorted(store_dir.glob("*.json")):
            if fnmatch.fnmatch(path.stem, "task-*-*") or fnmatch.fnmatch(path.stem, "final-*"):
                path.unlink()
        for pattern in HANDOFF_FILE_PATTERNS:
            for path in sorted(store_dir.glob(pattern)):
                path.unlink()
    progress_path = store_dir / PROGRESS_FILENAME
    if progress_path.is_file():
        progress_path.unlink()


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
    """Write-time gate: strict parse + validation, then the same
    item-construction path `open` uses (spec Sec 6, amended 2026-08-27) —
    so a record that passes `check` cannot later render as malformed at
    query time. Silent on success."""
    path = _resolve_check_path(record_path, store)
    data = _parse_record_file(path)

    rec = Record(stem=path.stem, ok=True, data=data)
    try:
        _build_open_items(rec)
    except Exception as e:
        raise RecordError(
            f"{path}: passes validation but fails to render as an open item: {e}") from e


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
        elif args.command == "append":
            cmd_append(store_dir, args.type, args.task, args.note)
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
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
