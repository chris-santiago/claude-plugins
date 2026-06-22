---
name: subagent-driven-development
description: Use when executing implementation plans with independent tasks in the current session
---

# Subagent-Driven Development

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Core principle:** Specialized coder agent per task → spec review → quality review → commit gate. Fresh context per task, staged parallelism for independent tasks.

**Continuous execution:** Do not pause between tasks. The only reasons to stop: unresolvable BLOCKED status, ambiguity that prevents progress, or all tasks complete.

**Every task gets every gate.** The three-stage review (spec → quality → review-lite) applies to ALL tasks — not just the first one. You will feel pressure to skip gates on later tasks because "the pattern is established" or "this one is simple." That impulse is the exact failure mode this rule prevents. Task 5 gets the same gates as Task 1. No exceptions.

## Pre-Flight Plan Review

Before dispatching Task 1, load the progress ledger (see Durable Progress) and resume at the first task not marked complete. Then read the plan once and check for:

- **Internal conflicts** — tasks that contradict each other or the plan's Constraints.
- **Plan-mandated defects** — anything the plan asks for that a reviewer would flag (a test that asserts nothing, verbatim duplication, a swallowed error).

Present everything you find to the user as one batched question, each finding beside the plan text that mandates it, asking which governs. If the scan is clean, proceed without comment. Do not interrupt per-discovery mid-run.

## The Process

```mermaid
flowchart TB
    subgraph Per Task
        coder["Dispatch *-coder agent"]
        questions{"Coder asks questions?"}
        answer["Answer questions, provide context"]
        implement["Coder implements, tests, self-reviews"]
        spec_rev["Dispatch spec reviewer"]
        spec_ok{"Spec compliant?"}
        fix_spec["Coder fixes spec gaps"]
        quality_rev["Dispatch *-quality-reviewer agent"]
        quality_ok{"Quality approved?"}
        fix_quality["Coder fixes quality issues"]
        commit_gate["Per-task commit gate: *-review-lite"]
        done["Mark task complete<br/>(TodoWrite + ledger)"]
    end

    read["Read plan + progress ledger,<br/>pre-flight conflict scan,<br/>extract tasks, map footprints, group into stages"]
    more_tasks{"More tasks in stage?"}
    more_stages{"More stages?"}
    final_gate["Final gate: scripts/review-package merge-base..HEAD<br/>→ *-review-lite reads the package file"]
    finish["chris-code:finishing-a-development-branch"]:::finish

    read --> coder
    coder --> questions
    questions -->|yes| answer
    answer --> coder
    questions -->|no| implement
    implement --> spec_rev
    spec_rev --> spec_ok
    spec_ok -->|no| fix_spec
    fix_spec -->|re-review| spec_rev
    spec_ok -->|yes| quality_rev
    quality_rev --> quality_ok
    quality_ok -->|no| fix_quality
    fix_quality -->|re-review| quality_rev
    quality_ok -->|yes| commit_gate
    commit_gate --> done
    done --> more_tasks
    more_tasks -->|"yes (parallel within stage)"| coder
    more_tasks -->|no| more_stages
    more_stages -->|"yes (next stage)"| coder
    more_stages -->|no| final_gate
    final_gate --> finish

    classDef finish fill:#90EE90,stroke:#333
```

## Agent Selection

### Coder Agents (exclusive — one coder per task)

Dispatch the most specific `*-coder` agent for the task's file types:

1. Check which file types the task will touch
2. Match against available `*-coder` agents by `scope.extensions`
3. If multiple match the same extension, resolve via `scope.require_dependencies` — most specific wins (e.g., `pytorch-coder` over `python-coder` when project depends on torch)
4. Concrete tiebreaker: if the code subclasses `nn.Module`, manipulates `torch.Tensor` shapes/devices, or implements a training-pipeline component (loss, callback, optimizer, scheduler, metric), dispatch `pytorch-coder`. Reserve `python-coder` for non-torch code (CLI, data I/O, config utils).
5. If no specific coder matches, fall back to a general-purpose agent

