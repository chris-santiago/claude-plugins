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

The steps are numbered for reference, not run in sequence. Steps 1–2 run first; then Steps 3–5 are dispatched together as one close (*The Close*), and `ledger.py triage --task close` decides what happens to every finding.

**Paths.** Resolve `$STORE` once with `python3 "$SDD_SCRIPTS/ledger.py" store-dir`, the same authority subagent-driven-development uses; it works in any git repo, even when SDD didn't run. Every report and record path below comes from `python3 "$SDD_SCRIPTS/ledger.py" path --task close --agent <name> [--kind report] --store "$STORE"`: the close's gates, its coders and its decision docs all live in the `close` scope, and a re-check reuses the same paths. `SDD_SCRIPTS` is the absolute path of the `subagent-driven-development` skill's `scripts/` directory: reuse it if SDD pinned it this session, otherwise derive it from this skill's "Base directory for this skill" line as `<that directory>/../subagent-driven-development/scripts`, since both skills ship in the same plugin.

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

Dispatch **every matching** `*-design-reviewer` agent by `scope.extensions` (additive: a change spanning `.py`/`.ipynb` and `.rs` gets both `python-design-reviewer` and `rust-design-reviewer`). These read-only agents are the senior pass for design drift, API cohesion and structure that review-lite and the quality reviewers miss, run in their own context so the analysis stays out of yours. (For hands-on refactoring outside the gate, use the `python-review` / `rust-review` skills.)

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
  - Report path: <path --task close --agent <agent-name> --kind report>
  - Record path: <path --task close --agent <agent-name>>
  - Scripts path: <$SDD_SCRIPTS, absolute>
```

The agent writes its report and its typed record and returns only `<agent-name> — PASS | CONCERNS — report: <path>`. Hand it the inputs and constraints, never a narrowed scope; never tell it to skip a concern or pre-rate a severity.

**Must see:** every S4–S5 finding fixed and re-checked, or ruled by the user; every S1–S3 finding ruled fix, file or drop (*The Close*).

### Step 4: Intent Re-check

Steps 1–3 compare the work to the spec. None asks whether the shipped behavior does what the user originally asked for, and a build can pass every spec gate while the spec drifted from the ask. Dispatch the read-only **`intent-reviewer`**, which is **spec-blind**: give it the frozen intent ledger and the running system, never the spec, plan or briefs.

```
Inputs (exactly two):
  - Intent ledger: <.claude/output/intent/YYYY-MM-DD-<topic>-intent.md>
    (for a bug remediation, the issue text IS the ledger — pass it instead)
  - The running system (the agent inspects and exercises it read-only)

Output destinations, not inputs:
  - Report path: <path --task close --agent intent-reviewer --kind report>
  - Record path: <path --task close --agent intent-reviewer>
  - Scripts path: <$SDD_SCRIPTS, absolute>

Do NOT pass the spec, the plan, the design doc, or the implementer's report —
the agent's independence depends on judging behavior against the ask alone.
```

It judges each statement met, not-met or can't-tell, writes its report and record, and returns only `intent-reviewer — PASS | CONCERNS — report: <path>`. On a re-check after the coder contested one of its findings, the dispatch adds the close coder's record path, of which the agent reads only the `contested` entries. If no intent ledger exists and no original-ask statement is recoverable, say so and skip this step; never fabricate a ledger after the fact.

**Must see:** no `not-met` statement left open, and no `can't-tell`. A `not-met` is a real gap between behavior and the ask and is fixed in the close, unless the user rules it `file` or `drop` (a wrong ledger is one reason to).

### Step 5: Mutation Re-check

A test can execute a line and assert nothing about it, so a green suite can prove nothing. This step checks that the change's tests detect failures: in a throwaway worktree the agent breaks the changed code and confirms a test fails, using the project's own tests and no external mutation tool. Run it when the change includes testable source, and skip a docs-only diff. It is the most expensive gate and only meaningful on the green suite from Steps 1–2.

**Ask the user before running it.** Each task's quality reviewers already break the code a sample of its new or changed tests claim to check (their *Break check*), so this full gate is the user's call. It often takes an hour or more, and several hours on a large change. Before the close's dispatch, show the user the range it would mutate (`git diff --shortstat <merge-base>..HEAD`) and ask whether to run it, saying how long it can take. Record the answer verbatim: `python3 "$SDD_SCRIPTS/ledger.py" append --type progress --task close --note "user ruling: mutation gate: <their answer>" --store "$STORE"`. It holds for the whole close, re-checks included, and starts no round; after a compaction, `ledger.py run-state` shows it, so don't ask again. When they decline, skip this step and say so in the completion report.

