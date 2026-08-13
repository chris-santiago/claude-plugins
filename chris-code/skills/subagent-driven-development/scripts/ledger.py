#!/usr/bin/env python3
"""
ledger.py — typed record store for subagent-driven-development.

Replaces scripts/progress outright: one store, one script. Per-task-loop
agents write their own JSON record at a dispatch-supplied path (naming
convention: task-<N>-<agent-name>.json, or final-<agent-name>.json for the
whole-change gate); this script derives queryable views over those files on
the fly. There is no fold/sync step, so there is no drift between records
and ledger.

Store: $(git rev-parse --git-path sdd)/ — per-worktree, uncommitted,
disposable. progress.jsonl in that same directory is append-only and
written only by this script (orchestrator-only; agents never touch it).

Usage:
    python3 ledger.py read
    python3 ledger.py open
    python3 ledger.py shapes
    python3 ledger.py append --type progress --task N|final --note "..."
    python3 ledger.py resolve <id> [--note "..."]
    python3 ledger.py clear

Importable API (used by task_brief.py):
    get_store_dir() -> Path
    load_records(store_dir=None) -> list[Record]
    load_progress_log(store_dir=None) -> list[dict]
    resolved_ids_from_log(log) -> set[str]
    compute_open_items(records=None, resolved_ids=None) -> list[OpenItem]
    list_shapes(records=None) -> list[Shape]
    render_shapes(shapes) -> str
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# Fields required on every record's envelope, regardless of role.
# "status" is required too, but its allowed values are role-specific, so it
# is listed per-role in ROLE_PAYLOAD_FIELDS below rather than here.
ENVELOPE_FIELDS = ("schema", "agent", "role", "task")

# Every payload field a role's record must contain (status included). An
# absent field is a contract violation; an explicit empty value is an
# answer — see spec §6.
ROLE_PAYLOAD_FIELDS = {
    "coder": (
        "status", "changed_files", "tests", "new_shared_symbols",
        "duplication_pending", "concerns", "report",
    ),
    "spec-reviewer": ("status", "issues", "cannot_verify"),
    "quality-reviewer": ("status", "findings", "lossiness"),
    "review-lite": ("status", "cycle", "findings", "linter", "verdict_path"),
}

# Expected type per payload field, by role. Fields not listed here are
# scalars (report, verdict_path, symbol/why strings, ...) whose exact type
# isn't load-time checked — only shapes a container mismatch can crash
# downstream (a scalar where a list/object belongs, e.g. enumerate() over a
# string yielding one garbage item per character instead of raising) or
# silently hide an item (a non-string status skipping the open-item check
# that's keyed on set membership) are validated here.
FIELD_TYPES = {
    "coder": {
        "status": str,
        "changed_files": list,
        "tests": dict,
        "new_shared_symbols": list,
        "duplication_pending": list,
        "concerns": list,
    },
    "spec-reviewer": {
        "status": str,
        "issues": list,
        "cannot_verify": list,
    },
    "quality-reviewer": {
        "status": str,
        "findings": list,
        "lossiness": list,
    },
    "review-lite": {
        "status": str,
        "cycle": int,
        "findings": list,
        "linter": dict,
    },
}

# Closed status enum per role (spec §6). Validated at load time so an
# out-of-enum status (e.g. a typo'd "Blocked") becomes a visible #malformed
# record instead of silently failing the open-item status check below and
# hiding what may be a blocked/failing record — the exact silent failure
# this design forbids (spec §4, §8).
STATUS_ENUMS = {
    "coder": {"done", "done_with_concerns", "needs_context", "blocked"},
    "spec-reviewer": {"compliant", "issues"},
    "quality-reviewer": {"approved", "issues"},
    "review-lite": {"clean", "block", "escalate"},
}

CODER_OPEN_STATUSES = {"blocked", "needs_context"}
REVIEWER_OPEN_STATUSES = {"issues", "block", "escalate"}

PROGRESS_FILENAME = "progress.jsonl"


# --- Data model ---

@dataclass
class Record:
    """One parsed (task, agent) record file."""

    path: Path
    stem: str
    ok: bool
    error: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class OpenItem:
    """One unresolved item surfaced by `open`."""

    id: str
    kind: str  # duplication_pending | cannot_verify | status | malformed
    summary: str
    source: str  # record stem it came from


@dataclass
class Shape:
    """One shared-symbol entry surfaced by `shapes`."""

    symbol: str
    path: str
    why: str
    source: str  # record stem it came from


# --- Store resolution ---

def get_store_dir() -> Path:
    """Resolve the per-worktree sdd store directory via git.

    Does not create the directory — callers that write must mkdir first.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-path", "sdd"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("ERROR: not inside a git repository.")
    return Path(out).resolve()


