---
name: coherent-change
description: >
  Use when making a *determined* change — one whose intended behavior is already
  settled, and the only open question is which implementation best fits the
  existing codebase. Triggers: a refactor, an API/consistency alignment, a
  migration, "implement this the way this codebase would", or the urge to invent
  an approach without checking how the codebase already solves it. NOT for
  design-open work where "what to build" is still live (use brainstorming), and
  NOT when there is no existing code or convention to mirror (greenfield → brainstorming).
---

# Coherent Change

## Overview

Once a change is *determined* — its intended behavior settled — there are still many ways to implement it. Only one fits the codebase. This skill exists to find that one and defend it.

**Core principle:** the change is *discovered from existing code*, *chosen against alternatives*, and *proven*. An implementation that works but bolts on logic the codebase already has a pattern for is debt, not a coherent change.

**The signature output, produced every time:** a defended choice — every genuine candidate rooted in how this codebase already solves the problem, the one you selected, proof it's correct across *all* affected cases, and why it beats the others on reuse, idiom-fit, contract-preservation, least surprise, and end-user ergonomics.

This is the engine `chris-code:remediating-issues` runs for a known issue, and the one `chris-code:systematic-debugging` hands a diagnosed fix off to — both own their front-end and delegate the whole build, so the engine carries it end to end. A design workflow such as `chris-code:lean-spec` can instead call it decision-only, taking only the defended choice for its own plan (see Modes).

## When to Use

- The change is **determined**: you can state it in one sentence and the only live question is *which implementation coheres best*. Refactors, consistency/API alignments, migrations, implementing an already-specced behavior.
- There's an **exemplar to mirror**: existing code or an adopted convention whose patterns should constrain the answer, and you can point at it.

**When NOT to use:**
- **Design-open work** — a feature, a new subsystem, anything where "what should it be?" is still live. Use `chris-code:brainstorming` to settle the design first; once the change is determined it comes back here.
- **No exemplar** — a brand-new codebase with nothing to mirror. Design-open by default → brainstorming.
- A **known bug or issue** is better entered through `chris-code:remediating-issues`, which wraps this engine with diagnosis-framing and issue-origin close-out.

## Modes — Read This First

The mode turns on one question: **does a downstream workflow own the build?** Not "who invoked you" — what owns the implementation.

**Carry-through (default).** You own the change end to end: run the full arc through implement → verify → close. This is the mode for direct invocation **and** for when a fix-oriented front-end (`chris-code:remediating-issues`, `chris-code:systematic-debugging`) hands you a determined change — they own the framing or diagnosis, you own the build.

**Decision-only (escape hatch).** You stop at the approved defended choice and hand it back, because a downstream spec → plan → execution workflow owns the build. This is the mode when a design workflow such as `chris-code:lean-spec` calls you at its propose-approaches step. Run **stages 1–4 only**; the defended choice's implementation + verification plan becomes a hand-off note for their plan. Do **not** implement, verify, or close — that would collide with their workflow.

You are in decision-only mode **only** if a spec/plan/execution workflow downstream owns the build. Otherwise carry through — including when remediating-issues or systematic-debugging delegated the change to you.

## The Iron Law

```
NO IMPLEMENTATION IS PROPOSED BEFORE THE CODEBASE HAS BEEN
RESEARCHED AND ALTERNATIVES HAVE BEEN WEIGHED.
```

The first approach that works is a candidate, never the conclusion. If you can name only one, you have not finished the research.

## Change Fully, Defer Only the Separable

The change must close its scope across *every* case its intent reaches — each sibling branch, producer, and input the correctness table lists. No stubs, no silent fallbacks, no "handle the rest in a later phase." Partial coverage dressed as done is the incoherence this skill exists to prevent.

This is not a ban on follow-ups. A genuinely *separate, larger* improvement — the north-star from the defense — is logged and deferred, because the current change already closes its scope without it. The line: **would a reader consider this change fully done?** "Mostly, except the siblings / a stub / a fallback" is banned deferral. "Yes, and there's a bigger orthogonal refactor for someday" is a legitimate follow-up.

## The Arc

Work the determined change through these stages. (Decision-only mode stops after stage 4.)

**1. Frame the determined change.** Confirm it's *determined*, not design-open: if "what should this be?" is still live, stop — that's `chris-code:brainstorming`'s job, not this skill's. State the change in one sentence, name the exemplar(s) you'll mirror, and define the concrete before/after check that proves it done. (If a front-end — remediating-issues, systematic-debugging, or lean-spec — handed you the change, this is already settled; confirm and proceed.) Where a cheap check captures "done", write it now; where it's expensive (visual, interactive, integration, performance), pin it exactly and carry it into the verification plan.

**2. Research the codebase.** The load-bearing stage; the coherent implementation is *discovered here*, not invented. Dispatch parallel `Explore` agents to inventory it in one pass — every producer and consumer of the thing you're changing, how the affected path works end to end, and the repo's idioms for this class of change — and keep the main context clean. Good research surfaces the few facts that *reframe* the problem: what's actually in scope, what's irrelevant, where the real boundary sits. Read before you propose.

