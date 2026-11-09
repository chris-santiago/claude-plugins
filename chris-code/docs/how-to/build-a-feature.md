# Build a new feature

Use this for **design-open** work — a feature or subsystem where *what to build* is still live. If the behavior is already settled and only the implementation is open, use [make a determined change](make-a-determined-change.md) instead.

## Steps

1. **Start with intent:** `/brainstorming`. It's a hard gate — no code until a design is approved. Answer its questions (one at a time), pick an approach, approve the design. It freezes a small **intent ledger** (≤7 acceptance statements in your words) — confirm it.
2. **Spec, then plan.** `lean-spec` writes a contracts-only design; `lean-plan` writes a what/where execution handoff. Review the spec when prompted.
3. **Execution.** `subagent-driven-development` dispatches a coder per task — each brief carrying the task's intent — and runs spec + quality review, a scripted triage and a commit gate per task, staged by file footprint. Reviewers tag each finding with severity and reach: minor ones ride along without a re-review, serious ones get a patch round, and serious ones that reach a contract get a researched task-wide decision doc before the fix. A task gets at most two rounds, then one batched question per stage, and cross-task notes reach each brief from the run's store. For small work, `executing-plans` is the lighter path.
4. **Verify.** `verification-before-completion`: tests → lints, then one [close](../explanation/execution-mechanics.md#the-close) that runs design review, the spec-blind intent re-check, and (if you choose it) the mutation re-check together, with `ledger.py triage --task close` routing their findings. Blocking findings (an intent not-met, an S4+ finding) are fixed in place and re-checked; the rest is filed for the close batch; after two fix rounds, anything still blocking comes to you. Open questions and owed doc disclosures are settled before the close starts, and the completion report is built from the run's store.
5. **Finish.** `finishing-a-development-branch`: merge / PR / keep / discard. It reports the run's open follow-ups before cleaning up.

## You have now

Shipped a feature that was designed before it was coded, executed by focused agents, reviewed at every gate, and checked back against your original ask before being called done.
