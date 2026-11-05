---
name: remediating-issues
description: >
  Use when remediating a non-trivial open issue, bug, or review/audit finding
  where more than one fix is plausible and the fix should fit the existing
  codebase, not just make the symptom disappear. Triggers: "remediate this",
  "fix this properly", "what's the most coherent fix", the urge to patch the
  first thing that works, or a fix that bolts on logic the codebase already has
  a pattern for. NOT for trivial one-line fixes with a single obvious fix, and
  NOT for discovering issues (use code-archaeology or bug-hunt).
---

# Remediating Issues

## Overview

Many fixes make a bug go away. Only one fits the codebase. This skill finds that one and defends it.

It wraps `chris-code:coherent-change`, which researches the codebase, defends the most coherent fix against the alternatives and builds it. **REQUIRED:** coherent-change's *Iron Law* (no fix proposed before the codebase is researched and alternatives weighed), *Change Fully, Defer Only the Separable*, and *The Defended Choice* apply here as written, with "fix" for "change". This skill adds what a bug needs on top: pinning the issue before fixing it, the regression gate, closing the issue at its origin, and the batch and per-task variants that SDD and the completion gate use.

**The signature output, every time:** a defended choice for the fix. That artifact is what separates this from "fix the bug and add a test".

## When to Use

- A non-trivial issue from any source: a code-review or audit finding, a GitHub issue, or a problem named in session.
- The fix space is genuinely wide: more than one plausible fix, with a real difference between a coherent one and a hacky one.

**When NOT to use:**
- Trivial one-line fixes with a single obvious fix: nothing to defend.
- Finding issues: use `chris-code:code-archaeology` or `chris-code:bug-hunt`; this skill consumes a known issue.
- Pure refactors with no reported defect: use `chris-code:python-review` / `chris-code:rust-review`.

## Fix Fully, Defer Only the Separable

The fix closes the issue across *every* case its root cause reaches: each sibling branch, producer and input the correctness table lists. No stubs, no silent fallbacks, no "handle the rest in a later phase". Only a genuinely separate, larger improvement (the north-star from the defense) is logged and deferred. The test: **would a reader consider this issue fully closed by the change?**

## The Arc

One issue is the atom; a set of issues is a batch (*Batch Path*).

**1. Frame and pin the issue.** Don't fix a phantom: confirm the problem is real and still open. For a tracked issue, read the code it cites, verify the described behavior still exists, and check whether a fix already landed (`git log -S <symbol>`, weighed against the issue's age). A stale or already-fixed issue is closed *with evidence*, not fixed again. Decide whether the defect is **observable** (a user-visible symptom on a live path) or **inert** (a latent inconsistency nothing currently reaches): both get fixed, but the proof differs (stage 3). Characterize the symptom precisely and define the concrete before/after check that will prove it fixed. **REQUIRED SUB-SKILL:** `chris-code:systematic-debugging`; complete its Phase 1 (root cause) before going further. Where a cheap failing test captures the symptom, write it now; where reproduction is expensive (visual, interactive, integration, performance), pin the symptom exactly and carry the failing check into the close. The point is a defined before/after, not necessarily a unit test.

**2. Build the fix with `chris-code:coherent-change` (build mode).** Hand it the determined fix and the stage-1 before/after check. It researches, defends the most coherent fix (presenting the defended choice at its stage-4 approval checkpoint), implements it through the coder agent, and runs its `*-review-lite` self-gate before handing back a working fix. One bug-specific rule for the engine: **the obvious candidate is the fix the issue itself suggests**, often the over-reaching one. Make it earn the win or show why it loses. In the correctness table, the already-correct cases stay byte-identical, and the implementation plan (part 6) names the `regression-test` coverage and how the origin gets closed.

**3. Close it with the bug gates,** in order:

1. **`chris-code:regression-test` (REQUIRED, the bug gate):** durable coverage of the *specific failure mode*, proven RED on the pre-fix code before staging, by the stash recipe in coherent-change's close (stage 6, step 1). An *inert* defect is proven structurally instead: assert the inconsistency itself is gone. The fix isn't complete until this passes.
2. **Commit the fix, then run `chris-code:verification-before-completion`** (REQUIRED), as coherent-change's close step 2 describes: a PASS with findings is not clean, in-scope findings are fixed in this fix, and the non-trivial set comes back here as a close-gate batch (*Batch Path*), never as one-off patches. A remediation has no separate intent ledger: **the issue text is the ledger**, so the gate's spec-blind intent re-check confirms the reported symptom is observably gone.
3. **`chris-code:finishing-a-development-branch`**: integration (merge / PR / keep / discard).

**4. Record the resolution against the origin.** A GitHub issue: reference it in the commit and close it *with confirmation*. A review or audit finding: mark it addressed. Interactive: confirm with the user.