**3. Generate every genuine candidate.** Usually two to four, each rooted in something the codebase already does and cited to a concrete precedent (`file:pattern`). **Include the obvious approach** so the defense can show why it loses. If only one comes to mind, return to stage 2; you don't yet know the options.

**4. Select and defend.** Choose the most coherent and ergonomic candidate and write the defended choice (canonical structure below). **Present it — with the implementation and verification plan — and get approval before changing code.** This is the single human checkpoint. **Decision-only mode ends here:** return the approved defended choice to the caller and stop.

**5. Implement.** *(carry-through only)* Dispatch the language-matched coder agent (`chris-code:python-coder` / `rust-coder` / `pytorch-coder`) to make the approved change — the default path, keeping implementation in an isolated context. The coder implements *only* the approved choice: minimal, no "while I'm here" extras. Work in-thread only when the change is too small to be worth a dispatch. Then **verify the coder's work yourself — subagents over-claim.** Re-run the tests, `grep` that intended deletions actually happened, and read the changed hunk; trust the diff you've checked, not the agent's summary.

**6. Prove and close.** *(carry-through only)* Run the before/after check from stage 1: it must fail without the change and pass with it. Where a unit test cannot observe the result, match the proof to what the change actually affects (an integration assertion, a golden/visual capture, a benchmark). Then, in order:

1. **Durable coverage, proven RED without the change.** Ensure the change has test coverage that fails without it and passes with it — write it test-first where you can (`chris-code:test-driven-development`). Prove it's real: temporarily revert the change (`git stash push -- <changed source>`), watch the test fail, then restore (`git stash pop`). A test never seen failing proves nothing. A fix-oriented front-end (remediating-issues, systematic-debugging) additionally runs `chris-code:regression-test` here, to cover the *specific failure mode* rather than just the new behavior.
2. **`chris-code:verification-before-completion`** (REQUIRED) — runs tests and lint, and dispatches the language-matched read-only **review agent** (`python-design-reviewer` / `rust-design-reviewer`). That senior cohesion/drift pass is the right final gate for a change whose whole point is fitting the codebase. Verdict must be PASS.
3. **`chris-code:finishing-a-development-branch`** — integration (merge / PR / keep / discard).

## The Defended Choice

The signature artifact, presented at the stage-4 checkpoint before any code changes — and the deliverable handed back in decision-only mode. Mirror this structure:

**1. Reframe.** The two or three facts from research that change the problem: what's in scope, what's irrelevant, where the real boundary sits.

**2. Proposed change.** Concrete and minimal: what changes, what gets deleted, what is deliberately left untouched.

**3. Correct across every affected case.** A table over *all* cases the change touches, not just the obvious one, showing it's right for each — and that the already-correct cases stay unchanged. This is how a coherent change proves it isn't over-reaching.

| Case | Today | Under the change | Result |
|------|-------|------------------|--------|
| …    | …     | …                | changed / unchanged |

**4. Why it's the most coherent and user-friendly choice.** Cover: reuse (which existing helper or abstraction it leans on), idiom-fit, whether it *mirrors an existing strategy* in the codebase, contract-preservation, smallest correct blast radius, project-constraint fit (cite `CLAUDE.md` where relevant), and the end-user / API payoff.

**5. Defense against the alternatives.** Every rejected candidate gets a real rebuttal, not a line: *why* it is non-exhaustive, over-reaching, disproportionate, or paradigm-violating. Distinguish the right-but-disproportionate north-star from the proportionate-now choice, and **log the north-star as a follow-up** rather than dismissing it.

**6. Implementation + verification plan.** Who implements (coder agent), the test(s) and the domain-appropriate proof, the durable coverage, and how it lands. In decision-only mode this is a hand-off note for the caller's plan, not yours to execute.

Then ask to proceed (carry-through) or hand back (decision-only).

## Rationalizations — All Mean "Do the Research and Write the Defense"

| Excuse | Reality |
|--------|---------|
| "The first approach works, ship it" | Working ≠ coherent. An implementation that ignores existing patterns is debt the next reader pays. |
| "There's only one way to do this" | Usually means stage 2 was skipped. Read the siblings before deciding. |
| "Defending alternatives is busywork" | The defense *is* the deliverable. It's what makes the choice trustworthy and reviewable. |
| "The 'what' is still a bit open" | Then you're in the wrong skill — settle the design in brainstorming first. |
| "I'll add the test after" | The before/after check comes first. A test written around a working change proves nothing. |
| "Handle the obvious case now, siblings later" | Same-intent siblings ship in this change — the correctness table lists them. Only a separate, larger improvement may be deferred. |
| "One-line rejections are enough" | The rejection reasoning *is* the deliverable. A real rebuttal per alternative is what makes the choice trustworthy. |

## Red Flags — Stop, You're About to Violate the Discipline

- You typed an approach before dispatching research or reading a sibling implementation.
- You can name only one candidate.
- Your change introduces a helper the codebase already provides.
- You rejected an alternative without saying why it's less coherent.
- You're implementing or closing while in decision-only mode — the caller owns that.
- You're about to claim "done" without the before/after check flipping or `verification-before-completion` running.
