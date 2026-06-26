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

Many fixes make a bug go away. Only one fits the codebase. This skill exists to find that one and defend it.

**Core principle:** the fix is *discovered from nearby code*, *chosen against alternatives*, and *proven*. A fix that works but bolts on logic the codebase already has a pattern for is debt, not a remediation.

**The signature output, produced every time:** a defended choice. Every genuine candidate fix rooted in how this codebase already solves the problem, the one you selected, proof it's correct across *all* affected cases, and why it beats the others on reuse, idiom-fit, contract-preservation, least surprise, and end-user ergonomics. That artifact is what separates this from "fix the bug and add a test."

## When to Use

- A non-trivial issue from any source: a code-review or audit finding, a GitHub issue, or a problem named in session.
- The fix space is genuinely wide: more than one plausible way to fix it, and the difference between a coherent fix and a hacky one is real.

**When NOT to use:**
- Trivial one-line fixes with a single obvious fix. Nothing to defend, no reason to invoke.
- Finding or discovering issues. Use `chris-code:code-archaeology` or `chris-code:bug-hunt`; this skill consumes a known issue.
- Pure refactors with no reported defect. Use `chris-code:python-review` / `chris-code:rust-review`.

## The Iron Law

```
NO FIX IS PROPOSED BEFORE THE CODEBASE HAS BEEN RESEARCHED
AND ALTERNATIVES HAVE BEEN WEIGHED.
```

The first fix that works is a candidate, never the conclusion. If you can name only one fix, you have not finished the research.

## Fix Fully, Defer Only the Separable

The fix must close the issue across *every* case its root cause reaches — each sibling branch, producer, and input the correctness table lists. No stubs, no silent fallbacks, no "handle the rest in a later phase." Partial coverage dressed as a fix is exactly the symptom-patching this skill exists to prevent.

This is not a ban on follow-ups. A genuinely *separate, larger* improvement — the north-star refactor from the defense — is logged and deferred, because the current fix already closes the issue without it. The line: **would a reader consider this issue fully closed by the change?** "Mostly, except the siblings / a stub / a fallback" is banned deferral. "Yes, and there's a bigger orthogonal refactor for someday" is a legitimate follow-up.

## The Arc

One issue is the atom. Work it through these stages. (A set of issues is just fan-out; see Batch Path.)

**1. Frame and pin the issue.** First, don't fix a phantom: confirm the problem is *real and still open*. For a tracked issue, read the code it cites and verify the described behavior still exists, and check whether a fix already landed (`git log -S <symbol>`, weighed against the issue's age). A stale or already-fixed issue is closed *with evidence*, not fixed again. Then decide whether the defect is **observable** (a user-visible symptom on a live path) or **inert** (a latent inconsistency nothing currently reaches) — both get fixed, but the proof differs (step 3 below). Characterize the symptom precisely and define the concrete before/after check that will prove it fixed. **REQUIRED SUB-SKILL:** `chris-code:systematic-debugging` — complete its Phase 1 (root cause) before going further. Where a cheap failing test captures the symptom, write it now; where reproduction is expensive (visual, interactive, integration, performance), pin the symptom exactly and carry the failing check into the close (step 3). The point is a defined before/after, not necessarily a unit test.

**2. Build the fix with `chris-code:coherent-change` (build mode).** Hand it the determined fix and the before/after check from stage 1. The engine researches the codebase, generates grounded candidates, defends the most coherent fix against the alternatives (the defended choice below), implements it via the coder agent, and runs its `*-review-lite` self-gate before handing back a working fix. One bug-specific note for the engine: **the obvious candidate is the fix the issue itself suggests** — often the over-reaching one; make it earn the win or show why it loses.

**3. Close it — the bug gates.** With the lite-reviewed fix in hand, run the close in order:

1. **`chris-code:regression-test` (REQUIRED — the mandatory bug gate).** Durable coverage of the *specific failure mode*, proven RED on the pre-fix code. Run the proof **before staging**, while the fix is still unstaged: `git stash push -- <changed source>` → it fails → `git stash pop` → then `git add` once. (`git stash pop` restores the working tree but **not** the index, so stashing *after* `git add` silently un-stages the fix and it drops from the commit; recover with `git stash pop --index`.) An *inert* defect (no observable symptom, per stage 1) is instead proven structurally — assert the inconsistency itself is gone. The fix is not complete until this passes.
2. **`chris-code:verification-before-completion`** (REQUIRED) — tests, lint, and the `python-design-reviewer` / `rust-design-reviewer` cohesion gate. A PASS can carry findings, and **PASS-with-findings is not clean**: verify each is real (`chris-code:receiving-code-review`), then apply *Fix Fully, Defer Only the Separable* — fix the **in-scope** findings *in this fix*, defer only a separable, larger improvement. Shipping a flagged in-scope finding as "fix later" defeats the gate. There is no separate intent ledger for a remediation: the **issue text is the ledger**, so the gate's spec-blind intent re-check (Step 5) confirms the originally-reported symptom is observably gone.
3. **`chris-code:finishing-a-development-branch`** — integration (merge / PR / keep / discard).

