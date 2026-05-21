---
name: log-init
description: Initialize the project journal system in the current git repo. Creates .project-log/ directory, journal.jsonl, and installs journal_log.py and journal_query.py. Use when the user says /log-init, "set up journal", "initialize journal", or "set up project logging". Only needs to be run once per repo.
---

## Step 1: Find repo root

Run `git rev-parse --show-toplevel`.

If this fails (not a git repo), tell the user and stop.

## Step 2: Check for existing setup

Check if `<repo-root>/.project-log/journal.jsonl` already exists.

If it does, tell the user the journal is already initialized and show the entry count:
```bash
wc -l <repo-root>/.project-log/journal.jsonl
```
Ask if they want to continue anyway. Stop if they say no.

## Step 3: Locate script source

The scripts are bundled with this skill. Confirm both exist before proceeding:
- `${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_log.py`
- `${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_query.py`

If they are missing, tell the user to reinstall the plugin and stop.

## Step 4: Confirm before creating anything

Tell the user what will be created:
- `.project-log/` directory
- `.project-log/journal.jsonl` (empty)
- `.project-log/journal_log.py` (copied from skill)
- `.project-log/journal_query.py` (copied from skill)

Ask: `► Create these files in <repo-root>? (y/n)`

Do not create anything until confirmed.

## Step 5: Create files

```bash
mkdir -p <repo-root>/.project-log
touch <repo-root>/.project-log/journal.jsonl
cp ${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_log.py <repo-root>/.project-log/
cp ${CLAUDE_PLUGIN_ROOT}/skills/log-init/scripts/journal_query.py <repo-root>/.project-log/
chmod +x <repo-root>/.project-log/journal_log.py
chmod +x <repo-root>/.project-log/journal_query.py
```

## Step 6: Verify

```bash
python3 <repo-root>/.project-log/journal_log.py --type memo --description "Journal initialized"
python3 <repo-root>/.project-log/journal_query.py --status
```

If either fails, show the error and stop.

## Step 6.5: Offer proactive logging rules for CLAUDE.md

Check if `<repo-root>/CLAUDE.md` exists.

If it does not exist, skip this step silently.

If it exists, check whether it already contains a `## Journal — Proactive Logging` section:
```bash
grep -q "## Journal — Proactive Logging" <repo-root>/CLAUDE.md && echo "exists" || echo "absent"
```

If already present, skip.

If absent, ask:
```
► Add proactive journal logging rules to your CLAUDE.md?
  This tells Claude to propose logging decisions, discoveries, issues,
  resolutions, lessons, and experiment results as they happen in conversation.
  You still confirm every entry. (y/n)
```

If yes, append the following section to `<repo-root>/CLAUDE.md`:

```markdown
## Journal — Consultation Before Planning

Before drafting any non-trivial plan, query the journal:
1. `python3 .project-log/journal_query.py --unresolved-issues` — surface active blockers
2. `python3 .project-log/journal_query.py --list decision --since 7d` — surface recent decisions that constrain the approach

When a plan step is informed by a journal entry, cite the short ID inline (e.g. `[→ issue 71af7634]`). A `decision` entry is a resolved constraint — retrieve full context before re-opening: `python3 .project-log/journal_query.py --entry <id>`.

## Journal — Committing

The word **"commit"** means the **ml-journal `/log-commit` skill** — not bare `git commit`, not any other commit helper. The skill stages files, synthesizes a commit message, creates the commit, and writes a `git` journal entry in one step. Never use a different commit path in this project.

## Journal — Proactive Logging

When `.project-log/journal.jsonl` exists, propose logging at natural pauses — not mid-investigation. Always ask first; full draft only after user confirms.

**Auto-propose these types:**

| Pattern | Type | When |
|---------|------|------|
| User confirms a direction | `decision` | After "I agree", "let's do X", "go with that" |
| Unexpected finding | `discovery` | When exploration changes understanding or approach |
| Bug/inconsistency found | `issue` | After identifying and explaining a problem |
| Bug fixed and verified | `resolution` | After fix confirmed working |
| Root cause understood | `lesson` | After explaining *why* something broke — ask "should I log this as a lesson?" |
| Results interpreted | `experiment` | When verdict is clear |
| Major phase or block of work completes | `summary` | After finishing an experiment version, resolving a cluster of issues, or wrapping a multi-step investigation |

**Do not auto-propose:** `/checkpoint`, `/resume`, `/log-commit`, `/research-note`, `/research-report`, read skills, `hypothesis`, `post_mortem`, `memo`.

**Rules:** One proposal per event. Don't re-propose if declined. Chain issue→resolution→lesson at completion, not as three interruptions.
```

## Step 7: Confirm

Tell the user:
- Journal initialized at `.project-log/journal.jsonl`
- One initialization entry logged
- Available skills: `/log-entry`, `/checkpoint`, `/resume`, `/log-status`, `/log-list`, `/log-summarize`, `/log-commit`, `/research-note`, `/research-report`
