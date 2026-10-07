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

The steps are numbered for reference, not run in sequence: Steps 1–2 run first, then Steps 3, 5, and 6 are dispatched together, with Step 4 done alongside them, as one close round (see *The Close Round*).

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
  - Report path: <$STORE/design-review-<agent-name>.md>
```

Resolve `$STORE` once via `python3 "$SDD_SCRIPTS/ledger.py" store-dir` (the same authority subagent-driven-development uses). `SDD_SCRIPTS` is the absolute path of the `subagent-driven-development` skill's `scripts/` directory at the plugin install location. Reuse it if SDD already pinned it this session. Otherwise derive it from this skill's own "Base directory for this skill" line: `<that directory>/../subagent-driven-development/scripts`, since both skills ship in the same plugin. Use it even when SDD did not run: `store-dir` works in any git repo. The agent writes its full report to that path and returns only `<agent-name> — PASS | CONCERNS — report: <path>`, so the architecture analysis stays out of your context until triage. At triage, read every report, not only the CONCERNS ones: a PASS can still carry S1–S2 findings. On a re-run after remediation, pass the *same* report path: the agent reads its prior report there and judges whether the findings were addressed rather than re-deriving them.

Pass it the inputs and constraints, never a narrowed scope. Do not tell the agent to skip a concern or pre-rate a severity — its findings and verdict are its own.

**Must see:** Verdict PASS from every dispatched agent (no S3+ findings), or every CONCERNS finding resolved through the close round. A CONCERNS verdict is not fixed here: its findings go to the close round's single triage (see *The Close Round*).

### Step 4: Requirements Check

Re-read the plan or spec that drove this work. With no spec (a bug remediation or a single `coherent-change` build), the issue text and the decision doc are the requirements. In round 2, add the close-gate decision doc and remediation plan. For each requirement:

1. Can you point to the code that implements it?
2. Can you point to a test that verifies it?
3. Is there anything in the spec that was not implemented?
4. Is there anything implemented that was not in the spec?

**Must see:** Every requirement covered. A gap does not get claimed as complete: it joins the close round's triage alongside the gate findings.

### Step 5: Intent Re-check

Steps 1–4 all compare the work to the spec (tests, lint, design cohesion, spec conformance). None of them asks the one question the spec cannot answer: **does the shipped behavior do what the user originally asked for?** A build can pass every spec gate while the spec itself drifted from the ask. This step closes that seam.

Dispatch the read-only **`intent-reviewer`** agent. It is **spec-blind** — give it the frozen intent ledger and the running system, never the spec, plan, or task briefs:

```
Inputs (exactly two):
  - Intent ledger: <.claude/output/intent/YYYY-MM-DD-<topic>-intent.md>
    (for a bug remediation, the issue text IS the ledger — pass it instead)
  - The running system (the agent inspects and exercises it read-only)

Report path (output destination, not an input): <$STORE/intent-recheck.md>

Do NOT pass the spec, the plan, the design doc, or the implementer's report —
the agent's independence depends on judging behavior against the ask alone.
```

The agent writes its full per-statement re-check to the report path and returns only `intent-reviewer — PASS | CONCERNS — report: <path>`. On a re-check after remediation, pass the same path so it can state per statement whether a prior `not-met` now holds.

If no intent ledger exists and no original-ask statement is recoverable (a change that never had one), note that explicitly and skip this step — do not fabricate a ledger after the fact.

**Must see:** Verdict PASS (no `not-met` statements). A `not-met` is a real gap between behavior and the ask and goes to the close round's triage (or, if the ledger itself is wrong, that is a user decision). Resolve every `can't-tell` before claiming completion. A PASS can still carry `can't-tell` items, so read the report at triage either way.

### Step 6: Mutation Re-check

Steps 1–5 trust the tests: if the suite is green, they treat the tested behavior as verified. But a test can execute a line and assert nothing about it — a green suite that proves nothing. This step checks that the tests written for this change *actually detect failures*: in a throwaway worktree the agent deliberately breaks the changed code and confirms a test fails. It uses no external mutation-testing tool — it edits the code and runs the project's own tests — so it works in any language with a runnable suite.

Run when the change includes testable source; skip a docs-only diff. It is the most expensive gate and only meaningful on the green suite Steps 1–2 established.

Dispatch the **`mutation-tester`** agent **with worktree isolation** — it deliberately breaks code, so it must never touch the working tree:

```
Agent(subagent_type: "chris-code:mutation-tester", isolation: "worktree", prompt: ...)

Inputs:
  - Mode: closing-review
  - Base branch: <the branch this split from, e.g. main>
  - Range (round 2 only): <round-1 head>..HEAD
  - Project constraints: <CLAUDE.md, verbatim>
