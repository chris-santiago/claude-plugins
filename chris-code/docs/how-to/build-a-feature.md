# Build a new feature

Use this for **design-open** work — a feature or subsystem where *what to build* is still live. If the behavior is already settled and only the implementation is open, use [make a determined change](make-a-determined-change.md) instead.

## Steps

1. **Start with intent:** `/brainstorming`. It's a hard gate — no code until a design is approved. Answer its questions (one at a time), pick an approach, approve the design. It freezes a small **intent ledger** (≤7 acceptance statements in your words) — confirm it.
2. **Spec, then plan.** `lean-spec` writes a contracts-only design; `lean-plan` writes a what/where execution handoff. Review the spec when prompted.
3. **Execution.** `subagent-driven-development` dispatches a coder per task — each brief carrying the task's intent — and runs spec → quality → commit-lite gates per task, staged by file footprint.
4. **Verify.** `verification-before-completion`: tests → lints → design review → requirements → the spec-blind intent re-check.
5. **Finish.** `finishing-a-development-branch`: merge / PR / keep / discard.

## You have now

Shipped a feature that was designed before it was coded, executed by focused agents, reviewed at every gate, and checked back against your original ask before being called done.
