# Getting started

This tutorial takes a single feature from idea to merged change using the full chris-code pipeline. By the end you'll have watched the design → spec → plan → execute → verify → finish flow run once, so the rest of the docs have something concrete to refer back to.

## Prerequisites

- Claude Code installed and working.
- chris-code enabled (see [Install](../index.md#install)).
- A git repository to work in — ideally a small Python or Rust project, since the coder and review agents are language-scoped.

## Step 1: Start with intent, not code

In a chris-code-enabled session, describe what you want to build, or invoke the skill directly:

```
/brainstorming
```

`brainstorming` is a **hard gate**: it will not let implementation begin until a design exists and you've approved it. Expect it to ask clarifying questions **one at a time**, propose two or three approaches with trade-offs, and present a design in sections. Answer the questions; approve or redirect the design.

You will see it produce a small **intent ledger** — up to seven observable acceptance statements, in your words — and ask you to confirm them. This is the frozen record of what you actually asked for. Confirm it; you don't write it, you just approve it.

## Step 2: Watch the spec and plan appear

After you approve the design, brainstorming hands off to:

- **`lean-spec`** — writes a contracts-only design spec to `.claude/output/specs/`. It captures invariants and interfaces, *not* implementation steps.
- **`lean-plan`** — writes a thin execution handoff (what and where, no code) to `.claude/output/plans/`.

Read the spec when prompted. It should be short; if it reads like a coding walkthrough, that's a smell the skill is designed to avoid.

## Step 3: Let execution dispatch the work

`subagent-driven-development` takes the plan and, per task:

1. dispatches the matching **coder agent** (`python-coder` / `rust-coder` / `pytorch-coder`) with a brief that carries the task's *why*,
2. runs **spec review** (did it build what was asked?),
3. runs **quality review** (is the code sound?),
4. runs the **commit-lite gate** (idioms + linter) before each commit.

You'll see each dispatch announced with its model and agent. Independent tasks run in parallel; tasks that touch the same files are serialized automatically.

## Step 4: Verify before "done"

When all tasks are in, `verification-before-completion` runs a five-step gate:

1. Tests — full suite, zero failures
2. Lints — zero errors/warnings
3. Full review — the senior `*-design-reviewer` agents
4. Requirements — every spec item traced
5. **Intent re-check** — a spec-blind `intent-reviewer` compares the shipped behavior to your frozen intent ledger

A green run is not "nothing to do" — read any findings it surfaces.

## Step 5: Finish the branch

`finishing-a-development-branch` presents your integration options — merge, open a PR, keep the branch, or discard — and handles worktree cleanup.

## What you've done

You've taken one change through the entire pipeline: intent was settled before code, the spec stayed lean, the work was dispatched to focused agents and reviewed at every gate, and the shipped behavior was checked back against your original ask before anything was called done.

Next: the [how-to guides](../how-to/index.md) show how to enter this machinery for specific tasks — a bug fix, a refactor, a review — without always starting from a blank design.