```

The agent scopes mutation to the changed lines (`<merge-base>..HEAD`, or the `Range` when given), so the branch work must be committed — the same assumption Steps 3 and 5 make. Unlike the other gates it runs in an isolated worktree and returns its report inline, with no report path. Save that report to `$STORE/mutation-review.md` so a fix dispatch can carry the path; a re-run judges the code fresh, not against a prior report.

**Must see:** Verdict PASS. **CONCERNS** means a test executes changed code but no test fails when the agent breaks it — a trivial/non-discriminating test. The fix is a test that fails on the break, routed through the close round's triage. Uncovered breaks (missing tests) and breaks the agent discards as behavior-preserving (equivalent) are advisory notes — they do not block. A non-green baseline or a scope with nothing to mutate yields a non-blocking `skipped`/`inconclusive` (note it, do not stall the review).

## The Close Round: Dispatch Together, Triage Once

Steps 3, 5, and 6 are independent read-only reviews of the same committed HEAD. Fixing after each one in turn is what makes a close cascade: the design fix lands, then intent flags something on the patched code, then mutation does, and every behavioral fix reopens the gates before it. A **close round** replaces that with one dispatch wave and one triage. Run Steps 1–2 first, fix them in place, and commit those fixes. They are deterministic and gate everything after them, and the round records and reviews committed HEAD. Then:

1. **Start the round.** `python3 "$SDD_SCRIPTS/ledger.py" close-round --expect <N> --note "<the plan or issue path being closed>" --store "$STORE"`, where `<N>` is `1` for a fresh close and `2` only on return from this run's close-gate remediation (step 6). It prints the round number and records the HEAD it reviews. The note must name the work, because after a compaction it is how you recognize your own round. If the store disagrees with `--expect`, it fails. On an `--expect 1` failure, read the latest round's note in `ledger.py read`. If it names the work you're closing, the rounds are this run's, so never clear. Follow the error: with one round recorded, resume round 1's triage (the gate reports are still at their paths); with two, finish round 2's triage and escalate. If it names other work, it belongs to an earlier, finished run: `ledger.py clear` and retry. The cap is **two rounds**: past it the command exits non-zero, and the open findings escalate to the user (step 7). Never clear the store to get past the cap.
2. **Dispatch every applicable gate in one message:** each matching `*-design-reviewer` (Step 3), `intent-reviewer` (Step 5), and `mutation-tester` (Step 6), in parallel. Do the Step 4 requirements check while they run.
3. **Wait for every verdict.** Never start a fix while any gate in the round is still out; a fix made against a partial verdict set guarantees an extra round when the late gate lands.
4. **Triage every finding once,** reading every report (a PASS can carry S1–S2 findings and `can't-tell` items). Verify each finding is real (`chris-code:receiving-code-review`), then sort it:
   - **Trivial:** it changes no behavior, touches one site, and touches no contract: a docstring, comment, message or log text, local rename, or lint. Fix it inline.
   - **Test-only strengthening:** a mutation CONCERNS whose fix is a discriminating test and no source change. Dispatch the language-matched coder directly with `$STORE/mutation-review.md`, the record path `$STORE/final-close-r<N>-<coder-name>.json` (its record's `task` is `"final"`), and the scripts path.
   - **`can't-tell`:** re-dispatch `intent-reviewer` at its same report path with the missing observation or access it named. This happens inside the current round, not as a new one. Wait for that verdict and triage it with the rest before step 5, so a late `not-met` joins the batch. If the access can't be provided, ask the user.
   - **Separable:** a larger improvement the change is fully correct without. Log it as a follow-up (*Fix Fully, Defer Only the Separable*).
   - **Non-trivial:** everything else, including anything you hesitate to call trivial. Never fix it inline.
5. **Commit the inline and test-only fixes** through the `*-review-lite` gate before anything else runs, with the gate's record at `$STORE/final-close-r<N>-<agent-name>.json`. Round 2 and the remediation's whole-change gate review committed HEAD, so an uncommitted fix is invisible to them.
6. **Route the non-trivial set as one batch** through `chris-code:remediating-issues` (Batch Path, close-gate variant). Hand over the gate report paths, not a paraphrase: they frame each finding's end-state. `coherent-change` batch mode runs one consolidated research pass, writes one decision doc, and presents it at its stage-4 approval checkpoint. Then the batch **skips `lean-spec`** (the gate reports are the *what* and the decision doc is the *how*) and goes straight to one `lean-plan`, whose spec references are the decision doc and the report paths. Record the remediation so a compaction can't lose it: `python3 "$SDD_SCRIPTS/ledger.py" append --type progress --task final --note "close-gate remediation r1: plan <path>, decision <path>, intent <path>, front-end <skill>" --store "$STORE"`. Here `intent` is the round-2 intent ledger; when that is issue text named only in session, save it to `$STORE/intent-issue.md` first. `front-end` is the skill whose close resumes after round 2 (`remediating-issues`, `coherent-change`, or none). Execute the plan with `subagent-driven-development` **on this same store**, never `clear` it mid-close, and number the plan's tasks after the highest numeric id `ledger.py completed` lists so the new tasks never collide with finished ones. That SDD run's own close *is* round 2: invoke this skill once when its last task completes.
7. **Close again: round 2.** `close-round --expect 2` prints `2`. Take the round-1 head from `ledger.py read`; `<round-1 head>..HEAD` is the remediation range. Round 2 re-runs only what the remediation could have changed, in parallel:
   - **Design reviewers:** always, at their **same report paths**, with one added input, `Remediation range: <round-1 head>..HEAD`, so they judge whether their prior findings were addressed and scope new problems to the remediation.
   - **Mutation tester:** always, with `Range: <round-1 head>..HEAD`, so it mutates only the remediation's changed lines rather than the whole branch again.
   - **Intent reviewer:** only when the remediation changed observable behavior (any remediation task whose `Cases:` line lists behavior). It re-runs at its same report path with its two spec-blind inputs. A remediation that is structural only (every task `n/a — structural` or `preserves …`) keeps round 1's intent verdict.

   Use the same range yourself when sorting findings. Triage round 2 as in step 4, with three differences:
   - A finding that recurs from round 1 is always non-trivial.
   - A new finding outside the remediation range is fresh sampling, not a regression the fix caused. Log it as a follow-up in your completion report, and it does not block completion. The exception is an S4+ (correctness) finding, which escalates to the user wherever it sits.
   - Any non-trivial finding left after round 2 **escalates to the user**, with the report paths and the decision doc attached. There is no round 3. If the user rules it should be fixed, their ruling is the decision. Dispatch the language-matched coder with the ruling, the gate report path, the record path `$STORE/final-close-ruling-<coder-name>.json` (its own path, so it doesn't inherit a round-2 test fix's cycle), and the scripts path. Commit the fix through `*-review-lite` (record at `$STORE/final-close-ruling-<agent-name>.json`), then re-run Steps 1–2 plus each gate that flagged it, at its same report path, with `Remediation range: <round-2 head>..HEAD` for a design reviewer. That re-check sits outside the round count, so it gets one attempt: if a gate still flags it, return to the user rather than looping.

After either round, inline and test-only fixes close the same way: commit them and re-run Steps 1–2. In the round that ends the close (round 2, or a round 1 with no remediation), also re-mutate a strengthened test with one `mutation-tester` re-dispatch (not a new round). A round 1 that goes on to remediation skips that, since round 2 re-runs mutation anyway. A round 1 whose findings were all trivial, test-only, `can't-tell`, or separable needs no round 2, so you're done once those are closed.

### Discriminating checks, and re-running after remediation

Two failure modes quietly turn a green gate into a false pass:

- **A behavioral check that doesn't discriminate proves nothing, even when it passes.** Whether the intent-reviewer exercises the system or you confirm a fix by observation, the check must hold under correct behavior and fail under the bug (see the discriminating-assertion rule in `chris-code:regression-test`). "Output is present", "renders without error", "is not None" are satisfied by the broken state too. A reviewer can be fooled by the same weak heuristic you would be, so treat a PASS built on a non-discriminating observation as unproven.
- **A CONCERNS→fix leaves a stale verdict until you re-run.** When a round's findings are remediated, the prior verdicts describe the pre-fix system; round 2 re-runs every gate the remediation could have changed for that reason (see step 7). A strengthened test must be re-mutated — the old mutation verdict was measured against the trivial test. Don't substitute "it's byte-identical so the verdict holds" for the re-run: prove byte-identity first (stash the fix, diff output or hashes), and if it isn't identical, regenerate and re-inspect every golden it touched before the verdict counts.

## After Verification Passes

Every finding fixed, logged as a follow-up (separable, or fresh sampling in round 2), or adjudicated by the user → you may claim completion, listing the follow-ups. Then invoke `chris-code:finishing-a-development-branch` for the integration workflow (merge/PR/keep/discard).

## What These Gates Do and Don't Prove

Be honest about what a green pipeline buys. These steps are not independent guarantees stacked into a proof. Only a few axes are genuinely independent: the **linter** (a deterministic, non-LLM check), **conformance** (does the behavior match the spec/intent), and the **mutation gate** (which breaks the code and runs the real tests to see whether they catch it — the verdict is test execution, not another LLM re-read). The design and quality re-judgments are correlated LLM passes — they share a model, a training distribution, and often a framing, so they tend to miss the same things together.

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
- **`mutation-tester`** — mutation gate in an isolated worktree (breaks changed code, runs the tests, reverts), dispatched when the change includes testable source (Step 6)

**This skill routes:**
- **chris-code:remediating-issues** — a close round's non-trivial findings, as one batch (close-gate variant: no `lean-spec`)

**Related skills:**
- **chris-code:test-driven-development** — TDD ensures tests exist; this skill ensures they pass
- **chris-code:regression-test** — ensures bug fixes have regression coverage before verification
