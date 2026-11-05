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

The steps are numbered for reference, not run in sequence. Steps 1–2 run first; then Steps 3, 5 and 6 are dispatched together, with Step 4 done alongside them, as one close round (*The Close Round*).

**Paths.** Resolve `$STORE` once with `python3 "$SDD_SCRIPTS/ledger.py" store-dir`, the same authority subagent-driven-development uses; it works in any git repo, even when SDD didn't run. `SDD_SCRIPTS` is the absolute path of the `subagent-driven-development` skill's `scripts/` directory: reuse it if SDD pinned it this session, otherwise derive it from this skill's "Base directory for this skill" line as `<that directory>/../subagent-driven-development/scripts`, since both skills ship in the same plugin.

### Step 1: Tests

Run the project's full test suite, not a subset or "the tests I think are relevant".

```bash
# Use the project's test runner
pytest / cargo test / npm test / go test ./...
```

**Must see:** zero failures, clean output. Fix failures before Step 2.

### Step 2: Lints

Run the project's linter, even when the tests pass.

```bash
# Use the project's linter
ruff check / cargo clippy -- -D warnings / eslint / golangci-lint run
```

**Must see:** zero errors and zero warnings (pre-existing warnings excepted). Fix lint issues before proceeding.

### Step 3: Full Review

Dispatch **every matching** `*-design-reviewer` agent by `scope.extensions` (additive: a change spanning `.py`/`.ipynb` and `.rs` gets both `python-design-reviewer` and `rust-design-reviewer`). Where findings conflict, the more domain-specific review wins. These read-only agents are the senior pass for design drift, API cohesion and structure that review-lite and the quality reviewers miss, run in their own context so the analysis stays out of yours. (For hands-on refactoring outside the gate, use the `python-review` / `rust-review` skills.)

Dispatch each with this framing, since design and cohesion are the mandate, not a bug hunt:

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

The agent writes its full report to that path and returns only `<agent-name> — PASS | CONCERNS — report: <path>`. At triage, read every report, not only the CONCERNS ones: a PASS can carry S1–S2 findings. On a re-run after remediation, pass the same report path, so the agent judges whether its prior findings were addressed instead of re-deriving them. Hand it the inputs and constraints, never a narrowed scope; never tell it to skip a concern or pre-rate a severity.

**Must see:** PASS from every dispatched agent (no S3+ findings), or every CONCERNS finding resolved through the close round, which is where they are fixed (*The Close Round*).

### Step 4: Requirements Check

Re-read the plan or spec that drove this work. With no spec (a bug remediation, or a single `coherent-change` build), the issue text and the decision doc are the requirements; in round 2, add the close-gate decision doc and remediation plan. For each requirement:

1. Can you point to the code that implements it?
2. Can you point to a test that verifies it?
3. Is there anything in the spec that was not implemented?
4. Is there anything implemented that was not in the spec?

**Must see:** every requirement covered. A gap joins the close round's triage with the gate findings; it is never claimed complete.

### Step 5: Intent Re-check

Steps 1–4 compare the work to the spec. None asks whether the shipped behavior does what the user originally asked for, and a build can pass every spec gate while the spec drifted from the ask. Dispatch the read-only **`intent-reviewer`**, which is **spec-blind**: give it the frozen intent ledger and the running system, never the spec, plan or briefs.

```
Inputs (exactly two):
  - Intent ledger: <.claude/output/intent/YYYY-MM-DD-<topic>-intent.md>
    (for a bug remediation, the issue text IS the ledger — pass it instead)
  - The running system (the agent inspects and exercises it read-only)

Report path (output destination, not an input): <$STORE/intent-recheck.md>

Do NOT pass the spec, the plan, the design doc, or the implementer's report —
the agent's independence depends on judging behavior against the ask alone.
```

It writes its per-statement re-check to the report path and returns only `intent-reviewer — PASS | CONCERNS — report: <path>`. On a re-check after remediation, pass the same path so it can say per statement whether a prior `not-met` now holds. If no intent ledger exists and no original-ask statement is recoverable, say so and skip this step; never fabricate a ledger after the fact.

**Must see:** PASS (no `not-met` statements). A `not-met` is a real gap between behavior and the ask and goes to the close round's triage, unless the ledger itself is wrong, which is the user's call. Resolve every `can't-tell` before claiming completion, and read the report either way: a PASS can carry `can't-tell` items.

### Step 6: Mutation Re-check

A test can execute a line and assert nothing about it, so a green suite can prove nothing. This step checks that the change's tests detect failures: in a throwaway worktree the agent breaks the changed code and confirms a test fails, using the project's own tests and no external mutation tool. Run it when the change includes testable source, and skip a docs-only diff. It is the most expensive gate and only meaningful on the green suite from Steps 1–2.

