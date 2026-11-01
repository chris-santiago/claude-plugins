#!/usr/bin/env python3
"""
journal_setup.py — Initialize a repo's journal, or upgrade it from the legacy layout.

The legacy layout copied journal_log.py / journal_query.py into .project-log/
and pointed CLAUDE.md at them. Now the plugin's scripts are the only journal
code that runs; a repo holds data only (.project-log/journal.jsonl).

Usage (S = python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_setup.py"):
    S [--data-dir D] inspect     # JSON report: journal, trusted, legacy copies, CLAUDE.md sections
    S [--data-dir D] init        # create .project-log/journal.jsonl if absent (never truncates);
                                 # a journal it creates is also trusted for session-start checkpoints
    S --data-dir D trust         # trust this repo's existing journal on this machine
    S upgrade [--dry-run]        # delete legacy copies, rewrite managed sections that call them
    S add-sections [--dry-run]   # append managed CLAUDE.md sections that are absent

Managed CLAUDE.md sections are the level-2 headings in assets/claude-md-sections.md.
`upgrade` rewrites only managed sections that call a legacy script; a managed
section that merely differs from the template is a user customization and is
left alone. Line endings (LF or CRLF) are preserved.

D is the plugin data dir (skills pass "${CLAUDE_PLUGIN_DATA}"). Trust is recorded
there, outside the repo; without it, checkpoints are not loaded automatically.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys

# `python3 -I` drops the script directory from sys.path; add it back so the
# plugin's own sibling module resolves. Nothing from the repo is imported.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from journal_common import (  # noqa: E402
    JOURNAL_NAME, LOG_DIR_NAME, is_trusted, journal_path, legacy_copies, log_dir, repo_root, trust_repo,
)

LEGACY_REF = re.compile(r"\.project-log/journal_\w+\.py")
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "claude-md-sections.md")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^#{1,2} ")


# --- Markdown sections ----------------------------------------------------------


def _heading_lines(lines):
    """Yield (index, heading text) for level-1/2 ATX headings outside code fences.

    A fence closes only on the same marker character with at least the opening
    length, so a ``` line inside a ~~~ block does not end it.
    """
    fence = None  # (marker char, length) of the open fence
    for i, line in enumerate(lines):
        match = FENCE.match(line)
        if match:
            run = match.group(1)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and line.strip() == run:
                fence = None
            continue
        if fence is None and HEADING.match(line):
            yield i, line.rstrip()


def section_spans(lines, wanted):
    """Map each wanted heading to the (start, end) spans of all its occurrences.

    A section runs from its heading to the next level-1/2 heading or EOF.
    """
    headings = list(_heading_lines(lines))
    spans = {}
    for pos, (start, text) in enumerate(headings):
        if text in wanted:
            end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
            spans.setdefault(text, []).append((start, end))
    return spans


def _normalize(text):
    return text.replace("\r\n", "\n").rstrip() + "\n"


def template_sections():
    """Return {heading: section text} from the template, in template order."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    headings = [text for _, text in _heading_lines(lines)]
    spans = section_spans(lines, set(headings))
    return {h: _normalize("".join(lines[slice(*spans[h][0])])) for h in headings}


# --- Repo state -----------------------------------------------------------------


def claude_md_location(root):
    """Return (path, symlinked) for the repo's CLAUDE.md.

    A symlinked CLAUDE.md is never read or written, wherever it points: a hostile
    repo could aim it at a shell rc, .git/config (under any case spelling), or the
    journal itself. Same rule as the journal's own symlink refusal.
    """
    path = os.path.join(root, "CLAUDE.md")
    return path, os.path.islink(path)


def read_lines(path):
    """Read with line endings preserved (newline=""), so CRLF files round-trip."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().splitlines(keepends=True)


def write_lines(path, lines):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))


def _newline(lines):
    return "\r\n" if lines and lines[0].endswith("\r\n") else "\n"


def _with_newline(text, nl):
    return text.replace("\n", nl) if nl != "\n" else text


def inspect_repo(root, data_dir=None):
    template = template_sections()
    journal = journal_path(root)
    legacy = legacy_copies(root)

    path, symlinked = claude_md_location(root)
    md = {
        "exists": os.path.lexists(path),
        "symlinked": symlinked,
        "stale_sections": [],
        "customized_sections": [],
        "current_sections": [],
        "absent_sections": [],
        "unmanaged_refs": [],
    }
    if md["exists"] and not symlinked:
        lines = read_lines(path)
        spans = section_spans(lines, set(template))
        for heading in template:
            texts = ["".join(lines[start:end]) for start, end in spans.get(heading, [])]
            if not texts:
                key = "absent_sections"
            elif any(LEGACY_REF.search(t) for t in texts):
                key = "stale_sections"
            elif all(_normalize(t) == template[heading] for t in texts):
                key = "current_sections"
            else:
                key = "customized_sections"
            md[key].append(heading)
        md["unmanaged_refs"] = unmanaged_refs(lines, template)
    elif not md["exists"]:
        md["absent_sections"] = list(template)

    return {
        "repo_root": root,
        "journal_exists": os.path.isfile(journal),
        "trusted": is_trusted(root, data_dir),
        "legacy_copies": legacy,
        "claude_md": md,
        "needs_upgrade": bool(legacy or md["stale_sections"]),
    }


def unmanaged_refs(lines, template):
    """Lines outside managed sections that call a legacy script (1-based line numbers)."""
    spans = section_spans(lines, set(template))
    managed = {i for occurrences in spans.values() for start, end in occurrences for i in range(start, end)}
    return [
        {"line": i + 1, "text": line.rstrip()}
        for i, line in enumerate(lines)
        if i not in managed and LEGACY_REF.search(line)
    ]


def upgraded_lines(lines, template):
    """Return lines with every managed section that calls a legacy script replaced."""
    nl = _newline(lines)
    new = list(lines)
    spans = section_spans(new, set(template))
    occurrences = sorted(((s, e, h) for h, occ in spans.items() for s, e in occ), reverse=True)
    for start, end, heading in occurrences:
        if not LEGACY_REF.search("".join(new[start:end])):
            continue
        replacement = template[heading] + ("\n" if end < len(new) else "")
        new[start:end] = _with_newline(replacement, nl).splitlines(keepends=True)
    return new


# --- Commands -------------------------------------------------------------------


def journal_in_history(root):
    """True if any ref has ever tracked the journal, or if that can't be determined.

    Such a journal can arrive with a checkout, so creating an empty one here is
    not grounds for trusting the repo automatically.
    """
    result = subprocess.run(
        ["git", "rev-list", "--all", "-1", "--", f"{LOG_DIR_NAME}/{JOURNAL_NAME}"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    return result.returncode != 0 or bool(result.stdout.strip())


def cmd_inspect(root, args):
    print(json.dumps(inspect_repo(root, args.data_dir), indent=2, ensure_ascii=False))


def cmd_init(root, args):
    journal = journal_path(root)
    os.makedirs(log_dir(root), exist_ok=True)
    existed = os.path.exists(journal)
    # O_NOFOLLOW backs up the symlink refusal in journal_path(); no O_TRUNC, ever.
    os.close(os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644))
    print(f"{'exists' if existed else 'created'} {os.path.relpath(journal, root)}")
    if existed:
        return  # an existing journal may be someone else's; trusting it is an explicit act
    if journal_in_history(root):
        print("not trusted: this repo's git history already has a journal, so trusting it is a separate step")
    elif args.data_dir:
        trust_repo(root, args.data_dir)
        print("trusted: this repo's journal is trusted on this machine; checkpoints load at session start")
    else:
        print("not trusted: no plugin data directory, so checkpoints will not auto-load at session start")


def cmd_trust(root, args):
    if not os.path.isfile(journal_path(root)):
        sys.exit("ERROR: No journal in this repo; run /log-init first.")
    if trust_repo(root, args.data_dir):
        print("trusted: this repo's journal is trusted on this machine; checkpoints load at session start")
    else:
        print("already trusted: this repo's journal was already trusted on this machine")


def cmd_upgrade(root, args):
    report = inspect_repo(root)
    md = report["claude_md"]
    if not report["needs_upgrade"] and not md["unmanaged_refs"] and not md["symlinked"]:
        print("Already current: nothing to upgrade.")
        return
    verb = "would " if args.dry_run else ""

    for name in report["legacy_copies"]:
        print(f"{verb}delete {os.path.join('.project-log', name)}")
        if not args.dry_run:
            os.remove(os.path.join(log_dir(root), name))

    refs = md["unmanaged_refs"]
    if md["symlinked"]:
        print("skip CLAUDE.md: it is a symlink, so it is never read or edited; check its target by hand for .project-log/ script calls")
    elif md["stale_sections"]:
        path, _ = claude_md_location(root)
        lines = read_lines(path)
        template = template_sections()
        new = upgraded_lines(lines, template)
        for heading in md["stale_sections"]:
            print(f'{verb}replace CLAUDE.md section "{heading}"')
        # Diff lines carry the file's own endings; normalize, and end a final
        # line that had no newline so it doesn't run into the next diff line.
        for line in difflib.unified_diff(lines, new, "CLAUDE.md", "CLAUDE.md (upgraded)"):
            print(line.rstrip("\r\n"))
        if not args.dry_run:
            write_lines(path, new)
            refs = unmanaged_refs(new, template)  # line numbers in the file the user will edit

    for ref in refs:
        print(f"report CLAUDE.md line {ref['line']} runs a legacy script; edit by hand: {ref['text'].strip()}")

    if not report["needs_upgrade"]:
        print("Nothing to change.")
    elif args.dry_run:
        print("Dry run: no changes made.")


def cmd_add_sections(root, args):
    report = inspect_repo(root)
    md = report["claude_md"]
    if md["symlinked"]:
        print("skip CLAUDE.md: it is a symlink, so it is never edited.")
        return
    if not md["exists"]:
        print("No CLAUDE.md: nothing to add.")
        return
    if not md["absent_sections"]:
        print("All journal sections already present.")
        return
    verb = "would " if args.dry_run else ""
    for heading in md["absent_sections"]:
        print(f'{verb}add CLAUDE.md section "{heading}"')
    if args.dry_run:
        print("Dry run: no changes made.")
        return
    path, _ = claude_md_location(root)
    lines = read_lines(path)
    nl = _newline(lines)
    template = template_sections()
    text = "".join(lines).rstrip("\r\n")
    addition = _with_newline("\n".join(template[h] for h in md["absent_sections"]), nl)
    write_lines(path, [f"{text}{nl}{nl}{addition}" if text else addition])


COMMANDS = {"inspect": cmd_inspect, "init": cmd_init, "trust": cmd_trust, "upgrade": cmd_upgrade, "add-sections": cmd_add_sections}


def main():
    parser = argparse.ArgumentParser(description="Initialize or upgrade the project journal layout.")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--dry-run", action="store_true", help="Show what would change; change nothing")
    parser.add_argument("--data-dir", default=None, help="Plugin data dir holding the trust list")
    args = parser.parse_args()
    COMMANDS[args.command](repo_root(), args)


if __name__ == "__main__":
    main()
