# Project Journal System — Combined Spec

## Overview

A persistent, structured audit trail for research and development work. Captures decisions, issues, discoveries, experiments, and session state across Claude sessions. Machine-queryable append-only log with Claude skills as the judgment layer and Python scripts as the mechanical layer.

---

## Architecture

```
judgment layer     →    Claude skills (extract, classify, construct args)
mechanical layer   →    Python scripts (validate, serialize, write)
storage            →    .project-log/journal.jsonl (per-repo, append-only)
```

No background daemons. No git hooks. Everything happens through explicit skill invocation within Claude sessions.

---

## Storage

### Location

```
<repo-root>/.project-log/journal.jsonl
```

One file per repo. Each line is a complete, valid JSON object. Never modified after write — append only.

### `.project-log/.gitignore`

```
# nothing — journal.jsonl and scripts are tracked
```

No daemon logs to ignore since there is no daemon.

---

## Entry Schema

### Common Envelope (all types)

```json
{
  "id": "<uuid4>",
  "timestamp": "<ISO8601>",
  "type": "<entry type>",
  "project": "<repo directory name>",
  "session_id": "<CLAUDE_SESSION_ID env var>"
}
```

`journal_log.py` auto-generates `id`, `timestamp`, `project`, and `session_id`. Skills never construct these.

---

### Entry Types and Type-Specific Fields

#### `issue`
```json
{
  "description": "string",
  "severity": "low | moderate | high | critical",
  "tags": ["string"],
  "context": "string"
}
```

#### `resolution`
```json
{
  "description": "string",
  "linked_issue_id": "uuid — optional",
  "approach": "string"
}
```

#### `decision`
```json
{
  "description": "string",
  "rationale": "string",
  "alternatives": "string"
}
```

#### `discovery`
```json
{
  "description": "string",
  "implications": "string",
  "source": "string"
}
```

#### `hypothesis`
```json
{
  "description": "string",
  "expected_result": "string",
  "metric": "string"
}
```

#### `experiment`
```json
{
  "description": "string",
  "linked_hypothesis_id": "uuid — optional",
  "metric": "string",
  "result": "string",
  "verdict": "confirmed | refuted | inconclusive"
}
```

#### `lesson`
```json
{
  "description": "string",
  "context": "string — what situation surfaced this lesson",
  "applies_to": "string — what area, component, or workflow this affects",
  "linked_id": "uuid — optional, any entry type that prompted this"
}
```

#### `memo`
```json
{
  "description": "string",
  "tags": ["string"] 
}
```

#### `post_mortem`
```json
{
  "description": "string",
  "what_failed": "string",
  "root_cause": "string",
  "contributing_factors": "string",
  "lessons": "string",
  "linked_issue_id": "uuid — optional"
}
```

#### `summary`
```json
{
  "description": "string",
  "key_decisions": ["string"],
  "open_threads": ["string"]
}
```

#### `checkpoint`
```json
{
  "in_progress": "string",
  "pending_decisions": "string",
  "recently_completed": "string",
  "key_context": "string",
  "git_state": "string — omit if clean on main",
  "open_threads": ["string"]
}
```

#### `git`
```json
{
  "commit_hash": "string",
  "message": "string",
  "branch": "string",
  "files_changed": ["string"],
  "diff_summary": "string"
}
```

---

## Python Scripts

All scripts are standalone Python (stdlib only), run via `python3`. Located in `.project-log/`.

### `journal_log.py`

**Responsibility:** validate, construct envelope, append entry.

**Interface:**
```bash
python3 .project-log/journal_log.py \
  --type issue \
  --description "GRU last hidden state pooling outperforms mean pooling" \
  --severity high \
  --tags "modeling,pooling" \
  --context "Proxy-scale experiment loop, 3 seeds"
```

- Reads `CLAUDE_SESSION_ID` from environment automatically
- Derives `project` from `git rev-parse --show-toplevel` basename
- Validates required fields per type — exits non-zero with clear error if missing
- Appends single JSON line to `.project-log/journal.jsonl`
- Prints confirmation: `Logged [type] <id> at <timestamp>`

