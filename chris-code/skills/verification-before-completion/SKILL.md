---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - runs concrete verification steps and confirms output before making any success claims
---

# Verification Before Completion

## Overview

Run concrete verification steps before claiming any work is done. Evidence before assertions, always.

**Core principle:** No completion claims without fresh verification evidence.

**Announce at start:** "I'm using the verification-before-completion skill to verify this work."

## The Gate

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What commands and checks prove this claim?
2. RUN: Execute each step below
3. READ: Full output, check exit codes, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim
```

## Verification Steps

### Step 1: Tests

Run the project's full test suite. Not a subset. Not "the tests I think are relevant."

```bash
# Use the project's test runner
pytest / cargo test / npm test / go test ./...
```

**Must see:** Zero failures, clean output. If tests fail, fix them before proceeding — do not continue to Step 2.

### Step 2: Lints

Run the project's linter. Not optional even if tests pass.

```bash
# Use the project's linter
ruff check / cargo clippy -- -D warnings / eslint / golangci-lint run
```

**Must see:** Zero errors, zero warnings (or only pre-existing warnings). Fix lint issues before proceeding.

### Step 3: Full Review

Dispatch **all matching** `*-design-reviewer` agents based on file types changed (additive — e.g., both `python-design-reviewer` and `rust-design-reviewer` fire when a change spans `.py`/`.ipynb` and `.rs`). Match by `scope.extensions`. If findings conflict, the more domain-specific review takes precedence.

These read-only agents are the senior-level pass — they catch design drift, API cohesion issues, and structural problems that review-lite and quality-reviewer miss, and they run in an isolated context so the architecture analysis doesn't pollute the main window. This is the heavyweight gate before integration. (For hands-on refactoring outside the gate, invoke the `python-review` / `rust-review` skills directly.)

Dispatch each matching agent with this framing — design/cohesion is the mandate, not a bug hunt:

```
Role: senior design/cohesion review of the whole change before integration.
This is NOT a bug hunt. Report architectural cohesion, API design, module
boundaries, and structural drift per your output format (Architecture map,
Findings, Recommended refactors, What still feels wrong). Correctness bugs are
in scope only as a subset (S4–S5), not the focus.

Inputs:
  - Changed files: <git diff --name-only <merge-base>..HEAD>
  - Spec/plan: <paths>
  - Project constraints: <CLAUDE.md / plan Constraints, verbatim>
```

Pass it the inputs and constraints, never a narrowed scope. Do not tell the agent to skip a concern or pre-rate a severity — its findings and verdict are its own.

**Must see:** Verdict PASS from every dispatched agent (no S3+ findings). If any returns CONCERNS, address the findings and re-run.

### Step 4: Requirements Check

Re-read the plan or spec that drove this work. For each requirement:

1. Can you point to the code that implements it?
2. Can you point to a test that verifies it?
3. Is there anything in the spec that was not implemented?
4. Is there anything implemented that was not in the spec?

**Must see:** Every requirement covered. If gaps exist, report them — do not claim completion.

### Step 5: Intent Re-check

Steps 1–4 all compare the work to the spec (tests, lint, design cohesion, spec conformance). None of them asks the one question the spec cannot answer: **does the shipped behavior do what the user originally asked for?** A build can pass every spec gate while the spec itself drifted from the ask. This step closes that seam.

Dispatch the read-only **`intent-reviewer`** agent. It is **spec-blind** — give it the frozen intent ledger and the running system, never the spec, plan, or task briefs:

```
Inputs (exactly two):
  - Intent ledger: <.claude/output/intent/YYYY-MM-DD-<topic>-intent.md>
    (for a bug remediation, the issue text IS the ledger — pass it instead)
  - The running system (the agent inspects and exercises it read-only)

Do NOT pass the spec, the plan, the design doc, or the implementer's report —
the agent's independence depends on judging behavior against the ask alone.
```

If no intent ledger exists and no original-ask statement is recoverable (a change that never had one), note that explicitly and skip this step — do not fabricate a ledger after the fact.

**Must see:** Verdict PASS (no `not-met` statements). A `not-met` is a real gap between behavior and the ask — fix it (or, if the ledger itself is wrong, that is a user decision). Resolve every `can't-tell` before claiming completion.

## After Verification Passes

All five steps green → you may claim completion. Then invoke `chris-code:finishing-a-development-branch` for the integration workflow (merge/PR/keep/discard).

## What These Gates Do and Don't Prove

Be honest about what a green pipeline buys. These steps are not independent guarantees stacked into a proof. Only about two axes are genuinely independent: the **linter** (a deterministic, non-LLM check) and **conformance** (does the behavior match the spec/intent). The design and quality re-judgments are correlated LLM passes — they share a model, a training distribution, and often a framing, so they tend to miss the same things together.

- More passes raise **recall** (more issues surfaced), not **residual assurance** — a clean run means "nothing these lenses caught," not "nothing is wrong."
- **Diversity beats quantity.** A check that fails *differently* — a deterministic linter, a spec-blind behavior check, an actual failing test, a human read — adds more than another same-model re-review of the same diff. The intent re-check (Step 5) earns its place by being spec-*blind*: it decorrelates from every spec-anchored step above it.
- No gate here verifies the **spec itself is right**. Conformance is not correctness; that judgment stays with the user.

Run the gates — they catch real drift. Just don't read green as proof of its absence.

## Rationalizations — All Mean "Run the Verification"

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the commands |
| "I'm confident" | Confidence ≠ evidence |
| "Linter passed" | Linter ≠ tests ≠ review |
| "Agent said success" | Verify independently |
| "Partial check is enough" | Partial proves nothing |

## Integration

**This skill is a prerequisite for:**
- **chris-code:finishing-a-development-branch** — do not invoke until verification passes

**This skill dispatches:**
- **`*-design-reviewer` agents** — read-only senior-level review, auto-dispatched by scope (Step 3)
- **`intent-reviewer`** — read-only, spec-blind behavior-vs-intent re-check (Step 5)

**Related skills:**
- **chris-code:test-driven-development** — TDD ensures tests exist; this skill ensures they pass
- **chris-code:regression-test** — ensures bug fixes have regression coverage before verification
