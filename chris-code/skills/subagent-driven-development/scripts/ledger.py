#!/usr/bin/env python3
"""
ledger.py — typed record store for subagent-driven-development.

One store, one script. Agents write their own JSON record at a
dispatch-supplied path (task-<N>-<agent-name>.json, or
final-<agent-name>.json for the whole-change gate); this script derives
queryable views over those files on the fly — no fold/sync step, no drift.

Store: $(git rev-parse --git-path sdd)/ by default, or --store DIR.
progress.jsonl in that same dir is append-only, orchestrator-only.

Philosophy (spec Sec 4/7, amended 2026-08-27): failures are loud, not
defensively rendered away. `check` is the write-time gate — an agent runs
it on its own freshly written record and fixes until it exits 0. Loading
records for a query isolates each file: one malformed record becomes one
malformed entry, never hides its siblings. Required-ness is scoped to
decision-driving fields only; informational fields are unvalidated.
Totality ("never crash on any input") is explicitly not a goal.

Usage: python3 ledger.py read|open|shapes|clear [--store DIR]
       python3 ledger.py append --type progress --task N|final --note "..." [--store DIR]
       python3 ledger.py resolve <id> [--note "..."] [--store DIR]
       python3 ledger.py check <record-path>

Importable API (used by task_brief.py): see __all__ below — one list, not
two, so the two can't drift. Functions raise instead of calling sys.exit,
so callers own exit codes.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RecordError", "Record", "OpenItem", "Shape",
    "get_store_dir", "validate_record",
    "load_records", "load_progress_log", "resolved_ids_from_log",
    "compute_open_items", "list_shapes", "render_shapes", "render_store_markdown",
]

SCHEMA_VERSION = 1
ENVELOPE_FIELDS = ("schema", "agent", "role", "task")
VALID_ROLES = frozenset({"coder", "spec-reviewer", "quality-reviewer", "review-lite"})

STATUS_ENUMS = {
    "coder": {"done", "done_with_concerns", "needs_context", "blocked"},
    "spec-reviewer": {"compliant", "issues"},
    "quality-reviewer": {"approved", "issues"},
    "review-lite": {"clean", "block", "escalate"},
}
CODER_OPEN_STATUSES = {"blocked", "needs_context"}
REVIEWER_OPEN_STATUSES = {"issues", "block", "escalate"}

# Decision-driving list fields beyond `status`, by role: required present,
# must be a list, and each entry must be an object. Everything else
# (changed_files, tests, concerns, report, issues, findings, linter,
# cycle, ...) is informational and unvalidated (spec Sec 7 amendment).
DECISION_LIST_FIELDS = {
    "coder": ("duplication_pending", "new_shared_symbols"),
    "spec-reviewer": ("cannot_verify",),
}

# Whole-record items (status, malformed) are state, not work items: they
# clear only when the record is rewritten, never via `resolve` — otherwise
# a stale resolution could suppress a later, different problem at the same
# id (spec Sec 6 amended `open` semantics).
RESOLVABLE_KINDS = {"duplication_pending", "cannot_verify"}

PROGRESS_FILENAME = "progress.jsonl"


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
    """--store override, else `git rev-parse --git-path sdd`. Does not create it."""
    if override is not None:
        return Path(override).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-path", "sdd"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError("not inside a git repository; pass --store DIR") from e
    return Path(out).resolve()


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


def load_records(store_dir: Path) -> list[Record]:
    """One Record per *.json file. A missing store dir is an empty list,
    not an error — an empty store is a valid, empty history. store_dir is
    required (not defaulted) so a caller can't accidentally combine
    records from one store with resolutions or shapes from another."""
    if not store_dir.is_dir():
        return []
    return [_load_record(path) for path in sorted(store_dir.glob("*.json"))]


def _load_record(path: Path) -> Record:
    # Every failure mode is caught right here, so one bad file becomes one
    # malformed Record instead of crashing the caller's whole query
    # (per-record isolation — one bad file must never hide its siblings).
    stem = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_record(data)
    except Exception as e:
        return Record(stem, ok=False, error=str(e))
    return Record(stem, ok=True, data=data)


def load_progress_log(store_dir: Path) -> list[dict]:
    """Parse progress.jsonl; a malformed line is skipped with a warning.
    store_dir is required (not defaulted), same as load_records/list_shapes/
    compute_open_items, so it's always sourced from an explicit store."""
    path = store_dir / PROGRESS_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"WARNING: skipping unreadable {PROGRESS_FILENAME}: {e}", file=sys.stderr)
        return []
    entries = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"WARNING: skipping malformed {PROGRESS_FILENAME} line {lineno}: {e}",
                  file=sys.stderr)
            continue
        if not isinstance(parsed, dict):
            print(f"WARNING: skipping malformed {PROGRESS_FILENAME} line {lineno}: "
                  "not a JSON object", file=sys.stderr)
            continue
        entries.append(parsed)
    return entries


