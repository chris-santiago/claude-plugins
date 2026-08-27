---
name: executing-plans
description: Use when you have a written implementation plan to execute in a separate session with review checkpoints
---

# Executing Plans

## Overview

Load plan, review critically, execute all tasks, report when complete.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

**Note:** If subagents are available, prefer `chris-code:subagent-driven-development` over this skill.

## The Process

### Step 1: Load and Review Plan
1. Read plan file
2. Review critically - identify any questions or concerns about the plan
3. If concerns: Raise them with your human partner before starting
4. If no concerns: check the progress ledger (`subagent-driven-development/scripts/ledger.py read --store "$STORE"`, where `STORE` is resolved once per subagent-driven-development's File Handoffs via `STORE=$(python3 subagent-driven-development/scripts/ledger.py store-dir)` — the single authority for the store path, default or the session's `--store` override) and `subagent-driven-development/scripts/ledger.py completed --store "$STORE"` for which task ids are DONE — rebuild TodoWrite from the ledger and resume at the first task id `completed` doesn't list; otherwise create TodoWrite and proceed

### Step 2: Execute Tasks

For each task:
1. Mark as in_progress
2. Follow each step exactly (plan has bite-sized steps)
3. Run verifications as specified
4. Dispatch **all matching** `*-quality-reviewer` agents (additive — e.g., both `python-quality-reviewer` and `pytorch-quality-reviewer` fire on `.py` and `.ipynb` files in a PyTorch project). If any returns REVISE: fix issues and re-dispatch until all APPROVED.
5. Mark as completed in TodoWrite, and append to the ledger the typed completion entry: `subagent-driven-development/scripts/ledger.py append --type complete --task N --note "commits <base7>..<head7>, review clean" --store "$STORE"`

### Step 3: Commit Gate

Before each commit (end of plan or mid-plan commit points):

1. **Collect candidates:** Check staged file extensions → match **all** `*-review-lite` agents by `scope.extensions` (additive, not exclusive)
2. **Dispatch** all matching agents against the staged diff, supplying each a record path (`$STORE/task-<N>-<agent-name>.json`, per subagent-driven-development's File Handoffs). Never pass a `cycle` value: the agent reads its own prior record at that path and self-derives `cycle` as prior + 1 (else 1), escalating at `cycle >= 3` with findings remaining — the backstop fires on its own as long as the record path stays stable across re-dispatches.
3. If any agent returns **block**: fix the issue and re-dispatch at the same record path before committing
4. If any agent returns **escalate**: stop and surface to the user

Only dispatch when there are staged changes to review.

### Step 4: Final Review

After all tasks complete, review the whole change to catch cross-task idiom drift the per-commit gates missed. The task commits are already in, so `git diff --cached` is empty and `*-review-lite` cannot use its staged-diff path. Hand it the whole-change diff as a file:

1. `BASE=$(git merge-base HEAD main)` (or the actual base), `HEAD=$(git rev-parse HEAD)`.
2. Run `subagent-driven-development/scripts/review-package "$BASE" "$HEAD"` to write the multi-commit diff to a file and print its path.
3. Dispatch each matching `*-review-lite` agent with that package-file path; the agent reviews the package diff, not `--cached`.

### Step 5: Complete Development

After final review passes:
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
- Follow plan steps exactly
- Don't skip verifications
- Reference skills when plan says to
- Stop when blocked, don't guess
- Track progress in the durable ledger, not only TodoWrite — after compaction, resume from the ledger and `git log`, not recollection
- Never start implementation on main/master branch without explicit user consent

## Integration

**Required workflow skills:**
- **chris-code:using-git-worktrees** - Ensures isolated workspace
- **chris-code:lean-plan** - Creates the plan this skill executes
- **chris-code:finishing-a-development-branch** - Complete development after all tasks
- **`*-quality-reviewer` agents** - Per-task quality + bug review, auto-dispatched by file type
- **`*-review-lite` agents** - Commit gates + final full-diff review, auto-dispatched by file type