First resolve the rigor level, which sets how many breaks the tester makes and which survivors gate (`$SDD_SCRIPTS/../rigor.md`). With a plan, run `python3 "$SDD_SCRIPTS/rigor.py" --plan <plan> --store "$STORE" --files`: its first line is the project level, and each later line a file a plan task raised above it. Without a plan, run `python3 "$SDD_SCRIPTS/rigor.py"`. Exit 2 means a bad `Test rigor:` line in `CLAUDE.md` or a lowering `Rigor:` line in the plan: fix it and re-run.

Dispatch the **`mutation-tester`** **with worktree isolation**, since it breaks code and must never touch the working tree. When the project level is `light` and no file is raised above it, pass `model: sonnet`: an exception to each role running on its frontmatter model (the other is a coder the user rules onto opus), because a light change gets few breaks and its survivors gate only on behavior its rows name (or, without a plan, on functions its tests call directly).

```
Agent(subagent_type: "chris-code:mutation-tester", isolation: "worktree", prompt: ...)
  # light, no raised files: Agent(..., model: "sonnet", ...)

Inputs:
  - Mode: closing-review
  - Base branch: <the branch this split from, e.g. main>
  - Range (re-check only): <the fix commit>^..HEAD
  - Re-break (re-check of a survivor ruled fix only): <the finding's sites>
  - Rigor: <project level> (<reasons>)       # rigor.py's first line
  - Plan: <path> | none
  - File levels: <rigor.py's later lines, verbatim> | none
  - Rigor table: <$SDD_SCRIPTS/../rigor.md, absolute>
  - Project constraints: <CLAUDE.md, verbatim>
  - Report path: <path --task close --agent mutation-tester --kind report>
  - Record path: <path --task close --agent mutation-tester>
  - Scripts path: <$SDD_SCRIPTS, absolute>
```

It mutates the changed lines (`<merge-base>..HEAD`, or the `Range`), so the branch work must be committed, as for Steps 3 and 4.

**Must see:** a verdict. **CONCERNS** means a test executes changed code but none fails when the agent breaks it: a non-discriminating test. Its survivors wait for the user's ruling (fix, file or drop); they don't block the close by themselves. Uncovered breaks (missing tests) and breaks discarded as behavior-preserving are advisory. A non-green baseline or nothing to mutate yields a non-blocking `skipped` or `inconclusive`: note it and move on.

## The Close

Steps 3–5 are independent read-only reviews of the same committed HEAD. Fixing after each in turn cascades: the design fix lands, intent flags the patched code, then mutation does, and every behavioral fix reopens the gates before it. So the close is one dispatch wave, and from there `triage` decides each step from the gates' typed records, as it does for a task but under the close's own rule. You never sort a finding. Each one is its own run of entries in the progress log, as in a task, and its state is its latest entry. The first time triage sees a finding it starts it as **fix** (an intent `not-met`, S4–S5, or a failing commit gate: blocking, sent to a coder) or **waiting** (anything else: the user decides). After that a gate's re-check only reports what it saw (gone, still raised, a contest conceded or held), so a re-check scoped to one fix never loses another gate's finding.

The user rules findings with `python3 "$SDD_SCRIPTS/ledger.py" rule <id>... --as fix|file|drop --note "user ruling: <their words>" --store "$STORE"`, one call per verb. `fix` sends the finding to a ruling round, `file` files it as a follow-up at once (carrying its id, gate and report path), and `drop` settles it. A later ruling replaces an earlier one, so the user can change their mind until the close is done; ruling `fix` on a filed finding resolves its follow-up. `rule` refuses an id no close gate raised, a finding already fixed, and anything once the close is done.

Run Steps 1–2 first, fix them in place, and commit those fixes: they are deterministic, gate everything after them, and the gates review committed HEAD. Then:

