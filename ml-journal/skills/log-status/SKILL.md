---
name: log-status
description: Show a quick summary of the current project journal state — last checkpoint, entry counts for this session, unresolved issues, and recent git entries. Use when the user says /journal-status, "journal status", "where are we", "what's open", "what have we logged", or "show me the journal state".
---

## Step 1: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

If `.project-log/journal.jsonl` does not exist, say: "No journal found in this repo. Run `/log-init` to set one up." Stop.

## Step 2: Run status query

```bash
python3 -I "${CLAUDE_SKILL_DIR}/../log-init/scripts/journal_query.py" --status
```

## Step 3: Surface output

Display the formatted output as-is.

If the command also printed a `legacy ml-journal layout` note, relay it and suggest running `/log-init` to upgrade. Hooks may be blocked in this environment, in which case this note is the only place the user sees it.