### `journal_query.py`

**Responsibility:** all read operations. Powers status, list, resume, summarize commands.

**Interface:**
```bash
python3 .project-log/journal_query.py --latest-checkpoint
python3 .project-log/journal_query.py --status
python3 .project-log/journal_query.py --list issue --since 7d
python3 .project-log/journal_query.py --list decision
python3 .project-log/journal_query.py --unresolved-issues
python3 .project-log/journal_query.py --entry <id>
```

Outputs human-readable formatted text for surface-to-console use. Skills never parse the output — they pass it through to the user as-is.

---

## Skills

Skills are the judgment layer. Claude reads context, determines type and field values, constructs the appropriate script invocation. Scripts handle all mechanical correctness.

### `/journal-init`

**Trigger:** user says `/journal-init` or "set up journal for this project"

**Steps:**
1. `git rev-parse --show-toplevel` — find repo root
2. Check if `.project-log/` already exists — warn if so, ask before proceeding
3. Create `.project-log/` directory
4. Create empty `.project-log/journal.jsonl`
5. Copy `journal_log.py` and `journal_query.py` into `.project-log/`
6. Confirm: "Journal initialized at `.project-log/journal.jsonl`"

One-time per repo.

---

### `/journal-entry`

**Trigger:** "log this", "record this", "log this issue / decision / discovery / experiment / post mortem", or any phrasing indicating something should be captured

**Steps:**
1. Infer entry type from conversation context. If ambiguous, state assumption and proceed — user can correct.
2. Extract relevant field values from conversation.
3. For types requiring confirmation (`decision`, `post_mortem`, `experiment`, `summary`, `checkpoint`): show proposed entry, ask "► Log this? (y/n)"
4. For low-stakes types (`issue`, `resolution`, `discovery`, `hypothesis`, `lesson`, `memo`): run directly, show result after.
5. Construct and run `python3 .project-log/journal_log.py --type <type> [fields...]`
6. Surface confirmation output to user.

**Type inference heuristics:**
- "we found that X" / "turns out X" → `discovery`
- "X is broken / failing" → `issue`
- "we decided to / we're going with" → `decision`
- "we're going to try / hypothesis: X" → `hypothesis`
- "the experiment showed / result was" → `experiment`
- "fixed the X issue" → `resolution`
- "what went wrong / post mortem" → `post_mortem`
- "note this / remember / memo / don't forget" → `memo`

---

### `/journal-commit`

**Trigger:** "commit", "git commit", "/jcommit", or user indicates work is ready to commit

**Steps:**
1. Run `git status --short` and `git diff --stat HEAD` to understand what's staged/changed.
2. Synthesize a commit message from conversation context and diff.
3. Show proposed commit message and journal entry fields. Ask "► Commit and log? (y/n)"
4. On confirm:
   a. `git add -A` (or targeted add if user specified files)
   b. `git commit -m "<message>"`
   c. Capture commit hash from output
   d. `python3 .project-log/journal_log.py --type git --commit-hash <hash> --message "<message>" --branch <branch> --files-changed <files> --diff-summary "<summary>"`
5. Confirm: "Committed `<hash>` and logged to journal."

---

### `/checkpoint`

**Trigger:** "/checkpoint", "save state", "checkpoint before compact", "end of session"

**Steps:**
1. `git rev-parse --show-toplevel` — find repo root
2. `git status --short` and `git branch --show-current` — get git state
3. Synthesize from conversation:
   - `in_progress` — what is actively being worked on
   - `pending_decisions` — open questions or blockers
   - `recently_completed` — what finished this session
   - `key_context` — hard-won facts expensive to re-derive
   - `open_threads` — structured list of unresolved items
   - `git_state` — omit if clean on main
4. Show draft. Ask "► Write checkpoint? (y/n)"
5. `python3 .project-log/journal_log.py --type checkpoint [fields...]`
6. Confirm: "Checkpoint written. Run `/compact` when ready."

