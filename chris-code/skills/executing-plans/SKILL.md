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
4. If no concerns: check the progress ledger (`subagent-driven-development/scripts/progress read`) — tasks listed complete are DONE, so rebuild TodoWrite from the ledger and resume at the first unlisted task; otherwise create TodoWrite and proceed

### Step 2: Execute Tasks

For each task:
1. Mark as in_progress
2. Follow each step exactly (plan has bite-sized steps)
3. Run verifications as specified
4. Dispatch **all matching** `*-quality-reviewer` agents (additive — e.g., both `python-quality-reviewer` and `pytorch-quality-reviewer` fire on `.py` and `.ipynb` files in a PyTorch project). If any returns REVISE: fix issues and re-dispatch until all APPROVED.
5. Mark as completed in TodoWrite, and append to the ledger: `subagent-driven-development/scripts/progress append "Task N: complete (commits <base7>..<head7>, review clean)"`

### Step 3: Commit Gate

Before each commit (end of plan or mid-plan commit points):

1. **Collect candidates:** Check staged file extensions → match **all** `*-review-lite` agents by `scope.extensions` (additive, not exclusive)
2. **Dispatch** all matching agents against the staged diff
4. If any agent returns **block**: fix the issue before committing
5. If any agent returns **escalate**: stop and surface to the user

Only dispatch when there are staged changes to review.

### Step 4: Final Review

After all tasks complete: dispatch `*-review-lite` agents against the full diff (base..HEAD) to catch cross-task idiom drift and inconsistencies missed by per-commit gates.

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
