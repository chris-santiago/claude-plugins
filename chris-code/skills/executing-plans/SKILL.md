---
name: executing-plans
description: Use when executing a plan for small work inline, in this session, with lighter review than subagent-driven-development
---

# Executing Plans

## Overview

Load plan, review critically, execute all tasks inline, report when complete. This is the light path for small work: you implement each task yourself against its brief, the quality reviewers check it, and the same scripted gate checks each commit. It skips subagent-driven-development's triage loop, spec reviewer, and record evidence, so its assurance is lighter; for larger or riskier plans, use that skill instead.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

## The Process

### Step 1: Load and Review Plan
1. Read plan file
2. Review critically - identify any questions or concerns about the plan
3. If concerns: Raise them with your human partner before starting
4. If no concerns: check the progress ledger (`python3 "$SDD_SCRIPTS/ledger.py" run-state --store "$STORE"` and `python3 "$SDD_SCRIPTS/ledger.py" read --store "$STORE"`, where `SDD_SCRIPTS` and `STORE` are resolved once per subagent-driven-development's File Handoffs: `SDD_SCRIPTS` is that skill's absolute `scripts/` directory (derive it from this skill's "Base directory for this skill" line as `<that directory>/../subagent-driven-development/scripts`, since SDD itself isn't loaded here), and `STORE=$(python3 "$SDD_SCRIPTS/ledger.py" store-dir)` is the single authority for the store path, default or the session's `--store` override) and `python3 "$SDD_SCRIPTS/ledger.py" completed --store "$STORE"` for which task ids are DONE — rebuild TodoWrite from the ledger and resume at the first task id `completed` doesn't list (first apply subagent-driven-development's stale-store test in *Durable Progress*, and `clear` a store left by a different plan, or `completed` will skip this plan's tasks as done); otherwise create TodoWrite and proceed

### Step 2: Execute Tasks

For each task:
1. Mark it in_progress, record its footprint (`python3 "$SDD_SCRIPTS/ledger.py" stage --task N --stage N --files <paths> --store "$STORE"`), and build its brief: `python3 "$SDD_SCRIPTS/task_brief.py" PLAN_FILE N --intent "..." --store "$STORE" -o "$STORE/task-N-brief.md"`. The brief carries the task's notes and its rigor level (`Rigor: <level> (<reasons>)`), and logs the notes' delivery. Test and review the task to that level, per subagent-driven-development's `rigor.md`. The script refuses a task whose `Cases:` rows state no result, that still has an `open:` row, whose `Verify:` line has no command, or whose `Rigor:` line is below the project level: fix the plan (asking the user for an `open:` answer) rather than working around it. File notes the way subagent-driven-development's *Run Notes* section describes.
2. Implement against the brief: every row on its `Cases:` line, each with a test. For behavior the brief leaves undefined, do what the codebase already does for the nearest analogous case, and note the choice and its precedent for the user (a `question` note owned by the task, resolved with their answer). A case you handle that the `Cases:` line didn't list goes in a follow-up note (`ledger.py note --kind follow-up --from N --text "unlisted case: ..."`).
3. Run the brief's `Verify:` command exactly.
4. Dispatch **all matching** `*-quality-reviewer` agents (additive — e.g., both `python-quality-reviewer` and `pytorch-quality-reviewer` fire on `.py` and `.ipynb` files in a PyTorch project). Give each the brief path, the changed-file list, the plan's Constraints verbatim, a record path at `$STORE/task-N-<agent-name>.json`, a report path at `$STORE/task-N-<agent-name>-review.md`, and the scripts path (`$SDD_SCRIPTS`, expanded). Each returns one line; read its findings in its record. A REVISE (any finding of severity 3 or more) gets a fix round: first take a snapshot (`python3 "$SDD_SCRIPTS/ledger.py" snapshot --task N --label "pre-fix c<cycle>" --store "$STORE"`, which prints the tree), then sweep each finding's rule across the task's files, write a failing test first, fix every site, and re-dispatch the reviewers that raised findings at their same record paths with `Fix baseline: <tree>`, the task's file list, and the round's kind (`patch`), so they judge the fix diff. Notes (severity 1-2) are fixed alongside, or filed as follow-ups. **At most two fix rounds, then stop and ask the user** with the open findings and both rounds' results.
5. Run the Step 3 commit gate for the task. Once it is committed, mark it completed in TodoWrite and append the typed completion entry: `python3 "$SDD_SCRIPTS/ledger.py" append --type complete --task N --light --note "commits <base7>..<head7>" --store "$STORE"`.

### Step 3: Commit Gate

1. `python3 "$SDD_SCRIPTS/ledger.py" ready --task N --light --store "$STORE"` lists anything that still stops the commit (an undelivered note, an open question, an open disclosure). Settle each first.
2. Stage exactly the task's files and run `python3 "$SDD_SCRIPTS/ledger.py" gate --task N --test "<the task's Verify: command>" [--lint "<the project's lint command>"] --store "$STORE"`. It runs the process-label scan on the staged lines, then lint, then the tests, each passing only on exit 0, and refuses while a task file has unstaged changes. A label or lint failure: rewrite and re-stage. A test failure: it's a fix round (Step 2, item 4's limit applies).
3. Commit, then `complete --light` (Step 2, item 5). It refuses a commit that doesn't match what the gate passed.

### Step 4: Final Review

After all tasks complete, review the whole change to catch cross-task drift the per-task reviews missed. The task commits are already in, so hand `*-review-lite` the whole-change diff as a file:

1. `BASE=$(git merge-base HEAD main)` (or the actual base), `HEAD=$(git rev-parse HEAD)`.
2. Run `"$SDD_SCRIPTS/review-package" "$BASE" "$HEAD" "$STORE/review-whole-change.diff"` to write the multi-commit diff to that file and print its path. Pass the explicit outfile: the script's own default resolves the default store, which is wrong when the session overrode `--store`.
3. Dispatch each matching `*-review-lite` agent with that package-file path, a record path at `$STORE/final-<agent-name>.json`, and the scripts path (`$SDD_SCRIPTS`, expanded). A block is a fix round: fix, gate the fix with `--task final --test "<the project's full test suite>"`, commit, and re-dispatch at the same record path. Two rounds, then the user.

### Step 5: Complete Development

After final review passes:
- **REQUIRED SUB-SKILL:** Use chris-code:verification-before-completion first. The final review is a diff-level idiom check; it doesn't exercise behavior or assess design, so the completion close (design, intent, and mutation gates) is still owed, exactly as after subagent-driven-development.
- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** Use chris-code:finishing-a-development-branch
- Follow that skill to verify tests, present options, execute choice

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Hit a blocker (missing dependency, test fails, instruction unclear)
- Plan has critical gaps preventing starting
- You don't understand an instruction
- Verification fails repeatedly

**Ask for clarification rather than guessing.**

## When to Revisit Earlier Steps

**Return to Review (Step 1) when:**
- Partner updates the plan based on your feedback
- Fundamental approach needs rethinking

**Don't force through blockers** - stop and ask.

## Remember
- Review plan critically first
- Implement against each task's brief
- Don't skip verifications
- Reference skills when plan says to
- Stop when blocked, don't guess
- Track progress in the durable ledger, not only TodoWrite — after compaction, resume from the ledger and `git log`, not recollection
- Never start implementation on main/master branch without explicit user consent

## Integration

**Required workflow skills:**
- **chris-code:using-git-worktrees** - Ensures isolated workspace
- **chris-code:lean-plan** - Creates the plan this skill executes
- **chris-code:verification-before-completion** - The completion close, before finishing
- **chris-code:finishing-a-development-branch** - Complete development after all tasks
- **`*-quality-reviewer` agents** - Per-task quality + bug review, auto-dispatched by file type
- **`*-review-lite` agents** - The final full-diff review, auto-dispatched by file type
