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

This is the engine `chris-code:remediating-issues` runs for a known issue, and the one `chris-code:systematic-debugging` hands a diagnosed fix off to — both delegate the *build* (research → defend → implement, lite-reviewed) and then run their own close. A design workflow such as `chris-code:lean-spec` instead calls it decision-only, taking only the defended choice for its own plan (see Modes).

## When to Use

- The change is **determined**: you can state it in one sentence and the only live question is *which implementation coheres best*. Refactors, consistency/API alignments, migrations, implementing an already-specced behavior.
- There's an **exemplar to mirror**: existing code or an adopted convention whose patterns should constrain the answer, and you can point at it.

**When NOT to use:**
- **Design-open work** — a feature, a new subsystem, anything where "what should it be?" is still live. Use `chris-code:brainstorming` to settle the design first; once the change is determined it comes back here.
- **No exemplar** — a brand-new codebase with nothing to mirror. Design-open by default → brainstorming.
- A **known bug or issue** is better entered through `chris-code:remediating-issues`, which wraps this engine with diagnosis-framing and issue-origin close-out.

## Modes — Read This First

The mode turns on one question: **does a downstream workflow own implementation?**

**Build (default).** Research → defend → implement → **lite-review self-gate** → hand back. The engine produces a coherent, working, lite-reviewed change and hands it to the caller. It does **not** run the heavyweight close — durable coverage, `verification-before-completion`, `finishing` — that is the caller's responsibility. This is the mode for direct invocation and for fix-oriented front-ends (`chris-code:remediating-issues`, `chris-code:systematic-debugging`), which own their own close. If you were invoked directly, *you* are the caller: run the close after.

**Decision-only (escape hatch).** Research → defend, then stop and hand back the approved defended choice — because a downstream spec → plan → execution workflow (`chris-code:lean-spec`) owns implementation itself. Run **stages 1–4 only**; do **not** implement. The defended choice's implementation + close plan becomes a hand-off note for their plan.

You are in decision-only mode **only** when a downstream workflow owns implementation (lean-spec). Otherwise build.

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

**5. Implement and self-gate.** *(build only)* Dispatch the language-matched coder agent (`chris-code:python-coder` / `rust-coder` / `pytorch-coder`) to make the approved change — the default path, keeping implementation in an isolated context. The coder implements *only* the approved choice: minimal, no "while I'm here" extras. Work in-thread only when the change is too small to be worth a dispatch. Then **verify the coder's work yourself — subagents over-claim:** re-run the tests, `grep` that intended deletions actually happened, and read the changed hunk; trust the diff you've checked, not the agent's summary. Before handing back, run the **`*-review-lite` gate** (`python-review-lite` / `rust-review-lite`) on the staged diff — the fast, diff-level guarantee that you never ship broken or sloppy code to the caller. It must come back clean.

**6. Hand back — the caller closes.** *(build only)* Confirm the before/after check from stage 1 passes (it must fail without the change and pass with it; where a unit test cannot observe the result, use the domain-appropriate proof — an integration assertion, a golden/visual capture, a benchmark). Then hand back the implemented, lite-reviewed change. The heavyweight **close is the caller's**, in order:

1. **Durable coverage, proven RED — before staging.** The behavior is locked in with tests that fail without the change and pass with it. Run the RED proof while the fix is still unstaged: `git stash push -- <changed source>` → the test fails → `git stash pop` → then `git add` once. (`git stash pop` restores the working tree but **not** the index, so stashing *after* `git add` silently un-stages the fix and it drops from the commit; recover with `git stash pop --index`.) A bug-oriented caller (`chris-code:remediating-issues`, `chris-code:systematic-debugging`) uses `chris-code:regression-test` for the *specific failure mode*; new behavior uses `chris-code:test-driven-development`.
2. **`chris-code:verification-before-completion`** — tests, lint, and the language-matched `python-design-reviewer` / `rust-design-reviewer` cohesion gate. A PASS is not "nothing to do": it can carry findings, and **PASS-with-findings is not clean.** Verify each finding is real (`chris-code:receiving-code-review` — don't reflexively obey or dismiss), then apply *Change Fully, Defer Only the Separable* to it: an **in-scope** finding (introduced by this change, or needed to make it correct) gets fixed *in this change*; only a **separable**, larger improvement is logged and deferred. Shipping an in-scope finding as "TODO: fix later" defeats the gate.
3. **`chris-code:finishing-a-development-branch`** — integration (merge / PR / keep / discard).

If you were invoked **directly**, you are the caller — run this close yourself. If a front-end called you, it owns the close.

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

**6. Implementation + close plan.** Who implements (coder agent) and the lite-review self-gate, then the caller's close: durable coverage / domain-appropriate proof, the `chris-code:verification-before-completion` gate (design-reviewer must PASS), and `chris-code:finishing-a-development-branch` for landing. In decision-only mode the whole plan is a hand-off note for the caller, not yours to execute.

Then ask to proceed (build) or hand back (decision-only).

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
- You're about to hand back without the before/after check flipping or the `*-review-lite` gate running.
