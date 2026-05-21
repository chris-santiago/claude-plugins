---
name: log-status
description: Show a quick summary of the current project journal state — last checkpoint, entry counts for this session, unresolved issues, and recent git entries. Use when the user says /journal-status, "journal status", "where are we", "what's open", "what have we logged", or "show me the journal state".
---

## Step 1: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

If `.project-log/journal.jsonl` does not exist, say: "No journal found in this repo. Run `/journal-init` to set one up." Stop.

## Step 2: Run status query

```bash
python3 <repo-root>/.project-log/journal_query.py --status
```

## Step 3: Surface output

Display the formatted output as-is. No further action needed.
