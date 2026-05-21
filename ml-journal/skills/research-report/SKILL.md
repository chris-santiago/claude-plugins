---
name: research-report
description: Synthesize a full research report from the project journal, git history, and supplementary markdown files. Produces RESEARCH_REPORT.md at the repo root. Use when the user says /research-report, "write a full research report", "end-of-project writeup", "document our full research history", "create a project report", or "document our research history".
---

## Step 1: Find repo root and check journal

```bash
git rev-parse --show-toplevel
```

If `.project-log/journal.jsonl` does not exist, say: "No journal found. Run `/log-init` first." Stop.

## Step 2: Check for existing report

```bash
ls <repo-root>/RESEARCH_REPORT.md 2>/dev/null
```

If one exists, note it to the user: "An existing RESEARCH_REPORT.md was found — the new synthesis will replace it. (Git has history.)" Do not let it constrain the new synthesis.

## Step 3: Dispatch report-drafter

Invoke the `report-drafter` agent with:
- The repo root path
- The project name (directory name of the repo root)
- Whether an existing RESEARCH_REPORT.md was found

Wait for the agent to return a draft.

## Step 4: Show draft and confirm

Show the full draft to the user.

Ask: `► Write to RESEARCH_REPORT.md? This will overwrite any existing file. (y/n)`

(Git has history — overwriting is safe.)

## Step 5: Write file

Write to `<repo-root>/RESEARCH_REPORT.md`.

Confirm: "RESEARCH_REPORT.md written — <N> lines."
