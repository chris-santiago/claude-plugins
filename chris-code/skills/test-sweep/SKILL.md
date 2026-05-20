---
name: test-sweep
description: >
  Iterative combinatorial test-and-fix campaign for any project. Writes systematic test modules
  targeting cross-cutting dimensions of the API surface, runs them, fixes all failures via TDD,
  then uses failure patterns to derive the next test suite. Repeats for N rounds or until
  convergence. Fully autonomous except for design-decision pauses. Use when the user says
  /test-sweep, "sweep for bugs", "systematic test campaign", "find gaps across the API surface",
  or wants a multi-round test-driven quality pass.
---

# Test Sweep

Iterative combinatorial test-and-fix campaign. Each round targets a new cross-cutting
dimension of the project's API, writes a parametrized test module, fixes all surfaced bugs,
and uses the failure patterns to derive the next round's target.

## Usage

```
/test-sweep [N]
```

N = max rounds (default 3). Stops early if a round produces zero new failures.

---

## Philosophy

- **Fixes must be robust and cohesive** — no band-aids, no isolated patches that ignore
  the surrounding design. Every fix must respect the architecture.
- **End-user experience first** — will this behavior surprise someone using the API?
- **Pause on ambiguity** — when a fix could go multiple directions with different UX
  tradeoffs, stop and present options to the user before implementing.

---

## Core Loop

For each round (up to N):

### 1. Select dimension

On the first round, discover cross-cutting test dimensions by exploring the project:

- Read the project structure, public API surface, and existing test files.
- Identify dimensions that cut across multiple modules: input types x operations, config
  options x features, data shapes x transforms, error conditions x entry points, etc.
- Build a seed queue ordered by expected bug yield (broadest coverage first).

Pick the next untested dimension from the queue. Skip any dimension whose test file
already exists and passes.

### 2. Write test modules

Dispatch coding agents to write parametrized test files following the project's
established test patterns:

- Match the project's test framework, fixtures, and assertion style.
- Use parametrize/table-driven patterns to maximize coverage per file.
- Target edge cases: empty inputs, single-element, nulls/NaN, type boundaries, etc.
- Keep each module focused on one dimension.

For multi-language projects, dispatch language-specific agents in parallel.

Do not write test files directly in the orchestrator — use coding agents.

### 3. Collect failures

Run the test module. Categorize each failure as:
- **Test-design issue** — wrong API call, bad data shape, invalid expectation
- **Real bug** — code silently drops a feature, crashes, or produces wrong output
- **Design decision** — multiple valid fixes with different UX implications

### 4. Fix

- **Test-design issues**: dispatch to a coding agent to fix the test file.
- **Design decisions**: pause, present options with tradeoffs, get user choice.
- **Real bugs**: dispatch to the appropriate coding agent with clear boundaries.

All fixes must consider:
- Does this change the public API contract?
- Is the fix cohesive with the surrounding subsystem?
- Would a user be surprised by this behavior?

### 5. Verify green

Re-run the test module, then the full project test suite for regressions. All must
pass before proceeding.

### 6. Review-lite gate

Stage changes. Review the diff for quality. Act on verdict:
- **clean** — proceed
- **block** — fix findings, re-stage, re-review
- **escalate** — surface to user, halt round

### 7. Commit

Commit test module + fixes as a single commit per round:
```
test+fix(sweep-N): <dimension name> — M gaps found, M fixed
```

### 8. Derive follow-up dimensions

Analyze the round's failures:
- If 2+ failures shared a subsystem root cause, generate a targeted follow-up
  dimension scoped to that subsystem.
- Append derived dimensions to the queue (they'll be picked up in later rounds).

### 9. Terminate or continue

- If round produced 0 new failures: stop, report convergence.
- If round N reached: stop, report summary.
- Otherwise: next round.

---

## Pause Conditions

The skill halts and asks the user when:
- A fix requires choosing between multiple valid UX behaviors
- Review returns `block` or `escalate`
- A fix would change existing public API behavior
- A failure reveals a fundamental architecture issue (not a local bug)

---

## Output

After all rounds complete, write `.claude/output/test-sweep/TEST_SWEEP_REPORT.md` (gitignored) with:
- Per-round summary: dimension, tests written, failures found, fixes applied
- Design decisions made (with rationale)
- Derived dimensions discovered (queued for next invocation)
- Remaining xfails with dated reasons

---

## Guardrails

- Never xfail without a dated reason AND a follow-up dimension queued
- All fixes go through review before commit
- All source writes go through coding agents — the orchestrator reads, analyzes, and dispatches but never edits source directly
- Skip dimensions whose test files already exist and pass
- Do not modify existing passing tests (only add new ones or fix test-design issues)
- Maximum 50 test cases per module (keep parametrize matrices bounded)