Only one coder agent writes the code. The winning coder must be self-contained (includes both domain-specific and general language patterns).

### Review Agents (additive — all matching agents fire)

Unlike coders, `*-quality-reviewer` and `*-review-lite` agents are **additive**: all agents matching the file extensions fire on the same diff. In a PyTorch project, `.py` files get both `python-quality-reviewer` (general Python patterns) and `pytorch-quality-reviewer` (Lightning conventions, training correctness). If findings conflict, the more specific agent's guidance takes precedence.

### Model Selection

Use the least powerful model that can handle each role. **Announce the model and agent on every dispatch:**
- "Dispatching haiku python-coder agent for Task 3 (add utility function)"
- "Dispatching sonnet rust-coder agent for Task 5 (refactor pipeline)"
- "Dispatching opus general agent for final cross-cutting review"

| Model | When |
|-------|------|
| **Haiku** | Isolated functions, clear spec, 1–2 files, mechanical changes |
| **Sonnet** | Multi-file coordination, integration concerns, pattern matching |
| **Opus** | Architecture decisions, design judgment, broad codebase understanding, reviews |

## Task Scheduling

Use **staged parallelism**, not flat sequential or flat parallel dispatch.

1. **Map file footprints:** Before dispatching, identify every source file and test file each task will touch
2. **Group into stages:** Tasks within a stage must have zero file overlap (source AND test files). Tasks that share any file go in separate stages.
3. **Within a stage:** Dispatch subagents in parallel — they touch disjoint files and cannot conflict
4. **Between stages:** Wait for all tasks in the current stage to complete and pass review before starting the next stage

Common serialization triggers:
- Two tasks both modify the same test file (e.g., `conftest.py`, `test_utils.py`)
- Two tasks both touch a shared module (e.g., `models.py`, `lib.rs`)
- A later task depends on types/interfaces introduced by an earlier task

When in doubt, serialize. The cost of a conflict is higher than the cost of waiting.

## File Handoffs

Anything you paste into a dispatch — and anything a subagent prints back — stays resident in your context for the rest of the session. Hand artifacts over as files instead, all under `$(git rev-parse --git-path sdd)` (`.git/sdd/`, per-worktree and uncommitted):

- **Task brief:** the brief is a *reference sheet*, not a restatement of the spec. Run `scripts/task-brief PLAN_FILE N` to extract the plan's task entry (its actions, `Consumes:` pointers, and spec §-references) to a file, then add any cross-task notes only you hold (next bullet). The dispatch carries only: (1) one line on where this task fits; (2) the brief path, introduced as "read this first — your task and the sections to read"; (3) the spec path, where the coder reads the referenced §§; for a contract built by an earlier task, name the file or spec § rather than restating its signature; (4) the Global Constraints copied verbatim; (5) the report-file path.
- **Cross-task notes (orchestrator-only, terse):** the one thing the coder cannot recover by reading the spec and the repo is cross-task context. Add it to the brief as pointers and decisions, never as dereferenced spec content: a dependency contract (`built in Task M → path`), a conflict adjudication (`finding §5 governs the extent→band call`), or a code entry point (the landing symbol, plus any new wire-key value). Grounding beyond the entry point is the coder's job (its first step is to read the files it will touch), so point at the entry and let it trace the chain. Keep this to a few lines; if it grows, the requirement belongs in the spec, or the conflict belonged in the Pre-Flight Plan Review.
- **Report file:** name it after the brief (`task-N-brief.md` → `task-N-report.md`). The implementer writes its full report there and returns only status, the changed-file list, a one-line test summary, and concerns.
- **Reviewer inputs:** spec-reviewer and `*-quality-reviewer` agents get the brief path, the report path, the changed-file list, and the verbatim Constraints, and read the actual changed files. Do not paste diffs.
- **Never** paste task text, prior-task summaries, or diffs into a dispatch or into your own context. A fresh subagent needs its brief, the interfaces it touches, and the constraints — nothing else.

## Global Constraints

Copy the plan's Constraints section verbatim (exact values, formats, and stated relationships between components) into every implementer and reviewer dispatch. It is the reviewer's attention lens for what THIS project demands; the process rules already live in the agents and templates.