def resolved_ids_from_log(log: list[dict]) -> set[str]:
    return {entry["resolves"] for entry in log
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

    for idx, entry in enumerate(rec.data.get("duplication_pending", [])):
        items.append(OpenItem(
            id=f"{rec.stem}#duplication_pending[{idx}]", kind="duplication_pending",
            summary=_describe_duplication(entry), source=rec.stem))

    for idx, entry in enumerate(rec.data.get("cannot_verify", [])):
        items.append(OpenItem(
            id=f"{rec.stem}#cannot_verify[{idx}]", kind="cannot_verify",
            summary=_describe_cannot_verify(entry), source=rec.stem))

    return items


def _describe_duplication(entry: dict) -> str:
    sites = ", ".join(entry.get("sites", []))
    return (f"sites=[{sites}] wants_owner={entry.get('wants_owner', '')} "
            f"why={entry.get('why', '')}")


def _describe_cannot_verify(entry: dict) -> str:
    return (f"{entry.get('requirement', '')} — {entry.get('why', '')} "
            f"(should_check: {entry.get('should_check', '')})")


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
        elif entry.get("type") == "resolution":
            lines.append(f"- resolves `{entry.get('resolves')}`: {entry.get('note', '')}")
        else:
            lines.append(f"- unknown entry: {entry}")
    return "\n".join(lines)


def cmd_read(store_dir: Path) -> None:
    print(render_store_markdown(load_records(store_dir), load_progress_log(store_dir)))


def cmd_open(store_dir: Path) -> None:
    records = load_records(store_dir)
    resolved = resolved_ids_from_log(load_progress_log(store_dir))
    items = compute_open_items(records, resolved)
    if not items:
        print("No open items.")
        return
    for item in items:
        print(f"[{item.id}] {item.kind}: {item.summary}")


def cmd_shapes(store_dir: Path) -> None:
    print(render_shapes(list_shapes(load_records(store_dir))))


def cmd_append(store_dir: Path, task: int | str, note: str) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    _append_jsonl(store_dir / PROGRESS_FILENAME, {"type": "progress", "task": task, "note": note})


def cmd_resolve(store_dir: Path, resolve_id: str, note: str) -> None:
    """Record a resolution — but only for an id that is currently open and
    resolvable. A resolve that matches nothing is not a silent no-op: it
    raises RecordError distinguishing "already resolved" (the id has a
    prior resolution — the corrective message quotes that resolution's own
    note) from "never was open" (the id never matched a resolvable item;
    the message lists what's actually open right now)."""
    log = load_progress_log(store_dir)
    already_resolved = {}
    for entry in log:
        if entry.get("type") == "resolution" and isinstance(entry.get("resolves"), str):
            already_resolved[entry["resolves"]] = entry.get("note", "")
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

    store_dir.mkdir(parents=True, exist_ok=True)
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "resolution", "resolves": resolve_id, "note": note})


def cmd_clear(store_dir: Path) -> None:
    """Delete files whose stem matches the record naming convention
    (task-*-* or final-*) plus the progress log — content validity is
    irrelevant: a malformed record-attempt is clearable, an unrelated
    notes.json is not."""
    if store_dir.is_dir():
        for path in sorted(store_dir.glob("*.json")):
            if fnmatch.fnmatch(path.stem, "task-*-*") or fnmatch.fnmatch(path.stem, "final-*"):
                path.unlink()
    progress_path = store_dir / PROGRESS_FILENAME
    if progress_path.is_file():
        progress_path.unlink()


def cmd_check(record_path: str) -> None:
    """Write-time gate: strict parse + validation; silent on success."""
    path = Path(record_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RecordError(f"cannot read {record_path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RecordError(f"invalid JSON in {record_path}: {e}") from e
    validate_record(data)


def _task_arg(value: str) -> int | str:
    """A positive integer, or 'final' for the whole-change commit gate."""
    if value == "final":
        return value
    try:
        n = int(value)
    except ValueError:
        n = None
    if n is None or n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer or 'final'")
    return n


def build_parser() -> argparse.ArgumentParser:
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument(
        "--store", default=None,
        help="override the store directory (default: git rev-parse --git-path sdd)")

    parser = argparse.ArgumentParser(
        description="Typed record store for subagent-driven-development.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("read", parents=[store_parent], help="render the full store as markdown")
    sub.add_parser("open", parents=[store_parent], help="list unresolved open items")
    sub.add_parser("shapes", parents=[store_parent], help="list shared symbols recorded so far")

    p_append = sub.add_parser("append", parents=[store_parent], help="append a progress note")
    p_append.add_argument("--type", required=True, choices=["progress"])
    p_append.add_argument("--task", required=True, type=_task_arg,
                           help="positive task number, or 'final' for the whole-change gate")
    p_append.add_argument("--note", required=True)

    p_resolve = sub.add_parser("resolve", parents=[store_parent],
                                help="record a resolution for an open item")
    p_resolve.add_argument("id")
    p_resolve.add_argument("--note", default="")

    sub.add_parser("clear", parents=[store_parent],
                    help="remove records matching the naming convention "
                         "(task-*-*/final-*) and the progress log")

    p_check = sub.add_parser("check", parents=[store_parent],
                              help="validate a single record file (write-time gate)")
    p_check.add_argument("record_path", help="path to the record JSON file to validate")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "check":
            cmd_check(args.record_path)
            return
        store_dir = get_store_dir(args.store)
        if args.command == "read":
            cmd_read(store_dir)
        elif args.command == "open":
            cmd_open(store_dir)
        elif args.command == "shapes":
            cmd_shapes(store_dir)
        elif args.command == "append":
            cmd_append(store_dir, args.task, args.note)
        elif args.command == "resolve":
            cmd_resolve(store_dir, args.id, args.note)
        elif args.command == "clear":
            cmd_clear(store_dir)
    except (RuntimeError, RecordError) as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