1. **Start the close.** First settle what the close owns (`ledger.py run-state` lists it): ask the user each open `question` and resolve it with `user ruling: <their answer, verbatim>`; land each open `disclosure` and resolve it with the file and commit where it landed; resolve any task-note whose task never ran. Ask whether to run the mutation gate (Step 5). Then run `python3 "$SDD_SCRIPTS/ledger.py" close-round --note "<the plan or issue path being closed>" --store "$STORE"`. It records and prints the HEAD the gates review, and refuses while the close owns an open note, or when the store already holds a close: an unfinished one resumes with `triage --task close`, and a finished one is final. A new close needs a cleared store: show the user `ledger.py report`, then `ledger.py clear`, passing `--discard-open` only on their confirmation. Rule close findings with `rule`, and log any other ruling about the close on `--task close`, never as a run-note: run-notes reach coders.
2. **Dispatch every applicable gate in one message:** each matching `*-design-reviewer` (Step 3), `intent-reviewer` (Step 4) and, when the user chose to run it, `mutation-tester` (Step 5), in parallel.
3. **Wait for every verdict.** Never start a fix while a gate is still out: a fix against a partial set guarantees an extra round when the late gate lands.
4. **Run `python3 "$SDD_SCRIPTS/ledger.py" triage --task close --store "$STORE"`** and act on the step it prints:
   - **`patch` or `holistic`:** fix the `fix` findings in place (step 5). Contract reach makes it holistic.
   - **`clarify`:** an intent statement is `can't-tell`. Re-dispatch the intent reviewer at its same paths with the access its record's `needs` names. If that access can't be given, ask the user and resolve the statement's id (`close-intent-reviewer#statements[<n>]`) with `user ruling: <their answer>`. A clarify step counts toward no cap.
   - **`decide`:** findings wait for the user, and triage lists each with its rule, severity and gate. They are the non-blocking findings, any a gate holds against a coder's contest, and any `fix` finding still open after two fix rounds or a ruling round (triage moves those to `waiting`). Put them to the user in one message, each with its report path, the decision doc where one ran, and a recommendation (after a failed ruling round, recommend `file`), and log the answers with `rule`. Then run `triage`: a finding ruled `fix` starts a ruling round.
   - **`done`:** nothing blocks or waits. The close is final.
   Triage files the close coder's own deferrals (sites outside its fix, root causes a decision excluded) as follow-ups when it first sees them.
5. **Fix in place,** by the round's kind:
   - **A `patch` or ruling round** goes to the language-matched coder at `path --task close --agent <coder-name>` (report path with `--kind report`), with the raising gates' record and report paths, the `Fix baseline` and `Task files` lines triage printed, the project constraints verbatim, the contract of the quality reviewer paired with the coder for each language the fix touches (subagent-driven-development's *Review Agents*) as the review checklist, and the scripts path; a ruling round also quotes the user's ruling verbatim. The coder's record has `task` `"close"`, and its first close fix is cycle 2. Record its id with `ledger.py handle --task close --role <coder-name> --agent <id>`, and send a later round to that same coder with `SendMessage` while it is reachable. The coder may contest a finding instead of fixing it, and the raising gate concedes or holds it in its re-check.
   - **A `holistic` round** first dispatches a general-purpose agent with `model: opus`, told to invoke `chris-code:remediating-issues` (per-task variant), with the gates' record and report paths, the coder's record path if one exists, the `Task files`, the scripts and store paths, the constraints and the output path triage names (`close-decision-c<cycle>.json`); there is no brief. The coder then implements the doc case by case.
   - **A round triage marks `inline`** (usually a ruling round on findings the user ruled `fix`, each one site of S3 or less) is offered to the user first, and waits for their answer: ask at once whether you or the coder fixes it, as in subagent-driven-development's *Ask who fixes a small round*, and log it with `python3 "$SDD_SCRIPTS/ledger.py" inline --task close --by coder|orchestrator --note "user ruling: <their words>" --store "$STORE"`. Until then `baseline` refuses the round and `check` refuses a coder's fix for it. If they choose you, fix it, then run `python3 "$SDD_SCRIPTS/ledger.py" inline --task close --done --files <every file you changed> --store "$STORE"`, and tell each re-checking gate the round was fixed inline, with no coder record.
   - **Commit the fix.** When the coder (or you) finishes, run `python3 "$SDD_SCRIPTS/ledger.py" commit --task close --message "<message>" --test "<the project's full test suite>" [--lint "<the lint command>"] --store "$STORE"`: it gates and commits the fix's files and completes nothing. A labels, lint or test failure goes back to the coder as the same attempt (after an inline fix, it is yours): the round's fix isn't finished until it commits, and `triage` waits for that commit. A fix that changed nothing (every finding contested) commits nothing once the gate passes on HEAD, and goes to its re-check.
   - **A fix that can't land.** A coder that can't land the fix (blocked, or unable to make the gate pass) brings the round's findings to the user. Keeping the work means another attempt, which resumes the round. Ending it means ruling every finding it sent `file` or `drop`; then `triage` waits for `ledger.py discard --task close`, which puts the round's files back to its `Fix baseline` and drops the gate record that judged them.