First resolve the rigor level, which sets how many breaks the tester makes and which survivors gate (`$SDD_SCRIPTS/../rigor.md`). With a plan (in close round 2, the remediation plan, matching `Range`), run `python3 "$SDD_SCRIPTS/rigor.py" --plan <plan> --store "$STORE" --files`: its first line is the project level, and each later line a file a plan task raised above it. Without a plan, run `python3 "$SDD_SCRIPTS/rigor.py"`. Exit 2 means a bad `Test rigor:` line in `CLAUDE.md` or a lowering `Rigor:` line in the plan: fix it and re-run.

Dispatch the **`mutation-tester`** **with worktree isolation**, since it breaks code and must never touch the working tree. When the project level is `light` and no file is raised above it, pass `model: sonnet`: the one documented exception to each role running on its frontmatter model, because a light change gets few breaks and its survivors gate only on behavior its rows name (or, without a plan, on functions its tests call directly).

```
Agent(subagent_type: "chris-code:mutation-tester", isolation: "worktree", prompt: ...)
  # light, no raised files: Agent(..., model: "sonnet", ...)

Inputs:
  - Mode: closing-review
  - Base branch: <the branch this split from, e.g. main>
  - Range (round 2 only): <round-1 head>..HEAD
  - Rigor: <project level> (<reasons>)       # rigor.py's first line
  - Plan: <path> | none
  - File levels: <rigor.py's later lines, verbatim> | none
  - Rigor table: <$SDD_SCRIPTS/../rigor.md, absolute>
  - Project constraints: <CLAUDE.md, verbatim>
```

It mutates the changed lines (`<merge-base>..HEAD`, or the `Range`), so the branch work must be committed, as for Steps 3 and 5. It returns its report inline, with no report path: save it to `$STORE/mutation-review.md` so a fix dispatch can carry the path. A re-run judges the code fresh, not against a prior report.

**Must see:** PASS. **CONCERNS** means a test executes changed code but none fails when the agent breaks it: a non-discriminating test, fixed by a test that fails on the break, through the close round's triage. Uncovered breaks (missing tests) and breaks discarded as behavior-preserving are advisory. A non-green baseline or nothing to mutate yields a non-blocking `skipped` or `inconclusive`: note it and move on.

## The Close Round: Dispatch Together, Triage Once

Steps 3, 5 and 6 are independent read-only reviews of the same committed HEAD. Fixing after each in turn cascades: the design fix lands, intent flags the patched code, then mutation does, and every behavioral fix reopens the gates before it. A **close round** is one dispatch wave and one triage instead. Run Steps 1–2 first, fix them in place, and commit those fixes: they are deterministic, gate everything after them, and the round reviews committed HEAD. Then:

1. **Start the round.** First settle what the close owns (`ledger.py run-state` lists it): ask the user each open `question` and resolve it with `user ruling: <their answer, verbatim>`; land each open `disclosure` and resolve it with the file and commit where it landed; resolve any task-note whose task never ran. `close-round` refuses until none is open. Then run `python3 "$SDD_SCRIPTS/ledger.py" close-round --expect <N> --note "<the plan or issue path being closed>" --store "$STORE"`, with `<N>` `1` for a fresh close and `2` only on return from this run's close-gate remediation (step 6). It prints the round number and records the HEAD it reviews. The note must name the work: after a compaction it is how you recognize your own round.
   - **When `--expect` disagrees with the store,** it fails. On an `--expect 1` failure, read the latest round's note in `ledger.py read`. If it names the work you're closing, the rounds are this run's, so never clear: with one round recorded, resume round 1's triage (the gate reports are still at their paths); with two, finish round 2's triage and escalate. If it names other work, it belongs to an earlier, finished run: `ledger.py clear` and retry. `clear` refuses while that run's follow-ups, disclosures or questions are open: show the user `ledger.py report`, and pass `--discard-open` only once they confirm.
   - **The cap is two rounds.** Past it the command exits non-zero, and the open findings escalate to the user (step 7). Never clear the store to get past the cap.
