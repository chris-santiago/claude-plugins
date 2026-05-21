---
name: log-commit
description: Stage, commit, and log to the project journal in one step. Use when the user says /journal-commit, /jcommit, "commit and log", "commit this", or indicates work is ready to commit. Synthesizes the commit message from conversation context and logs a git entry to the journal simultaneously.
---

## Step 0: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

If `.project-log/journal.jsonl` does not exist, say: "No journal found. Run `/journal-init` first." Stop.

## Step 1: Understand what's changed

```bash
git status --short
git diff --stat HEAD
git branch --show-current
git log --oneline -5
```

Show the status and diff stat to the user so they can see what will be committed.

If nothing is staged or modified, say so and stop.

## Step 2: Determine what to stage

If specific files were mentioned by the user, stage only those:
```bash
git add <files>
```

Otherwise, stage all changes:
```bash
git add -A
```

Do not stage `.project-log/journal.jsonl` yet — it will be added after the journal entry is written.

## Step 3: Synthesize commit message

From the conversation context and the diff stat, write a commit message:
- First line: imperative mood, ≤72 characters, describes *what* changed
- Optional second paragraph (after blank line): *why*, if non-obvious
- Match the prefix style (e.g. `feat:`, `fix:`, `chore:`, `docs:`) used in recent commits from `git log`

Do not use generic messages like "update files" or "wip".

## Step 4: Synthesize journal fields

From the same context, prepare `git` entry fields:
- `message` — same as commit message first line
- `branch` — from `git branch --show-current`
- `files_changed` — comma-separated list of changed files (excluding journal.jsonl)
- `diff_summary` — 1–2 sentence prose description of what the commit does

## Step 5: Show draft and confirm

```
Commit message:   <message>
Files:            <file list>
Journal entry:    git | <diff_summary>
```

Ask: `► Commit and log? (y/n)`

Do not run git or write to journal until confirmed.

## Step 6: Log to journal

Write the journal entry **before** committing so it can be included in the same commit:

```bash
python3 <repo-root>/.project-log/journal_log.py \
  --type git \
  --message "<message>" \
  --branch <branch> \
  --files-changed "<file1, file2, ...>" \
  --diff-summary "<summary>"
```

Note: `commit_hash` is omitted here — it is not knowable before the commit and is recorded as optional metadata. The journal entry is linked to the commit by being part of it.

## Step 7: Stage journal and commit

Stage the journal file alongside everything else, then commit in one shot:

```bash
git add .project-log/journal.jsonl
git commit -m "<message>"
```

Capture the commit hash from the output (format: `[branch abc1234]`).

If commit fails, show the error and stop. The journal entry was already written — note this to the user so they can manually reset if needed.

## Step 8: Confirm

Show both confirmations:
- `[branch abc1234] <message>`
- `Logged [git] <id> at <timestamp>` (synthesized from the journal_log.py output)