# --- Record loading and validation ---

def load_records(store_dir: Path | None = None) -> list[Record]:
    """Load and validate every JSON record file in the store.

    Returns one Record per *.json file (progress.jsonl is not a record — it
    has a different extension and is read separately). A missing store
    directory yields an empty list, not an error: an empty store is a valid,
    empty history.
    """
    if store_dir is None:
        store_dir = get_store_dir()
    if not store_dir.is_dir():
        return []
    return [_load_record(path) for path in sorted(store_dir.glob("*.json"))]


def _load_record(path: Path) -> Record:
    """Parse and validate one record file per spec §6 / §4's malformed list:
    unparseable JSON, missing required field, unknown schema/role, a
    required field holding the wrong type, or a status outside the role's
    closed enum."""
    stem = path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        # UnicodeDecodeError is a ValueError, not an OSError — a file with
        # invalid UTF-8 bytes must surface as malformed, not crash the
        # query, same as unparseable JSON.
        return Record(path, stem, ok=False, error=f"unreadable: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return Record(path, stem, ok=False, error=f"invalid JSON: {e}")

    if not isinstance(data, dict):
        return Record(path, stem, ok=False, error="record is not a JSON object")

    missing = [f for f in ENVELOPE_FIELDS if f not in data]
    if missing:
        return Record(path, stem, ok=False, data=data,
                       error=f"missing required field(s): {', '.join(missing)}")

    if data["schema"] != SCHEMA_VERSION:
        return Record(path, stem, ok=False, data=data,
                       error=f"unknown schema: {data['schema']!r}")

    role = data["role"]
    # role is used as a dict key below; an unhashable role (e.g. a list or
    # object smuggled into that field) must not crash the lookup itself.
    payload_fields = ROLE_PAYLOAD_FIELDS.get(role) if isinstance(role, str) else None
    if payload_fields is None:
        return Record(path, stem, ok=False, data=data,
                       error=f"unknown role: {role!r}")

    missing = [f for f in payload_fields if f not in data]
    if missing:
        return Record(path, stem, ok=False, data=data,
                       error=f"missing required field(s): {', '.join(missing)}")

    bad_types = [f for f, expected in FIELD_TYPES.get(role, {}).items()
                 if not _matches_type(data.get(f), expected)]
    if bad_types:
        return Record(path, stem, ok=False, data=data,
                       error=f"field(s) with wrong type: {', '.join(bad_types)}")

    # status is confirmed str by the FIELD_TYPES check above, so this
    # membership test is safe regardless of what the record contains.
    allowed_statuses = STATUS_ENUMS[role]
    if data["status"] not in allowed_statuses:
        return Record(path, stem, ok=False, data=data,
                       error=f"status {data['status']!r} not in allowed set for "
                             f"role {role!r}: {sorted(allowed_statuses)}")

    return Record(path, stem, ok=True, data=data)


def _matches_type(value, expected: type) -> bool:
    if expected is int:
        # bool is an int subclass in Python; a cycle count of `true` should
        # not pass an int check.
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


# --- progress.jsonl (orchestrator-only) ---

def load_progress_log(store_dir: Path | None = None) -> list[dict]:
    """Parse progress.jsonl into a list of entry dicts.

    A malformed line is skipped with a warning rather than crashing the
    query, matching the fail-loud-but-never-crash stance records get.
    """
    if store_dir is None:
        store_dir = get_store_dir()
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
    # isinstance(..., str), not just "resolves" in entry: a resolves value
    # that isn't a string (e.g. a hand-edited list) would otherwise crash
    # this set comprehension with "unhashable type".
    return {entry["resolves"] for entry in log
            if entry.get("type") == "resolution" and isinstance(entry.get("resolves"), str)}


def _append_jsonl(path: Path, entry: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")


# --- open-item computation ---

def compute_open_items(
    records: list[Record] | None = None,
    resolved_ids: set[str] | None = None,
) -> list[OpenItem]:
    """Every unresolved item across records, per spec §6's closed list:
    a duplication_pending entry, a cannot_verify entry, a coder record with
    status blocked/needs_context, a reviewer/review-lite record with status
    issues/block/escalate, or a malformed record."""
    if records is None:
        records = load_records()
    if resolved_ids is None:
        resolved_ids = resolved_ids_from_log(load_progress_log())

    items = []
    for rec in records:
        items.extend(_open_items_for_record(rec))
    return [item for item in items if item.id not in resolved_ids]


def _open_items_for_record(rec: Record) -> list[OpenItem]:
    if not rec.ok:
        return [OpenItem(id=f"{rec.stem}#malformed", kind="malformed",
                          summary=rec.error, source=rec.stem)]

    role = rec.data["role"]
    status = rec.data.get("status")
    items: list[OpenItem] = []

    # isinstance guard: status is not container-type-checked at load time
    # (it's a scalar contract field, see FIELD_TYPES), so a non-string
    # status (e.g. a list) must not crash this set-membership test with
    # "unhashable type".
    if isinstance(status, str):
        if role == "coder" and status in CODER_OPEN_STATUSES:
            items.append(OpenItem(id=f"{rec.stem}#status", kind="status",
                                   summary=f"coder status: {status}", source=rec.stem))
        elif role != "coder" and status in REVIEWER_OPEN_STATUSES:
            items.append(OpenItem(id=f"{rec.stem}#status", kind="status",
                                   summary=f"{role} status: {status}", source=rec.stem))

    # _as_list, not `or []`: these two fields are only container-type-
    # checked for the roles that require them (coder / spec-reviewer). A
    # stray non-list value on a role that doesn't validate the field would
    # otherwise reach enumerate() unguarded — a truthy scalar bypasses
    # `or []`, and a bare string degrades to one entry per character.
    for idx, entry in enumerate(_as_list(rec.data.get("duplication_pending"))):
        items.append(OpenItem(
            id=f"{rec.stem}#duplication_pending[{idx}]", kind="duplication_pending",
            summary=_describe_duplication(entry), source=rec.stem,
        ))

    for idx, entry in enumerate(_as_list(rec.data.get("cannot_verify"))):
        items.append(OpenItem(
            id=f"{rec.stem}#cannot_verify[{idx}]", kind="cannot_verify",
            summary=_describe_cannot_verify(entry), source=rec.stem,
        ))

    return items


def _as_list(value) -> list:
    """Coerce a JSON value that is expected to be a list into an actual
    list for safe iteration. Anything else — a stray string, number, or a
    dict smuggled into a list-shaped field — is treated as "no entries"
    rather than iterated, since iterating a bare string yields one entry
    per character instead of raising."""
    return value if isinstance(value, list) else []


def _safe_str(value) -> str:
    """Render a single JSON value of any shape as inline text without
    raising. Strings pass through unchanged; anything else (numbers,
    bools, None, or a nested list/dict smuggled into a scalar field) is
    rendered via json.dumps so structure stays visible instead of being
    iterated or stringified as a Python repr."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _safe_join(value, sep: str = ", ") -> str:
    """Join a JSON value that is expected to be a list of strings, without
    assuming it actually is one: a non-list is rendered as a single unit
    via _safe_str (never iterated — a bare string would otherwise degrade
    to per-character output under str.join), and non-string list elements
    are coerced individually rather than raising in str.join."""
    if isinstance(value, list):
        return sep.join(_safe_str(v) for v in value)
    return _safe_str(value)


def _describe_duplication(entry) -> str:
    if not isinstance(entry, dict):
        return _safe_str(entry)
    sites = _safe_join(entry.get("sites"))
    return (f"sites=[{sites}] wants_owner={_safe_str(entry.get('wants_owner', ''))} "
            f"why={_safe_str(entry.get('why', ''))}")


def _describe_cannot_verify(entry) -> str:
    if not isinstance(entry, dict):
        return _safe_str(entry)
    return f"{_safe_str(entry.get('requirement', ''))} — {_safe_str(entry.get('why', ''))}"


# --- shared shapes ---

def list_shapes(records: list[Record] | None = None) -> list[Shape]:
    """Every new_shared_symbols entry across well-formed coder records."""
    if records is None:
        records = load_records()
    shapes = []
    for rec in records:
        if not rec.ok or rec.data.get("role") != "coder":
            continue
        for entry in _as_list(rec.data.get("new_shared_symbols")):
            if not isinstance(entry, dict):
                continue
            shapes.append(Shape(
                symbol=_safe_str(entry.get("symbol", "")),
                path=_safe_str(entry.get("path", "")),
                why=_safe_str(entry.get("why", "")),
                source=rec.stem,
            ))
    return shapes


def render_shapes(shapes: list[Shape]) -> str:
    """Render shared-symbol entries as a markdown bullet list.

    Empty input renders as a placeholder line so the brief's shared-shapes
    section is always present, never blank — spec §6: no flag disables it.
    """
    if not shapes:
        return "(none recorded yet)"
    lines = []
    for s in shapes:
        why = f" — {s.why}" if s.why else ""
        lines.append(f"- `{s.symbol}` ({s.path}){why}  [{s.source}]")
    return "\n".join(lines)


# --- full-store markdown rendering ---

def render_store_markdown(records: list[Record], log: list[dict]) -> str:
    lines = ["# SDD Ledger", "", "## Records"]

    if not records:
        lines.append("")
        lines.append("(none)")
    for rec in records:
        lines.append("")
        if not rec.ok:
            lines.append(f"### {rec.stem} — MALFORMED")
            lines.append(f"- error: {rec.error}")
            continue
        data = rec.data
        lines.append(f"### {rec.stem}  (role: {data['role']}, task: {data['task']}, "
                      f"status: {data['status']})")
        for key in ROLE_PAYLOAD_FIELDS[data["role"]]:
            if key == "status":
                continue
            lines.append(f"- {key}: {_render_value(data.get(key))}")

    lines.append("")
    lines.append("## Progress log")
    if not log:
        lines.append("")
        lines.append("(none)")
    for entry in log:
        lines.append("")
        if entry.get("type") == "progress":
            lines.append(f"- task {entry.get('task')}: {entry.get('note', '')}")
        elif entry.get("type") == "resolution":
            lines.append(f"- resolves `{entry.get('resolves')}`: {entry.get('note', '')}")
        else:
            lines.append(f"- unknown entry: {entry}")

    return "\n".join(lines)


def _render_value(value) -> str:
    if value in (None, "", [], {}):
        return "(empty)"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# --- CLI commands ---

def cmd_read(store_dir: Path) -> None:
    records = load_records(store_dir)
    log = load_progress_log(store_dir)
    print(render_store_markdown(records, log))


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
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "progress", "task": task, "note": note})


def cmd_resolve(store_dir: Path, resolve_id: str, note: str) -> None:
    store_dir.mkdir(parents=True, exist_ok=True)
    _append_jsonl(store_dir / PROGRESS_FILENAME,
                  {"type": "resolution", "resolves": resolve_id, "note": note})


def cmd_clear(store_dir: Path) -> None:
    """Remove every record file and the progress log.

    Reuses load_records' file discovery so `clear` deletes exactly the set
    of files `read`/`open`/`shapes` would have read — including malformed
    ones — rather than a second, independently-maintained glob. Scoped to
    what ledger.py owns: other files that may live in the same directory
    (e.g. task_brief.py's brief output) are left untouched.
    """
    for rec in load_records(store_dir):
        rec.path.unlink()
    progress_path = store_dir / PROGRESS_FILENAME
    if progress_path.is_file():
        progress_path.unlink()


# --- argument parsing ---

def _task_arg(value: str) -> int | str:
    """--task accepts a positive integer, or the literal 'final' used by the
    whole-change commit gate, whose final-<agent-name>.json records carry no
    task number (spec §6)."""
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
    parser = argparse.ArgumentParser(
        description="Typed record store for subagent-driven-development.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("read", help="render the full store as markdown")
    sub.add_parser("open", help="list unresolved open items")
    sub.add_parser("shapes", help="list shared symbols recorded so far")

    p_append = sub.add_parser("append", help="append a progress note")
    p_append.add_argument("--type", required=True, choices=["progress"])
    p_append.add_argument("--task", required=True, type=_task_arg,
                           help="positive task number, or 'final' for the whole-change gate")
    p_append.add_argument("--note", required=True)

    p_resolve = sub.add_parser("resolve", help="record a resolution for an open item")
    p_resolve.add_argument("id")
    p_resolve.add_argument("--note", default="")

    sub.add_parser("clear", help="remove all records and the progress log")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    store_dir = get_store_dir()

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


if __name__ == "__main__":
    main()