2. **Dispatch every applicable gate in one message:** each matching `*-design-reviewer` (Step 3), `intent-reviewer` (Step 5) and `mutation-tester` (Step 6), in parallel. Do the Step 4 requirements check while they run.
3. **Wait for every verdict.** Never start a fix while a gate is still out: a fix against a partial set guarantees an extra round when the late gate lands.
4. **Triage every finding once,** reading every report (a PASS can carry S1–S2 findings and `can't-tell` items). Verify each finding is real (`chris-code:receiving-code-review`), then sort it:
   - **Trivial:** changes no behavior, touches one site and no contract (a docstring, comment, message or log text, local rename, or lint). Fix it inline.
   - **Test-only strengthening:** a mutation CONCERNS whose fix is a discriminating test with no source change. Dispatch the language-matched coder directly with `$STORE/mutation-review.md`, a report path (`$STORE/final-close-r<N>-<coder-name>-report.md`), the record path `$STORE/final-close-r<N>-<coder-name>.json` (its record's `task` is `"final"`), and the scripts path. If that coder is sent back to fix its own work (a blocked lite gate, say), it writes cycle 2: first run `python3 "$SDD_SCRIPTS/ledger.py" snapshot --task final --label "pre-fix c<cycle>" --store "$STORE"` and pass `Fix baseline: <tree>`, since `check` refuses a fix record without its own baseline.
   - **`can't-tell`:** re-dispatch `intent-reviewer` at its same report path with the observation or access it named, inside the current round. Triage its verdict with the rest before step 5, so a late `not-met` joins the batch. If the access can't be provided, ask the user.
   - **Separable:** a larger improvement the change is fully correct without. File it as a follow-up: `python3 "$SDD_SCRIPTS/ledger.py" note --kind follow-up --from final --text "..." --store "$STORE"` (*Fix Fully, Defer Only the Separable* in `remediating-issues`).
   - **Non-trivial:** everything else, including anything you hesitate to call trivial. Never fix it inline.
5. **Commit the inline and test-only fixes** before anything else runs: once `python3 "$SDD_SCRIPTS/ledger.py" labels HEAD <changed files>` is clean (rewrite each review-process label it lists, or leave a hit that isn't one), through the `*-review-lite` gate with its record at `$STORE/final-close-r<N>-<agent-name>.json`. Round 2 and the remediation's whole-change gate review committed HEAD, so an uncommitted fix is invisible to them.
6. **Route the non-trivial set as one batch** through `chris-code:remediating-issues` (Batch Path, close-gate variant), handing over the gate report paths, not a paraphrase: they frame each finding's end-state. That variant runs one `coherent-change` batch research pass and one decision doc with its stage-4 approval, skips `lean-spec`, and goes to one `lean-plan` whose spec references are the decision doc and the report paths. Record the remediation so a compaction can't lose it: `python3 "$SDD_SCRIPTS/ledger.py" append --type progress --task final --note "close-gate remediation r1: plan <path>, decision <path>, intent <path>, front-end <skill>" --store "$STORE"`. `intent` is the round-2 intent ledger (save issue text named only in session to `$STORE/intent-issue.md` first); `front-end` is the skill whose close resumes after round 2 (`remediating-issues`, `coherent-change`, or none). Execute the plan with `subagent-driven-development` on **this same store**, never clearing it mid-close, with the plan's tasks numbered after the highest numeric id `ledger.py completed` lists. That SDD run's own close *is* round 2: invoke this skill once when its last task completes.
7. **Close again: round 2.** `close-round --expect 2` prints `2`. Take the round-1 head from `ledger.py read`; `<round-1 head>..HEAD` is the remediation range. Round 2 re-runs only what the remediation could have changed, in parallel:
   - **Design reviewers:** always, at their **same report paths**, with one added input, `Remediation range: <round-1 head>..HEAD`, so they judge whether their prior findings were addressed and scope new problems to the remediation.
   - **Mutation tester:** always, with `Range: <round-1 head>..HEAD`, so it mutates only the remediation's lines.
   - **Intent reviewer:** only when the remediation changed observable behavior (a remediation task whose `Cases:` line lists behavior), at its same report path with its two spec-blind inputs. A structural-only remediation (every task `n/a — structural` or `preserves …`) keeps round 1's intent verdict.

   Use the same range yourself when sorting findings, and triage round 2 as in step 4, with three differences:
   - A finding that recurs from round 1 is always non-trivial.
   - A new finding outside the remediation range is fresh sampling, not a regression the fix caused: file it as a follow-up, and it doesn't block completion. An S4+ (correctness) finding is the exception and escalates to the user wherever it sits.
   - Any non-trivial finding left after round 2 **escalates to the user**, with the report paths and the decision doc attached. There is no round 3. If the user rules it should be fixed, the ruling is the decision: dispatch the language-matched coder with the ruling, the gate report path, a report path (`$STORE/final-close-ruling-<coder-name>-report.md`), the record path `$STORE/final-close-ruling-<coder-name>.json` (its own, so it doesn't inherit a round-2 test fix's cycle), and the scripts path. Run the same `labels HEAD` check, commit the fix through `*-review-lite` (record at `$STORE/final-close-ruling-<agent-name>.json`), then re-run Steps 1–2 and each gate that flagged it, at its same report path, with `Remediation range: <round-2 head>..HEAD` for a design reviewer. That re-check sits outside the round count and gets one attempt: if a gate still flags it, return to the user rather than looping.

After either round, inline and test-only fixes close the same way: commit them and re-run Steps 1–2. In the round that ends the close (round 2, or a round 1 with no remediation), re-mutate a strengthened test with one `mutation-tester` re-dispatch, not a new round; a round 1 that goes on to remediation skips this, since round 2 re-runs mutation. A round 1 whose findings were all trivial, test-only, `can't-tell` or separable needs no round 2: you're done once they are closed.

### Discriminating checks, and re-running after remediation

Two failure modes turn a green gate into a false pass:

- **A behavioral check that doesn't discriminate proves nothing, even when it passes.** Whether the intent reviewer exercises the system or you confirm a fix by observation, the check must hold under correct behavior and fail under the bug (the discriminating-assertion rule in `chris-code:regression-test`). "Output is present", "renders without error" and "is not None" are satisfied by the broken state too. A reviewer can be fooled by the same weak heuristic, so treat a PASS built on a non-discriminating observation as unproven.
- **A CONCERNS→fix leaves a stale verdict until you re-run.** After remediation the prior verdicts describe the pre-fix system, which is why round 2 re-runs every gate the remediation could have changed, and why a strengthened test must be re-mutated (the old verdict measured the trivial test). Don't substitute "it's byte-identical, so the verdict holds" for the re-run: prove byte-identity first (stash the fix, diff output or hashes), and if it isn't identical, regenerate and re-inspect every golden it touched before the verdict counts.

## After Verification Passes

When every finding is fixed, filed as a follow-up (separable, or fresh sampling in round 2), or adjudicated by the user, you may claim completion. Build the completion report from `python3 "$SDD_SCRIPTS/ledger.py" report --store "$STORE"`, not from memory: it lists the user's rulings, the follow-ups, the coders' `unlisted case:` entries (where the plan's `Cases:` lines were thin), your dispositions and waivers, where each disclosure landed, and which tasks ran on executing-plans' light path.

**The close batch.** The report groups the open follow-ups by rule: notes the coders skipped, minor findings whose fix would change a contract, sites a sweep found outside a task, and anything else filed during the run. Present them in one message, each with a recommendation, and let the user pick per item: **fix**, **file** (keep it as a follow-up past this branch), or **ignore** (`resolve` it with their ruling). The items to fix go through `chris-code:remediating-issues`' Batch Path as one change, not one fix per item. Nothing in the change is left behind without the user deciding it.

Then invoke `chris-code:finishing-a-development-branch` for the integration workflow (merge/PR/keep/discard).

## What These Gates Do and Don't Prove

A green pipeline is not a stack of independent guarantees. Only a few axes are independent: the **linter** (deterministic, not an LLM), **conformance** (does the behavior match the spec and the intent), and the **mutation gate** (its verdict is test execution, not another LLM read). The design and quality reviews are correlated LLM passes that share a model, a training distribution and often a framing, so they tend to miss the same things.

- More passes raise **recall** (more issues surfaced), not **residual assurance**: a clean run means "nothing these lenses caught", not "nothing is wrong".
- **Diversity beats quantity.** A check that fails differently (a deterministic linter, a spec-blind behavior check, a real failing test, a human read) adds more than another same-model review of the same diff. That is why the intent re-check (Step 5) is spec-blind.
- No gate verifies that **the spec itself is right**. Conformance is not correctness; that judgment stays with the user.

Run the gates: they catch real drift. Just don't read green as proof of its absence.

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
- **chris-code:finishing-a-development-branch**: don't invoke it until verification passes

**This skill dispatches:**
- **`*-design-reviewer` agents**: read-only senior review, by scope (Step 3)
- **`intent-reviewer`**: read-only, spec-blind behavior-vs-intent re-check (Step 5)
- **`mutation-tester`**: the mutation gate in an isolated worktree, when the change includes testable source (Step 6)

**This skill routes:**
- **chris-code:remediating-issues**: a close round's non-trivial findings, as one batch (close-gate variant: no `lean-spec`)

**Related skills:**
- **chris-code:test-driven-development**: TDD makes sure tests exist; this skill makes sure they pass
- **chris-code:regression-test**: makes sure bug fixes have regression coverage before verification