---

### `/resume`

**Trigger:** "/resume", "what were we working on", "load last checkpoint", session start with existing journal

**Steps:**
1. `python3 .project-log/journal_query.py --latest-checkpoint`
2. Surface formatted output to console
3. Ask: "How would you like to proceed?"

If no checkpoint exists: "No checkpoint found in journal. Starting fresh."

---

### `/journal-status`

**Trigger:** "/journal-status", "journal status", "where are we", "what's open"

**Steps:**
1. `python3 .project-log/journal_query.py --status`
2. Surface output. No further action.

**Status output covers:**
- Last checkpoint (timestamp + open threads)
- Entry counts by type for current session
- Unresolved issues (issues with no linked resolution)
- Last 5 git entries logged

---

### `/journal-list`

**Trigger:** "show recent [type]", "list [decisions / issues / experiments / ...]", "what issues have we logged"

**Steps:**
1. Determine requested type and time window from user phrasing
2. `python3 .project-log/journal_query.py --list <type> [--since <N>d]`
3. Surface output.

---

### `/journal-summarize`

**Trigger:** "summarize [decisions / issues / experiments]", "what decisions have we made", "give me a summary of open issues"

**Steps:**
1. `python3 .project-log/journal_query.py --list <type>` — get all entries of requested type
2. Claude synthesizes prose summary from the structured output
3. Surface summary. Offer to log as `summary` type entry.

---

### `/research-note`

**Trigger:** "/research-note", "write a research note", "create a note from today's work", "summarize today as a note", "generate a shareable summary", "write up this session", "create an experiment note for this session"

**Steps:**
1. `git rev-parse --show-toplevel` — find repo root, check journal exists
2. Determine scope from user phrasing (default: `1d`)
3. Check conversation context for existing `log-summarize` output; if present, use as primary input
4. If no existing summary: `journal_query.py --list <type> --since <scope>` for decision, discovery, experiment, issue, resolution, hypothesis, lesson
5. Also gather: `journal_query.py --latest-checkpoint`, `--unresolved-issues`, `git log --oneline --since`
6. Synthesize a 40–80 line note (Summary, Key Decisions, Discoveries & Results, Issues, Current State, Next Steps — omit empty sections)
7. Show draft. Ask "► Save to RESEARCH_NOTE_<date>.md? (y/n)"
8. Write to `<repo-root>/RESEARCH_NOTE_<date>.md`

---

### `/research-report`

**Trigger:** "/research-report", "write a full research report", "end-of-project writeup", "document our full research history", "create a project report"

**Steps:**
1. `git rev-parse --show-toplevel` — find repo root, check journal exists
2. Check if `RESEARCH_REPORT.md` already exists; note to user if so
3. Dispatch `report-drafter` agent with repo root, project name, and existing-report flag — agent reads full journal, git log, and supplementary markdown files; synthesizes and returns the full draft
4. Show draft. Ask "► Write to RESEARCH_REPORT.md? (y/n)" — overwrites, git has history.
5. Write to `<repo-root>/RESEARCH_REPORT.md`

**Agent:** `report-drafter` — handles all context ingestion (full journal, git history, supplementary docs) in an isolated subcontext. Produces a 9-section draft (Problem Statement, Timeline, What Was Tried, What Failed, What Worked, Key Decisions, Issues and Resolutions, Current State, Open Questions). Never writes files directly.

---

## Consultation Patterns

The journal is a source of truth, not only an append log. Query it proactively:

### Before Planning
Before drafting any non-trivial plan:
1. `python3 .project-log/journal_query.py --unresolved-issues` — surface active blockers
2. `python3 .project-log/journal_query.py --list decision --since 7d` — surface recent decisions that constrain the approach

### Cross-Reference in Plans and Instructions
When a plan step is informed by or constrained by a journal entry, include the short ID:
- Example: "Implement union-of-issues IDR for ensemble [→ issue 71af7634]"
- This creates a traceable thread from planning documents back to diagnostic history