## Constructing Reviewer Dispatches

- **Never pre-judge.** Do not instruct a reviewer to ignore, not-flag, or pre-rate a finding. If your dispatch contains "do not flag," "at most Minor," or "the plan chose," stop — you are pre-judging to spare yourself a review loop. Let the reviewer raise it and adjudicate it in the loop.
- **Pass the `*-review-lite` cycle counter.** When a commit-gate `*-review-lite` returns block/escalate, the coder fixes and you re-dispatch the same agent on the same diff. Pass `cycle: N` in that dispatch — `1` on the first try, incremented on each re-review. At `cycle >= 3` the agent escalates to break a stuck fix loop; omit the counter and that backstop never fires (the agent assumes `cycle: 1` every time).
- **Never narrow the mandate.** Do not reframe a reviewer's job to a subset of its remit ("just check for bugs," "only look at the parser," "skip the tests"). Each reviewer's system prompt defines its full scope — hand it the inputs and constraints, not a reduced charter. Under-cueing the scope is as corrosive as suppressing a finding: a design reviewer told to "look for bugs" stops reviewing design.
- **Do not** ask a reviewer to re-run tests the implementer already ran, or add open-ended directives ("check all uses") without a concrete, task-specific reason.
- **Plan-mandated defects are the user's call.** If a finding conflicts with what the plan mandates, present the finding and the plan text and ask which governs. Do not dismiss it because the plan mandated it, and do not dispatch a fix that contradicts the plan without asking.

## Handling ⚠️ Items

The spec-reviewer may return "⚠️ Cannot verify from diff" items — requirements that live in unchanged code or span tasks. These do not block the rest of the review, but resolve each one yourself before marking the task complete: you hold the plan and cross-task context the reviewer lacks. A confirmed gap is a failed spec review — send it back to the coder and re-review.

## Durable Progress

Conversation memory does not survive compaction; a controller that loses its place can re-dispatch finished tasks. Track progress in a ledger, not only in TodoWrite.

- At start, run `scripts/progress read`. Tasks listed complete are DONE — do not re-dispatch them; resume at the first task not listed. If the ledger belongs to a different branch, `scripts/progress clear` first.
- When a task's reviews come back clean, run `scripts/progress append "Task N: complete (commits <base7>..<head7>, review clean)"` alongside marking it done in TodoWrite. TodoWrite is your live view; the ledger is the durable recovery map.
- After compaction, rebuild the TodoWrite list from the ledger, and trust the ledger and `git log` over your own recollection.

## Handling Implementer Status

Implementer subagents report one of four statuses. Handle each appropriately:

**DONE:** Proceed to spec compliance review.

**DONE_WITH_CONCERNS:** The implementer completed the work but flagged doubts. Read the concerns before proceeding. If the concerns are about correctness or scope, address them before review. If they're observations (e.g., "this file is getting large"), note them and proceed to review.

**NEEDS_CONTEXT:** The implementer needs information that wasn't provided. Provide the missing context and re-dispatch.

**BLOCKED:** The implementer cannot complete the task. Assess the blocker:
1. If it's a context problem, provide more context and re-dispatch with the same model
2. If the task requires more reasoning, re-dispatch with a more capable model
3. If the task is too large, break it into smaller pieces
4. If the plan itself is wrong, escalate to the human

**Never** ignore an escalation or force the same model to retry without changes. If the implementer said it's stuck, something needs to change.

## Final Gate

After the last stage, run one review over the whole change. The per-commit gates each saw a single commit in isolation, so cross-commit idiom drift — a helper duplicated across two tasks, an inconsistency between Task 1 and Task 5 — can pass every per-commit gate and still land.

The task commits are already in, so `git diff --cached` is empty and `*-review-lite` cannot use its default staged-diff path. Hand it the whole-change diff as a file instead:

