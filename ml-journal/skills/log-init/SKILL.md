---
name: log-init
description: Initialize the project journal in the current git repo, or upgrade a repo set up with an older ml-journal (scripts copied into .project-log/). Creates .project-log/journal.jsonl only; all journal code runs from the plugin. Use when the user says /log-init, "set up journal", "initialize journal", "set up project logging", or "upgrade the journal".
---

All journal code runs from the plugin; a repo holds data only (`.project-log/journal.jsonl`). In the steps below, `SETUP` means:

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_setup.py"
```

## Step 1: Inspect

Run `SETUP inspect`. If it fails because this is not a git repo, tell the user and stop.

The JSON report gives `journal_exists`, `legacy_copies`, `needs_upgrade`, and `claude_md` (`exists`, `symlinked`, `stale_sections`, `customized_sections`, `current_sections`, `absent_sections`, `unmanaged_refs`).

## Step 2: Upgrade a legacy repo

If `needs_upgrade` is true: run `SETUP upgrade --dry-run` and show its output, including the diff. Explain in one line: older ml-journal copied its scripts into `.project-log/`; they are no longer used, and the journal data is not touched. Ask: `► Apply this upgrade? (y/n)`. On yes, run `SETUP upgrade` and show its output.

If `needs_upgrade` is false but `claude_md.unmanaged_refs` is not empty, there is nothing to apply; just list those lines.

Either way, `report` lines and `unmanaged_refs` are `CLAUDE.md` lines the upgrade does not edit. Tell the user to fix them by hand: they should call a journal skill (e.g. `/log-list`) instead of a script. If `claude_md.symlinked` is true, `CLAUDE.md` is a symlink, which the upgrade never reads or edits; say so, and suggest the user check its target by hand.

## Step 3: Initialize a new journal

Skip if `journal_exists` is true.

Tell the user `.project-log/journal.jsonl` will be created, and ask: `► Create it in <repo-root>? (y/n)`. On yes:

```bash
SETUP init
python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_log.py" --type memo --description "Journal initialized"
python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_query.py" --status
```

If any command fails, show the error and stop.

## Step 4: Offer CLAUDE.md journal sections

Skip if `claude_md.exists` is false or `claude_md.absent_sections` is empty.

Ask:
```
► Add journal sections to your CLAUDE.md?
  They tell Claude to consult the journal before planning, use /log-commit for
  commits, and propose logging decisions, discoveries, issues, resolutions,
  lessons, and results as they happen. You still confirm every entry. (y/n)
```

On yes, run `SETUP add-sections` and show its output.

## Step 5: Confirm

Tell the user what was done (upgraded, initialized, or already current), and list the available skills: `/log-entry`, `/checkpoint`, `/resume`, `/log-status`, `/log-list`, `/log-summarize`, `/log-commit`, `/research-note`, `/research-report`.