### Decisions as Constraints
A `decision` entry represents a resolved choice. Retrieve full context before re-opening:
`python3 .project-log/journal_query.py --entry <id>`

---

## Hooks (Optional)

Hooks are **not registered by default** — the system functions fully via explicit skill invocation. Install only if your environment permits hooks (e.g., personal machines). Use `.claude/settings.local.json` (per-machine, gitignored) rather than `.claude/settings.json` (tracked) so the configuration is not committed.

To enable:

```json
{
  "hooks": {
    "PreCompact": [{ "type": "command", "command": "bash plugins/ml-journal/journal-precompact.sh" }],
    "SessionStart": [{ "type": "command", "command": "bash plugins/ml-journal/journal-session-start.sh" }]
  }
}
```

### PreCompact hook (preferred) / PostCompact fallback

**PreCompact** fires while full conversation context is available — richer checkpoint synthesis. **PostCompact** fires after compaction from the compaction summary — degraded but better than nothing.

Verify PreCompact is an available hook type in Claude Code before implementing. Fall back to PostCompact if not.

Hook behavior:
1. `git rev-parse --show-toplevel` — detect repo
2. Check for `.project-log/journal.jsonl` — exit silently if not found (repo not initialized)
3. Synthesize checkpoint fields from context (PreCompact) or compaction summary from stdin JSON (PostCompact)
4. `python3 .project-log/journal_log.py --type checkpoint [fields...]` — no confirmation, context is being lost
5. Exit silently on success

### SessionStart hook

1. `git rev-parse --show-toplevel` — detect repo
2. Check for `.project-log/journal.jsonl` — exit silently if not found
3. `python3 .project-log/journal_query.py --latest-checkpoint`
4. Emit JSON with `additionalContext` injecting checkpoint as session context
5. Exit silently if no checkpoint exists

### Hook graceful degradation

All hooks:
- Exit silently if not in a git repo
- Exit silently if `.project-log/journal.jsonl` does not exist
- Exit silently on any error — never block Claude session startup

---

## Confirmation Behavior Summary

| Type | Confirm before logging? |
|---|---|
| `issue` | No |
| `resolution` | No |
| `discovery` | Yes |
| `hypothesis` | Yes |
| `lesson` | No |
| `memo` | No |
| `git` | Yes (commit is irreversible) |
| `decision` | Yes |
| `experiment` | Yes |
| `post_mortem` | Yes |
| `summary` | Yes |
| `checkpoint` | Yes |

---

## Implementation Order

1. `journal_log.py` — core writer, test with manual invocations for each type
2. `journal_query.py` — reader, test `--status`, `--latest-checkpoint`, `--list`
3. `/journal-init` skill — wires setup
4. `/journal-entry` skill — main logging path
5. `/checkpoint` and `/resume` skills — session continuity
6. `/journal-commit` skill — git + log in one step
7. `/journal-status`, `/journal-list`, `/journal-summarize` skills — query layer
8. `/research-note` skill — session-scoped formatted note
9. `/research-report` skill — full research report synthesis
9. Hooks — optional, add last

---

## Dependencies

- `python3` (>= 3.10) — all scripts use stdlib only, no external packages
- `git` — repo detection, commit operations, log queries
- `jq` — hooks only, for JSON parsing from stdin
- No hardcoded paths anywhere — fully portable across git repos

---

## Edge Cases

- **Not in a git repo:** all hooks and skills detect this and exit/stop silently
- **`.project-log/` not initialized:** hooks exit silently; skills prompt to run `/journal-init`
- **Concurrent sessions:** append operations are atomic under PIPE_BUF; entries are small enough
- **Auto vs manual checkpoints:** auto (hook) entries carry same schema as manual — no labeling difference needed since `session_id` distinguishes them
- **Out-of-Claude commits:** not captured — acceptable tradeoff for simplicity. User can run `/journal-entry` manually to backfill a `git` entry if needed.