1. `BASE=$(git merge-base HEAD <base-branch>)`, `HEAD=$(git rev-parse HEAD)`.
2. Run `scripts/review-package "$BASE" "$HEAD"` — it writes the commit list, stat, and full multi-commit diff to a file and prints the path (the diff never enters your context).
3. Dispatch each matching `*-review-lite` agent with that package-file path. The agent reads the package and reviews the whole-change diff, not `--cached`.

Handle block/escalate exactly as at a per-commit gate (including the `cycle` counter on re-dispatch).

## Prompt Templates

- `./implementer-prompt.md` - Dispatch implementer subagent (used when no `*-coder` agent matches)
- `./spec-reviewer-prompt.md` - Dispatch spec compliance reviewer subagent

Quality review is handled by `*-quality-reviewer` agents (e.g., `python-quality-reviewer`, `rust-quality-reviewer`), dispatched by scope matching — no prompt template needed.

All dispatches use file handoffs (see File Handoffs): pass brief, report, and constraint content as file paths plus verbatim Constraints, never pasted task text or diffs.

## Example Workflow

```
[Read plan: .claude/output/plans/feature-plan.md]
[Extract 5 tasks, map file footprints, group into 3 stages]
[Stage 1: Tasks 1,2 (disjoint files) | Stage 2: Task 3 | Stage 3: Tasks 4,5 (disjoint)]

Stage 1 — dispatching 2 tasks in parallel:
  "Dispatching sonnet python-coder agent for Task 1 (add CLI hook)"
  "Dispatching haiku python-coder agent for Task 2 (add utility function)"

  Task 1: coder completes → spec reviewer ✅ → quality reviewer ❌ (S3: hidden side effect
    in helper) → coder fixes → quality reviewer ✅ → python-review-lite ✅ → mark complete
  Task 2: coder completes → spec reviewer ✅ → quality reviewer ✅ → python-review-lite ✅
    → mark complete

Stage 2:
  "Dispatching sonnet python-coder agent for Task 3 (refactor shared module)"
  [Task 3 shares conftest.py with Tasks 1,2 — must wait for Stage 1]

  Task 3: coder completes → reviews pass → commit gate → mark complete

Stage 3 — dispatching 2 tasks in parallel:
  "Dispatching sonnet rust-coder agent for Task 4 (add FFI binding)"
  "Dispatching haiku python-coder agent for Task 5 (add Python wrapper)"

  [Both complete → reviews → commit gates (rust-review-lite + python-review-lite) → mark complete]

[Final gate: scripts/review-package base..HEAD → python-review-lite + rust-review-lite read the package file]
[chris-code:finishing-a-development-branch]
```

## Red Flags

- Never start implementation on main/master without explicit user consent
- Never skip reviews (spec compliance OR quality) or proceed with unfixed issues
- Never dispatch subagents in parallel when their file footprints overlap
- Never paste task text or diffs into a dispatch or your own context — hand the task brief as a file (`scripts/task-brief`), and never hand a subagent the whole plan file
- Never coach a reviewer to suppress, soften, or pre-rate a finding
- Never start quality review before spec compliance passes
- Never mark a task complete with an unresolved ⚠️ item
- Never re-dispatch a task the ledger lists as complete
- Never move to next task while any review has open issues
- If a reviewer finds issues: coder fixes → reviewer re-reviews → repeat until approved
- If a subagent is blocked: provide more context, upgrade model, or break the task apart — never force retry without changes

## Integration

**Required workflow skills:**
- **chris-code:using-git-worktrees** - Ensures isolated workspace
- **chris-code:lean-plan** - Creates the plan this skill executes
- **chris-code:requesting-code-review** - Code review template for reviewer subagents
- **chris-code:finishing-a-development-branch** - Complete development after all tasks

**Agents:**
- **`*-coder` agents** - Specialized implementers, auto-dispatched by file type
- **`*-quality-reviewer` agents** - Design quality + bug detection review, auto-dispatched by file type
- **`*-review-lite` agents** - Commit gates (idiom + lint), auto-dispatched by file type

**Subagents should use:**
- **chris-code:test-driven-development** - Subagents follow TDD for each task

**Alternative workflow:**
- **chris-code:executing-plans** - Use for inline execution without subagents
