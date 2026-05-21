---
name: checkpoint
description: Save a session checkpoint to the project journal. Captures current work state for handoff to future sessions or post-compact recovery. Use when the user says /checkpoint, "save state", "checkpoint before compact", "end of session", or "save my progress". Also invoked automatically by the PreCompact hook.
---

## Step 0: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

Check that `<repo-root>/.project-log/journal.jsonl` exists. If not, tell the user to run `/journal-init` first and stop.

## Step 1: Get git state

```bash
git status --short
git branch --show-current
```

Only include git state in the checkpoint if there is something noteworthy — staged files, uncommitted changes, or a non-main branch. Omit entirely if working tree is clean and on main.

## Step 2: Synthesize checkpoint fields

From the conversation history, draft concise values for:

**in_progress** — what is actively being worked on right now (specific tasks, files, decisions in flight). 1–3 sentences.

**pending_decisions** — open questions or blockers the next session must resolve. 1–3 sentences. Omit if none.

**recently_completed** — what finished this session, so the next session knows what "done" means. 1–3 sentences. Omit if nothing meaningful completed.

**key_context** — hard-won facts expensive to re-derive: confirmed root causes, design decisions already settled, gotchas discovered, corrections already made. 1–3 sentences. Omit if nothing critical.

**git_state** — e.g. "branch: feature/pooling-experiment | modified: src/model.py, config/train.yaml". Omit if clean on main.

**open_threads** — structured list of unresolved items that must not be forgotten. Each item is a short phrase. Pull from pending_decisions and any other loose ends in the conversation.

Keep each field tight. Omit fields that genuinely don't apply — do not pad with filler.

## Step 3: Show draft and confirm

Show the proposed checkpoint as a readable block:

```
In progress:          [...]
Pending decisions:    [...]
Recently completed:   [...]
Key context:          [...]
Git state:            [...]
Open threads:
  • [...]
  • [...]
```

Ask: `► Write checkpoint? (y/n)`

Do not write anything until confirmed.

## Step 4: Write checkpoint

```bash
python3 <repo-root>/.project-log/journal_log.py \
  --type checkpoint \
  --in-progress "..." \
  --pending-decisions "..." \
  --recently-completed "..." \
  --key-context "..." \
  --git-state "..." \
  --open-threads "thread1, thread2, ..."
```

Omit flags for fields that are empty.

## Step 5: Confirm

Show the confirmation line from output.

If the user is about to compact: "Checkpoint written. Run `/compact` when ready."
Otherwise: "Checkpoint written. Use `/resume` to reload this state in a future session."