**4. Record the resolution against the origin.** GitHub → reference in the commit and close it *with confirmation*; review/audit finding → mark it addressed; interactive → confirm with the user.

## The Defended Choice

The signature artifact, presented at the stage-4 checkpoint before any code changes. Mirror this structure — it is what the canonical remediation produces:

**1. Reframe.** The two or three facts from research that change the problem: what's actually in scope, what's irrelevant to the goal, where the real boundary sits.

**2. Proposed fix.** Concrete and minimal: what changes, what gets deleted, what is deliberately left untouched.

**3. Correct across every affected case.** A table over *all* cases the change touches, not just the reported one, showing the fix is right for each — and that the already-correct cases stay byte-identical. This is how a coherent fix proves it isn't over-reaching.

| Case | Today | Under the fix | Result |
|------|-------|---------------|--------|
| …    | …     | …             | fixed / unchanged |

**Completeness — required line under the table:** *cases I might be missing, and how I'd find them.* Name where you searched for same-root-cause siblings, producers, and inputs (the `grep`, the call-site scan, the type's consumers) and what would surface one you overlooked. A table listing only the cases you already found proves coverage of those, not of the bug's full reach.

**4. Why it's the most coherent and user-friendly choice.** Cover: reuse (which existing helper or abstraction it leans on), idiom-fit, whether it *mirrors an existing strategy* elsewhere in the codebase, contract-preservation, smallest correct blast radius, project-constraint fit (cite `CLAUDE.md` where relevant), and the end-user / API payoff.

**5. Defense against the alternatives.** Every rejected candidate (A/B/C/D…) gets a real rebuttal, not a line: *why* it is non-exhaustive, over-reaching, disproportionate, or paradigm-violating. Distinguish the right-but-disproportionate north-star fix from the proportionate-now choice, and **log the north-star as a follow-up** rather than dismissing it.

**6. Implementation + verification plan.** Who implements (coder agent), the test(s) and the domain-appropriate proof, `regression-test`, and how the origin gets closed.

Then ask to proceed.

## Batch Path

One issue is the atom; a set is fan-out. Triage all issues, rank them, and footprint each by the files it touches. Issues with no file overlap fan out to coder agents in parallel (the `chris-code:subagent-driven-development` staging pattern); overlapping issues serialize. Each issue still runs its own frame → build → close. Close with one synthesized remediation report.

## Rationalizations — All Mean "Do the Research and Write the Defense"

| Excuse | Reality |
|--------|---------|
| "The first fix works, ship it" | Working ≠ coherent. A fix that ignores existing patterns is debt the next reader pays. |
| "There's only one way to fix this" | Usually means stage 2 was skipped. Read the siblings before deciding. |
| "Defending alternatives is busywork" | The defense *is* the deliverable. It's what makes the fix trustworthy and reviewable. |
| "It's a small bug, skip the process" | Small bugs with wide fix-spaces are the target. Truly single-fix bugs are out of scope — don't invoke here. |
| "I'll add the test after the fix" | The before/after check comes first. A test written around a working fix proves nothing about the bug. |
| "The issue already says how to fix it" | That's candidate A. Make it earn the win or show why it loses — the suggested fix is often the over-reaching one. |
| "One-line rejections are enough" | The rejection reasoning *is* the deliverable. A real rebuttal per alternative is what makes the choice trustworthy. |
| "A unit test covers it" (for a symptom a unit test can't observe) | If the bug only surfaces through an integration, end-to-end, or performance check, that's the proof you owe. |
| "Fix the reported case now, handle the siblings later" | Same-root-cause siblings ship in this fix — the correctness table lists them for a reason. Only a separate, larger improvement may be deferred. |

## Red Flags — Stop, You're About to Violate the Discipline

- You typed a fix before dispatching research or reading a sibling implementation.
- You can name only one candidate, or you skipped the fix the issue suggested instead of refuting it.
- Your fix introduces a helper the codebase already provides.
- You're shipping a stub, a fallback, or a "TODO: the rest" for a case the same root cause reaches.
- You rejected an alternative without saying why it's less coherent.
- Your proof is a unit test for a symptom only an integration, end-to-end, or performance check can observe.
- You're about to claim "done" without the before/after check flipping or `verification-before-completion` running.
