---
name: research-note
description: Generate a formatted research note from recent journal activity. Produces a session-scoped or day-scoped markdown note suitable for sharing, attaching to a PR, or archiving. Use when the user says /research-note, "write a research note", "create a note from today's work", "summarize today as a note", "generate a shareable summary", "write up this session", or "create an experiment note for this session".
---

## Step 1: Check journal exists

```bash
git rev-parse --show-toplevel
```

If `.project-log/journal.jsonl` does not exist, say: "No journal found. Run `/log-init` first." Stop.

## Step 2: Determine scope

From the user's request, determine the time window:
- "today" / no qualifier → `1d`
- "this session" → `12h` (generous window; filter to current session in synthesis)
- "yesterday" → `2d` (look back 2 days, note in header)
- "last N days" / "this week" → appropriate value (`3d`, `7d`, etc.)

## Step 3: Gather inputs

**Check conversation context first.** If a `log-summarize` synthesis is already present in the current conversation, use it as the primary input — do not re-query those entry types.

Whether or not a summary exists, also gather:

```bash
python3 <repo-root>/.project-log/journal_query.py --latest-checkpoint
python3 <repo-root>/.project-log/journal_query.py --unresolved-issues
git log --oneline --since="<N> days ago"
```

If no existing summary in context, query all relevant types for the scope window:

```bash
python3 <repo-root>/.project-log/journal_query.py --list decision --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list discovery --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list experiment --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list issue --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list resolution --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list hypothesis --since <scope>
python3 <repo-root>/.project-log/journal_query.py --list lesson --since <scope>
```

If all queries return empty and there is no existing summary, tell the user there is nothing to note for the requested scope and stop.

## Step 4: Synthesize note

Write a formatted markdown note using the template below. Include only sections that have content — omit empty sections entirely. Do not write placeholder text.

Target length: 40–80 lines. This is a shareable artifact, not a comprehensive report. Be specific — reference actual entry content, not vague summaries.

```markdown
# Research Note — <project name>

*<YYYY-MM-DD> | <N> entries | scope: <today / last N days / this session>*

## Summary
[2–4 sentence prose summary of what was accomplished and its significance]

## Key Decisions
- [Decision + brief rationale]

## Discoveries & Results
- [Discovery or experiment result with verdict]

## Issues
- [Open or resolved issues; note severity for open ones]

## Current State
[From checkpoint: what is in progress, what is pending. Omit if no checkpoint in scope.]

## Next Steps
- [From open_threads and pending_decisions]
```

## Step 5: Determine output filename

Default: `RESEARCH_NOTE_<YYYY-MM-DD>.md` in `<repo-root>/research-notes/`.

Create the directory if it does not exist:

```bash
mkdir -p <repo-root>/research-notes
```

Check if this file already exists:

```bash
ls <repo-root>/research-notes/RESEARCH_NOTE_<date>.md 2>/dev/null
```

If it exists, ask: `research-notes/RESEARCH_NOTE_<date>.md already exists. Overwrite, or save as RESEARCH_NOTE_<date>_<HHMM>.md? (overwrite / new)`

## Step 6: Show draft and confirm

Show the full draft to the user.

Ask: `► Save to research-notes/<filename>? (y/n)`

## Step 7: Write file

Write to `<repo-root>/research-notes/<filename>`.

Confirm: `research-notes/<filename> written — <N> lines. Ready to share or attach to a PR.`
