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

Dispatch **all matching** `*-review` skills based on file types changed (additive — e.g., both `python-review` and a future `pytorch-review` fire on `.py` and `.ipynb` files in a PyTorch project). Match by `scope.extensions` in the skill frontmatter. If findings conflict, the more domain-specific review takes precedence.

These are the senior-level refactoring reviews — they catch design drift, API cohesion issues, and structural problems that review-lite and quality-reviewer miss. This is the heavyweight pass before integration.

**Must see:** No critical or important issues. If issues are found, address them and re-run the review.

### Step 4: Requirements Check

Re-read the plan or spec that drove this work. For each requirement:

1. Can you point to the code that implements it?
2. Can you point to a test that verifies it?
3. Is there anything in the spec that was not implemented?
4. Is there anything implemented that was not in the spec?

**Must see:** Every requirement covered. If gaps exist, report them — do not claim completion.

## After Verification Passes

All four steps green → you may claim completion. Then invoke `chris-code:finishing-a-development-branch` for the integration workflow (merge/PR/keep/discard).

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
- **`*-review` skills** — full senior-level review, auto-dispatched by scope (Step 3)

**Related skills:**
- **chris-code:test-driven-development** — TDD ensures tests exist; this skill ensures they pass
- **chris-code:regression-test** — ensures bug fixes have regression coverage before verification
