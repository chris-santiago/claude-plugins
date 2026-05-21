---
name: resume
description: Load the most recent session checkpoint from the project journal and surface it to the console. Use when the user says /resume, "what were we working on", "load last checkpoint", "restore state", "catch me up", or at the start of a session when continuing prior work. Also triggered automatically by the SessionStart hook when a journal exists.
---

## Step 1: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

If `.project-log/journal.jsonl` does not exist, say: "No journal found in this repo. Run `/journal-init` to set one up." Stop.

## Step 2: Load latest checkpoint

```bash
python3 <repo-root>/.project-log/journal_query.py --latest-checkpoint
```

## Step 3: Surface and prompt

Display the full formatted output from the query script.

Then ask: "How would you like to proceed?"

Do not summarize or reinterpret the checkpoint — surface it as-is so nothing is lost in translation.

## If no checkpoint exists

If the query returns "No checkpoint found", say:

"No checkpoint found in this journal. There are entries — use `/journal-status` to see what's been logged."

Or if the journal is empty:

"Journal exists but has no entries yet."