## Batch Path

A set of issues is a **batch**, not a per-issue fan-out. Triage and rank them, frame each as an observable end-state (the symptom gone: the intent, not a prescribed fix), then hand the whole set to `chris-code:coherent-change` **batch mode**: one consolidated research pass, a defended fix per issue reconciled against that shared map, and the set routed into **one** `chris-code:lean-spec` → **one** `chris-code:lean-plan` → `chris-code:subagent-driven-development`. Each fix's task carries its `chris-code:regression-test` coverage, and origins are recorded at the end. Decomposition and footprint staging are the plan's and SDD's job. Close with one synthesized remediation report.

**Close-gate variant.** When the batch is a `verification-before-completion` close round's non-trivial findings, the gate reports already frame each end-state and the run is mid-close, so stage 1's framing is done; coherent-change's stage-4 approval checkpoint still applies. Only for this variant:
- Skip `lean-spec` (the gate reports are the *what*, the decision doc the *how*) and go straight to one `lean-plan` whose spec references are the decision doc and the report paths.
- Run SDD on the same store, with task numbers continuing after `ledger.py completed`.
- A task carries `regression-test` coverage only for a finding that is a behavioral defect; a design or cohesion finding gets the plan's ordinary tests.
- No origin recording, no separate remediation report, and no `finishing-a-development-branch` at this level: the gate report is the origin, and round 2's re-review at the same report path closes it.
- Close by returning to `verification-before-completion` for round 2, not a fresh round 1. The SDD run's own close is that return, so verification is invoked once.

Every other batch keeps the full `lean-spec` route.

**Per-task variant.** SDD dispatches this variant on opus, only for a holistic round: a task with a serious finding of contract reach, or a coder's `root cause:` concern (`chris-code:subagent-driven-development`, *Constructing Reviewer Dispatches*). The task's coder owns the fix, so the variant is decision-only. It is task-wide: it may reshape the task's implementation, not only patch the cited sites.

