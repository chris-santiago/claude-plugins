#!/usr/bin/env python3
"""
journal_log.py — Append a typed entry to .project-log/journal.jsonl

This plugin copy is the only journal code that runs; repos hold data only.
Run from anywhere inside the repo (the journal is found via the git root):

Usage:
    python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_log.py" --type issue --description "..." --severity high
    python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_log.py" --type decision --description "..." --rationale "..."
    ... (see REQUIRED_FIELDS for all types)
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# `python3 -I` (3.11+) drops the script directory from sys.path; add it back so
# the plugin's own sibling module resolves. Nothing from the repo is imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journal_common import journal_path, repo_root, warn_if_legacy  # noqa: E402


# --- Schema ---

REQUIRED_FIELDS = {
    "issue":       ["description", "severity"],
    "resolution":  ["description"],
    "decision":    ["description", "rationale"],
    "discovery":   ["description"],
    "hypothesis":  ["description"],
    "experiment":  ["description", "verdict"],
    "post_mortem": ["description", "what_failed", "root_cause", "linked_issue_id"],
    "lesson":      ["description"],
    "memo":        ["description"],
    "summary":     ["description"],
    "checkpoint":  ["in_progress"],
    "git":         ["message", "branch"],
}

OPTIONAL_FIELDS = {
    "issue":       ["tags", "context"],
    "resolution":  ["linked_issue_id", "approach", "evidence"],
    "decision":    ["alternatives", "implications", "linked_issue_id", "linked_id"],
    "discovery":   ["implications", "source", "linked_issue_id"],
    "hypothesis":  ["expected_result", "metric", "linked_issue_id"],
    "experiment":  ["linked_hypothesis_id", "linked_issue_id", "metric", "result"],
    "post_mortem": ["contributing_factors", "lessons", "severity", "scope", "remediation", "detail"],
    "lesson":      ["context", "applies_to", "linked_id"],
    "memo":        ["tags", "context", "detail", "linked_issue_id", "linked_id"],
    "summary":     ["key_decisions", "open_threads"],
    "checkpoint":  ["pending_decisions", "recently_completed", "key_context", "git_state", "open_threads"],
    "git":         ["commit_hash", "files_changed", "diff_summary"],
}

VALID_SEVERITIES = {"low", "minor", "moderate", "high", "critical"}
VALID_VERDICTS   = {"confirmed", "refuted", "inconclusive"}
VALID_SCOPES     = {"active", "future"}

LIST_FIELDS = {"tags", "files_changed", "key_decisions", "open_threads"}


def build_entry(args, project):
    entry_type = args.type

    if entry_type not in REQUIRED_FIELDS:
        sys.exit(f"ERROR: Unknown type '{entry_type}'. Valid types: {', '.join(sorted(REQUIRED_FIELDS))}")

    # Envelope
    entry = {
        "id":         str(uuid.uuid4()),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "type":       entry_type,
        "project":    project,
        "session_id": os.environ.get("CLAUDE_SESSION_ID") or str(os.getppid()),
    }

    # Collect all known fields for this type
    all_fields = REQUIRED_FIELDS[entry_type] + OPTIONAL_FIELDS.get(entry_type, [])

    # Reject fields passed that are not valid for this type
    all_possible = set()
    for fields in list(REQUIRED_FIELDS.values()) + list(OPTIONAL_FIELDS.values()):
        all_possible.update(fields)
    invalid = [
        f for f in all_possible
        if f not in all_fields and getattr(args, f, None) is not None
    ]
    if invalid:
        sys.exit(
            f"ERROR: Field(s) not valid for type '{entry_type}': {', '.join(sorted(invalid))}. "
            f"Valid fields: {', '.join(sorted(all_fields))}"
        )

    for field in all_fields:
        raw = getattr(args, field.replace("-", "_"), None)
        if raw is None:
            continue
        if field in LIST_FIELDS:
            # Accept comma-separated string or already a list
            if isinstance(raw, str):
                entry[field] = [v.strip() for v in raw.split(",") if v.strip()]
            else:
                entry[field] = raw
        else:
            entry[field] = raw

    # Validate required fields
    missing = [f for f in REQUIRED_FIELDS[entry_type] if f not in entry]
    if missing:
        sys.exit(f"ERROR: Missing required fields for type '{entry_type}': {', '.join(missing)}")

    # Validate enums
    if "severity" in entry and entry["severity"] not in VALID_SEVERITIES:
        sys.exit(f"ERROR: Invalid severity '{entry['severity']}'. Must be one of: {', '.join(sorted(VALID_SEVERITIES))}")
    if "verdict" in entry and entry["verdict"] not in VALID_VERDICTS:
        sys.exit(f"ERROR: Invalid verdict '{entry['verdict']}'. Must be one of: {', '.join(sorted(VALID_VERDICTS))}")
    if "scope" in entry and entry["scope"] not in VALID_SCOPES:
        sys.exit(f"ERROR: Invalid scope '{entry['scope']}'. Must be one of: {', '.join(sorted(VALID_SCOPES))}")

    return entry


def append_entry(journal_path, entry):
    os.makedirs(os.path.dirname(journal_path), exist_ok=True)
    # O_NOFOLLOW backs up the symlink check in journal_common.journal_path().
    fd = os.open(journal_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Append a typed entry to the project journal.")
    parser.add_argument("--type", required=True, help="Entry type")

    # All possible fields across all types
    all_possible = set()
    for fields in list(REQUIRED_FIELDS.values()) + list(OPTIONAL_FIELDS.values()):
        all_possible.update(fields)

    for field in sorted(all_possible):
        # Register with hyphen flag (--in-progress) and underscore dest (in_progress)
        flag = field.replace("_", "-")
        parser.add_argument(f"--{flag}", dest=field, default=None)

    args = parser.parse_args()

    root = repo_root()
    warn_if_legacy(root)
    path = journal_path(root)
    entry = build_entry(args, project=os.path.basename(root))
    append_entry(path, entry)

    print(f"Logged [{entry['type']}] {entry['id'][:8]} at {entry['timestamp'][:19]}Z")


if __name__ == "__main__":
    main()
