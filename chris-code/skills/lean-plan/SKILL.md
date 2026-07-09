---
name: lean-plan
description: Use when you have a spec or requirements for a multi-step task, before touching code — produces a thin execution handoff instead of a verbose implementation guide
---

# Lean Plan

## Overview

Write an implementation plan as a thin execution handoff. The plan tells the executor WHAT to do and WHERE — not HOW. If a design spec already documents the requirements, reference the spec instead of restating it.

**Announce at start:** "I'm using the lean-plan skill to create the implementation plan."

**Save plans to:** `.claude/output/plans/YYYY-MM-DD-<feature-name>-plan.md`

## Primary Principle

The plan is a thin execution handoff, not a second design spec and not a shadow implementation. Implementation agents ignore pasted code blocks and write their own — so don't waste tokens writing code they'll discard.

## Scope Check

If the spec covers multiple independent subsystems, suggest breaking into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## Before Writing

1. Read the design spec (and any referenced docs) end to end
2. Identify which details are already well-documented in the spec vs. which need to be stated in the plan
3. Map out which files will be created or modified

## Plan Format

Every plan MUST use this structure. No other sections. No prose between sections.

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

One sentence describing the required change.

## 2. Spec references

- `path/to/design-spec.md §2.3 Component contract`
- `path/to/api-spec.md §5 Error handling`

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Create | `exact/path/to/file.py` | short reason |
| Modify | `exact/path/to/existing.py` | short reason |
| Test | `tests/exact/path/to/test.py` | short reason |

## 4. Constraints

- Non-negotiable invariants
- Backward-compat requirements
- Performance, security, architecture constraints
- Repeat a constraint here even if it appears in the spec when violating it would be costly or easy to miss
- State each constraint self-contained, with exact values, so the orchestrator can copy it verbatim into every implementer and reviewer dispatch

## 5. Tasks

### Task 1: [Name]
- Consumes: <contract> from <spec §N, or built in Task M → `path`> — a pointer, never a restated signature; omit if the task stands alone
- [ ] Concrete action (reference spec §N for requirements)
- [ ] Concrete action
- [ ] Verify: `exact command to run`

### Task 2: [Name]
...

## 6. Acceptance checks

- `uv run pytest tests/path/ -v` — all pass
- `cargo test` — all pass
- Observable success criteria

## 7. Open questions

- Only unresolved items that could materially change implementation
- (Omit section if none)
```

## Compression Rules

**Remove:** explanatory prose, commentary, motivation, repeated rationale, code snippets (unless essential for an exact contract, schema, or signature), pseudo-code that restates the implementation, text inferable from the repo or spec.

**Prefer:** bullets over paragraphs, exact spec references over repeated detail, short operational language over narration.

**Preserve:** original intent and task sequencing, all requirements / edge cases / acceptance criteria, safety-critical details even if they also appear in the spec.

**Do not:** invent missing details, broaden scope.

**Code blocks — keep only if** removing one would create ambiguity about a required interface, exact command, or schema shape. Otherwise delete. Design decisions (strategy choices, routing/ownership, scoping, configuration contracts, ordering constraints) belong as prose bullets in Constraints — never inside code blocks.

**Spec references — replace duplicated detail** with a direct section reference. Keep the detail in the plan anyway if it's safety-critical, easy to miss, or likely forgotten during implementation.

## Word Efficiency

Every line must be load-bearing: a contract, an action, a path, a constraint, or an acceptance check the implementer cannot infer from the spec or the repo. Length is a smell, not a limit. A plan much longer than its task count usually means restatement, so investigate and cut. Never pad to fill a budget or truncate to fit one.

## Self-Review

After writing, check against the spec:

1. **Spec coverage:** Can you point to a task for each spec requirement? List any gaps.
2. **Bloat scan:** Any prose that restates the spec? Any code blocks an executor would rewrite? Cut them.
3. **Name consistency:** Do types, signatures, and paths used in later tasks match earlier tasks?
4. **Verify scope vs. shared contracts:** Does any task change a *shared contract* (a test file several tasks edit, such as a central exclusions list or fixtures module; an enum; an allow/deny list; a public signature consumed elsewhere)? If so, its `Verify:` and its slice of the acceptance checks must run the **full suite, or grep every assertion of that contract**, not just a local `-k` subset scoped to the task's own module. A narrow filter passes green while hiding orphaned failures in sibling files: the assertion a *different* task already wrote against the contract you just flipped. When in doubt, a shared-contract task verifies suite-wide.
5. **Repeated shapes are contracts:** Do 3+ tasks perform the same operation (the same call pair, construction, or dispatch block)? Name the shared helper as a contract with an owner — one task builds it, every later consumer carries a `Consumes:` pointer to it. A shape left inline in the plan becomes N verbatim copies at execution: coders are scope-disciplined and will not hoist it for you.

Fix issues inline, then move on.

## Execution Handoff

After saving the plan, offer:

**"Plan saved to `.claude/output/plans/<filename>.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute in this session with checkpoints

**Which approach?"**

- **Subagent-Driven:** REQUIRED SUB-SKILL: `chris-code:subagent-driven-development`
- **Inline:** REQUIRED SUB-SKILL: `chris-code:executing-plans`