- **Run only coherent-change stages 2–4:** batch research over the task's whole diff, every reviewer record from every round, and the coder records, then defended choices that together account for every open finding and concern. It skips this skill's stage 1 (the reviewer records frame each finding, and the coder's TDD supplies the tests).
- **Start with `python3 <scripts-path>/ledger.py findings <output path>`.** It lists every finding id on the reviewer records in the decision's scope (its task, or the whole-change gate), which the decision must account for; any malformed or misfiled record that blocks it; every decision doc already in the store, which it must reconcile with; and the coders' `concerns`. A `root cause:` concern is open work: the decision claims its id, either in a fix choice (fixed in this task) or in an `excluded` entry (deferred, with the evidence for why it belongs elsewhere as the reason).
- **A choice may change another task's file:** it stays this task's fix, and SDD routes that file through its escalated-consumer path.
- **Research means reading** the code each candidate would change and the code it would mirror, not restating the reviewers' probes. Settle every open question by reading: "use X if it exists" or "`f()` or equivalent" handed to the coder is research left undone.
- **No approval checkpoint:** persist the doc immediately and don't ask to proceed. SDD's execution stays continuous, and a task still open after two fix rounds reaches the user in the stage batch. No `lean-spec`, `lean-plan` or origin recording either: every reviewer's re-check is the close.
- **A recurring finding's** choice must read the prior decision doc and say why its mechanism failed, in its `reframe` and in the `reconciled` entry for that doc. **A finding in `introduced_by_fix`** was caused by the previous fix: its choice must say how that fix broke it, from the fix's diff (`ledger.py diff-since` the previous fix baseline) and the coder record's `hunk_map` and `consumers_checked`.

Write the decision doc as one typed record to the output path the dispatch supplies (`task-N-decision-c<cycle>.json`; `final-decision-c<cycle>.json` at the whole-change gate, `final-r2-decision-c<cycle>.json` in a close-gate remediation run; `check` holds the name to the record's `task` and `cycle`). Run `python3 <scripts-path>/ledger.py check <path>` until it exits 0, and return the path. `check` verifies every finding is accounted for, every earlier decision is reconciled, and every precedent exists in the repo outside the store. The holistic fix can't finish until the doc passes, and the coder maps each of its cases to a hunk.

```json
{
  "schema": 2,
  "agent": "remediating-issues",
  "role": "decision",
  "task": 3,
  "status": "decided | escalated",
  "cycle": 2,
  "reviewer_records": ["task-3-spec-reviewer", "task-3-python-quality-reviewer"],
  "choices": [
    {
      "kind": "fix",
      "findings": ["task-3-spec-reviewer#issues[1a2b3c4d]"],
      "reframe": "the facts from research that change the problem",
      "choice": "what changes, what is deleted, what is deliberately left alone",
      "candidates": [
        {"name": "validate under the old type", "precedent": "src/scale.py:120-134", "why": "why it wins", "chosen": true},
        {"name": "validate after translating", "precedent": "src/merge.py:88", "why": "why it loses"}
      ],
      "cases": [
        {"case": "ordinal padding 1.5 to band", "site": "src/scale.py:120", "test": "tests/test_scale.py::test_band_padding_refused", "today": "refused at render", "under_fix": "refused at to_spec()", "result": "fixed"},
        {"case": "merged band keeps its padding", "site": "src/merge.py:88", "test": "tests/test_merge.py::test_merged_band_padding", "today": "padding kept", "under_fix": "padding kept", "result": "unchanged"}
      ],
      "couplings": [{"site": "src/merge.py:88", "effect": "reads the padded value the fix validates"}],
      "premise": {"assumption": "padding is validated before translation", "probe": "what was run or read to confirm it"},
      "completeness": "cases I might be missing, and where I searched for them"
    },
    {"kind": "escalate", "findings": ["task-3-python-quality-reviewer#findings[5e6f7a8b]"], "why": "no reachable fixture for the requested test", "evidence": "what the research showed"}
  ],
  "excluded": [{"finding": "task-3-python-quality-reviewer#findings[9c0d1e2f]", "reason": "trivial: message text, fixed directly"}],
  "reconciled": [{"decision": "task-2-decision-c2", "relation": "how this decision fits that one, or why they don't touch"}]
}
```

- `choices`: one per finding, or per cluster of findings sharing a cause. A `fix` choice carries the defended choice's parts: `reframe`, `choice`, the `cases` table, `couplings`, `premise`, the `completeness` line, and at least two `candidates`, exactly one `chosen`.
  - `candidates`: each cites the code it mirrors as `path:line` or `path:start-end` from the repo root (a line range, not coherent-change's `file:pattern`). The obvious candidate (often the reviewer's suggestion) is one of them, and each loser's `why` is a real rebuttal.
  - `cases`: every case the change touches, unchanged ones included, each with its `site`, the `test` that pins it, and that test's expected result in `under_fix`. A case with no test is a guess left to the coder, and decided items left unbuilt were the main way earlier fixes failed.
  - `couplings`: every other site the choice affects (a caller that reads the changed value, a sibling that shares its rule), each with its `effect`. Each coupling's site must also be a case, so it gets a test: an unnamed coupling is how a fix breaks its neighbor.
  - `premise`: the `assumption` the choice rests on and the `probe` (what you ran or read) that confirmed it. A wrong premise costs the whole round.
- An `escalate` choice is a finding the research shows can't or shouldn't be fixed as asked (no reachable fixture for a requested test, a requirement that conflicts with another), with the evidence. In a task's holistic round the coder contests that finding with this evidence, and the reviewer that raised it concedes or holds it, a hold going to the user; at the whole-change gate's close, SDD escalates it to the user. `status` is `escalated` when any choice is.
- `excluded`: every finding with no choice, and why (a note the coder handles alongside, a finding already settled). A `root cause:` concern listed here is deferred: SDD's triage files it as a follow-up with your reason as its rule, so write a reason a later task can act on. A decision may consist only of exclusions. `cannot_verify` items may be decided too, but needn't be listed.
- `reconciled`: every decision doc written before this one, and how this one relates to it (touching the same code, overlapping, or contradicting). A later decision reconciles with this one, not the reverse. A markdown decision doc from before decisions were records is named by its file stem.

## Rationalizations — All Mean "Do the Research and Write the Defense"

coherent-change's table applies. The bug-specific ones:

| Excuse | Reality |
|--------|---------|
| "It's a small bug, skip the process" | Small bugs with wide fix spaces are the target. Truly single-fix bugs are out of scope; don't invoke here. |
| "The issue already says how to fix it" | That's candidate A. Make it earn the win or show why it loses: the suggested fix is often the over-reaching one. |
| "I'll add the test after the fix" | The before/after check comes first. A test written around a working fix proves nothing about the bug. |
| "A unit test covers it" (for a symptom a unit test can't observe) | If the bug only surfaces through an integration, end-to-end or performance check, that's the proof you owe. |
| "Fix the reported case now, handle the siblings later" | Same-root-cause siblings ship in this fix; the correctness table lists them. Only a separate, larger improvement may be deferred. |

## Red Flags — Stop, You're About to Violate the Discipline

coherent-change's red flags apply. The bug-specific ones:

- You skipped the fix the issue suggested instead of refuting it.
- You're shipping a stub, a fallback, or a "TODO: the rest" for a case the same root cause reaches.
- Your proof is a unit test for a symptom only an integration, end-to-end or performance check can observe.
- You're about to claim "done" without the before/after check flipping or `verification-before-completion` running.