6. **Re-check exactly the `re-check` set triage printed,** at the gates' same paths, with the round's kind, its `Fix baseline` and files, the settled ids, and the coder's record path when it contested one of that gate's findings. A gate whose findings weren't sent stays out of the re-check, and a fix finding its gate no longer raises is fixed. The mutation tester re-checks only a survivor ruled `fix`, with `Range: <the fix commit>^..HEAD` and `Re-break: <the finding's sites>`, since the fix usually changed a test rather than the line that survived. Then run `triage` again: until each finding the round sent has been re-checked by its gate, it reprints the round with the gates it is waiting for and starts nothing.

### Discriminating checks, and re-running after a fix

Two failure modes turn a green gate into a false pass:

- **A behavioral check that doesn't discriminate proves nothing, even when it passes.** Whether the intent reviewer exercises the system or you confirm a fix by observation, the check must hold under correct behavior and fail under the bug (the discriminating-assertion rule in `chris-code:regression-test`). "Output is present", "renders without error" and "is not None" are satisfied by the broken state too. A reviewer can be fooled by the same weak heuristic, so treat a PASS built on a non-discriminating observation as unproven.
- **A fix leaves a stale verdict until its gate re-checks.** After a fix, the raising gate's verdict describes the pre-fix system, which is why triage re-dispatches it before `done`. Don't substitute "it's byte-identical, so the verdict holds" for the re-check: prove byte-identity first (stash the fix, diff output or hashes), and if it isn't identical, regenerate and re-inspect every golden it touched before the verdict counts.

## After Verification Passes

When triage prints `done` for the close, you may claim completion. Build the completion report from `python3 "$SDD_SCRIPTS/ledger.py" report --store "$STORE"`, not from memory: it lists the user's rulings, the follow-ups, the coders' `unlisted case:` entries (where the plan's `Cases:` lines were thin), your dispositions and waivers, where each disclosure landed, and which tasks ran on executing-plans' light path.

**The close batch.** The close's own findings were decided inside the close: one the user ruled `file` is an open follow-up already carrying that ruling, so recommend keeping it filed. The report groups every open follow-up by rule, including the run's others: notes the coders skipped, minor findings whose fix would change a contract, sites a sweep found outside a task, and anything else filed during the run. Present them in one message, each with a recommendation, and let the user pick per item: **fix**, **file** (keep it as a follow-up past this branch), or **ignore** (`resolve` it with their ruling). The items to fix go through `chris-code:remediating-issues`' Batch Path as one change, not one fix per item: resolve each with `resolve <id> --note "routed to <the batch's spec path>"` so the store can later be cleared without discarding it. Nothing in the change is left behind without the user deciding it.

Then invoke `chris-code:finishing-a-development-branch` for the integration workflow (merge/PR/keep/discard).

## What These Gates Do and Don't Prove

A green pipeline is not a stack of independent guarantees. Only a few axes are independent: the **linter** (deterministic, not an LLM), **conformance** (does the behavior match the spec and the intent), and the **mutation gate** and the quality reviewers' per-task break check (their verdict is test execution, not another LLM read). The design and quality reviews are correlated LLM passes that share a model, a training distribution and often a framing, so they tend to miss the same things.

- More passes raise **recall** (more issues surfaced), not **residual assurance**: a clean run means "nothing these lenses caught", not "nothing is wrong".
- **Diversity beats quantity.** A check that fails differently (a deterministic linter, a spec-blind behavior check, a real failing test, a human read) adds more than another same-model review of the same diff. That is why the intent re-check (Step 4) is spec-blind.
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
- **`intent-reviewer`**: read-only, spec-blind behavior-vs-intent re-check (Step 4)
- **`mutation-tester`**: the mutation gate in an isolated worktree, when the change includes testable source and the user chose to run it (Step 5)
- **the language-matched coder**: a blocking close finding, fixed in place (*The Close*)

**This skill routes:**
- **chris-code:remediating-issues**: a close holistic round's decision doc (per-task variant), and the close batch's non-close items marked fix (Batch Path)

**Related skills:**
- **chris-code:test-driven-development**: TDD makes sure tests exist; this skill makes sure they pass
- **chris-code:regression-test**: makes sure bug fixes have regression coverage before verification
