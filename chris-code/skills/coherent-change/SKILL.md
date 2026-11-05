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

Once a change is *determined* (its intended behavior settled), there are still many ways to implement it, and only one fits the codebase. This skill finds that one and defends it.

**Core principle:** the change is *discovered from existing code*, *chosen against alternatives*, and *proven*. An implementation that works but bolts on logic the codebase already has a pattern for is debt, not a coherent change.

**The signature output, every time:** a defended choice. Every genuine candidate rooted in how this codebase already solves the problem, the one you selected, proof it's correct across *all* affected cases, and why it beats the others on reuse, idiom-fit, contract-preservation, least surprise and end-user ergonomics.

**Save the defended choice to** `.claude/output/decisions/YYYY-MM-DD-<topic>-decision.md` on approval, in every mode, as `lean-spec` and `lean-plan` persist theirs. (`remediating-issues`' per-task variant writes to the store path its dispatch supplies instead.) It is the durable record of why this implementation beat the alternatives, and what a downstream `lean-spec` or `lean-plan` reads instead of re-deriving the choice. It is distinct from the brainstorming intent ledger in `.claude/output/intent/`, which records the original ask.

**Who calls it.** `chris-code:remediating-issues` runs this engine for a known issue, and `chris-code:systematic-debugging` hands it a diagnosed fix; both use it to build (research → defend → implement, lite-reviewed) and run their own close. A design workflow such as `lean-spec` calls it decision-only, for the defended choice alone. On direct invocation it sizes the change at the approval checkpoint: a single coherent edit it builds and hands back; a major, multi-task change it routes into spec → plan → execution. A *set* of changes (an audit's or review's findings) it batches (see *Modes*).

## When to Use

- The change is **determined**: you can state it in one sentence, and the only live question is which implementation coheres best. Refactors, consistency or API alignments, migrations, implementing already-specced behavior.
- There's an **exemplar to mirror**: existing code or an adopted convention you can point at, whose patterns should constrain the answer.
- A **set** of determined changes at once (an audit's or review's findings, a batch of issues): run them in batch mode.

**When NOT to use:**
- **Design-open work** (a feature, a new subsystem, anything where "what should it be?" is still live): settle the design with `chris-code:brainstorming` first; once determined, the change comes back here.
- **No exemplar** (a brand-new codebase with nothing to mirror): design-open by default, so brainstorming.
- A **known bug or issue** is better entered through `chris-code:remediating-issues`, which wraps this engine with diagnosis framing and issue-origin close-out.

## Modes — Read This First

Every invocation researches and defends (stages 1–4). What happens after the defended choice turns on two questions: does a downstream workflow already own implementation, and is the change small enough to build inline?

**Build (the default).** Research → defend → implement → **lite-review self-gate** → hand back a coherent, working, lite-reviewed change. The engine does **not** run the heavyweight close (durable coverage, `verification-before-completion`, `finishing`); that is the caller's. This is the mode for direct invocation and for fix-oriented front-ends (`remediating-issues`, `systematic-debugging`) **when the change is a single coherent edit**, small enough for one coder dispatch. Invoked directly, *you* are the caller: run the close after.

**Decision-only.** Research → defend, then **stop without implementing** and hand the approved defended choice, by its saved path, to the workflow that owns the build. Run stages 1–4 only. Two situations:

- **A downstream workflow owns implementation:** `lean-spec` called you for a determined section-8 decision, or `remediating-issues` ran its per-task variant for an SDD task's findings. That variant runs stages 2–4 only, with no approval checkpoint and no route sizing (the task's coder is the route), and writes only the decision doc at the store path its dispatch supplies; see that skill.
- **The change is too large to build inline:** even on direct invocation, a major determined change (many files, independent sub-units, staged work) is settled *what* and *why*, like a brainstorming design. Route the defended choice into `chris-code:lean-spec` → `chris-code:lean-plan` → `chris-code:subagent-driven-development`; it is the spec's input (its reframe the context, its proposed change the work, its correctness table the footprint map for staging).

**Choosing the route.** At the stage-4 checkpoint, read the scale off the correctness table and recommend: build inline for a single coherent edit, planned execution for a major or multi-task change. The user confirms. When in doubt, recommend planned execution: building a major change inline is the failure this split exists to prevent.

**Batch mode (a set of determined changes).** Don't run them one at a time. Research the affected subsystem in **one consolidated pass**, then write a defended choice per change, reconciled against that shared map so conflicts between changes surface. A batch is inherently major, so it **always** takes planned execution: persist the defended choices together in **one** `.claude/output/decisions/YYYY-MM-DD-<batch-topic>-decision.md` and route the whole set into **one** `lean-spec` → **one** `lean-plan` → `subagent-driven-development`, with no per-change build or close (decomposition and staging are the plan's and SDD's job). Each change needs only an observable **end-state**, not a prescribed fix: finding the method stays the engine's job. A bug set arrives through `remediating-issues`, which folds regression coverage and origin recording into that one plan and has two variants that change this route (its close-gate variant skips `lean-spec`; its per-task variant stops at the decision doc).

## The Iron Law

```
NO IMPLEMENTATION IS PROPOSED BEFORE THE CODEBASE HAS BEEN
RESEARCHED AND ALTERNATIVES HAVE BEEN WEIGHED.
```

The first approach that works is a candidate, never the conclusion. If you can name only one, the research isn't finished.

## Change Fully, Defer Only the Separable

The change must close its scope across *every* case its intent reaches: each sibling branch, producer and input the correctness table lists. No stubs, no silent fallbacks, no "handle the rest in a later phase". Partial coverage dressed as done is the incoherence this skill exists to prevent.

Follow-ups aren't banned. A genuinely *separate, larger* improvement (the north-star from the defense) is logged and deferred, because the change already closes its scope without it. The test: **would a reader consider this change fully done?** "Mostly, except the siblings / a stub / a fallback" is banned deferral; "yes, and there's a bigger orthogonal refactor for someday" is a legitimate follow-up.

## The Arc

Work the change through these stages. Decision-only mode stops after stage 4.

**1. Frame the determined change.** Confirm it's determined: if "what should this be?" is still live, stop and use `chris-code:brainstorming`. State the change in one sentence, name the exemplar(s) you'll mirror, and define the concrete before/after check that proves it done. (When a front-end such as `remediating-issues`, `systematic-debugging` or `lean-spec` handed you the change, this is settled: confirm and proceed.) Where a cheap check captures "done", write it now; where it's expensive (visual, interactive, integration, performance), pin it exactly and carry it into the verification plan.

**2. Research the codebase.** The load-bearing stage: the coherent implementation is discovered here, not invented. Dispatch parallel `Explore` agents to inventory, in one pass, every producer and consumer of what you're changing, how the affected path works end to end, and the repo's idioms for this class of change, keeping the main context clean. Good research surfaces the few facts that *reframe* the problem: what's actually in scope, what's irrelevant, where the real boundary sits. Read before you propose.

**3. Generate every genuine candidate.** Usually two to four, each rooted in something the codebase already does and cited to a concrete precedent (`file:pattern`). **Include the obvious approach** so the defense can show why it loses. If only one comes to mind, return to stage 2.

**4. Select and defend.** Choose the most coherent and ergonomic candidate and write the defended choice (*The Defended Choice*). **Present it, with the implementation and verification plan, and get approval before changing code.** This is the single human checkpoint; only `remediating-issues`' per-task variant skips it, persisting straight to its output path and handing back without asking. **On approval, persist it** to `.claude/output/decisions/YYYY-MM-DD-<topic>-decision.md` before anything else, so the record exists whichever route follows. **Size the change and recommend the route** (*Modes*): a single coherent edit builds inline (stage 5); a major change routes, on the user's confirmation, to `lean-spec` → `lean-plan` → `subagent-driven-development` with the saved doc as the spec's input. **Decision-only ends here:** hand back the saved decision doc and stop.

**5. Implement and self-gate** (build only, for a single coherent edit). Dispatch the language-matched coder (`chris-code:python-coder` / `rust-coder` / `pytorch-coder`) to make the approved change in its own context; work in-thread only when the change is too small to be worth a dispatch. The coder implements *only* the approved choice: minimal, no "while I'm here" extras. Then **verify its work yourself, since subagents over-claim:** re-run the tests, `grep` that intended deletions happened, and read the changed hunk. Before handing back, run the **`*-review-lite` gate** (`python-review-lite` / `rust-review-lite`) on the staged diff; it must come back clean.

**6. Hand back; the caller closes** (build only). Confirm the stage-1 before/after check passes: it must fail without the change and pass with it. Where a unit test can't observe the result, use the proof the change needs (an integration assertion, an end-to-end check, a performance check). Then hand back the implemented, lite-reviewed change. The heavyweight **close is the caller's**, in order:

1. **Durable coverage, proven RED, before staging.** Lock the behavior in with tests that fail without the change and pass with it. Run the RED proof while the fix is still unstaged: `git stash push -- <changed source>` → the test fails → `git stash pop` → then `git add` once. (`git stash pop` restores the working tree but **not** the index, so stashing *after* `git add` silently un-stages the fix and drops it from the commit; recover with `git stash pop --index`.) A bug-oriented caller (`remediating-issues`, `systematic-debugging`) uses `chris-code:regression-test` for the specific failure mode; new behavior uses `chris-code:test-driven-development`.
2. **Commit the change**, then run **`chris-code:verification-before-completion`**, whose gates review committed HEAD: tests, lint, and the language-matched design-reviewer cohesion gate. **A PASS with findings is not clean.** Verify each finding is real (`chris-code:receiving-code-review`: don't reflexively obey or dismiss), then apply *Change Fully, Defer Only the Separable*: an in-scope finding (introduced by this change, or needed to make it correct) is fixed *in this change*; only a separable, larger improvement is logged and deferred. Shipping an in-scope finding as "TODO: fix later" defeats the gate. Fixing follows that skill's close round: findings are batched and triaged once, and the non-trivial set goes through `remediating-issues` as one close-gate batch, not one patch at a time.
3. **`chris-code:finishing-a-development-branch`**: integration (merge / PR / keep / discard).

Invoked directly, you are the caller and run this close yourself; when a front-end called you, it owns the close.

## The Defended Choice

The signature artifact: presented at the stage-4 checkpoint before any code changes, persisted to `.claude/output/decisions/` on approval, and the deliverable in decision-only mode. Mirror this structure:

**1. Reframe.** The two or three facts from research that change the problem: what's in scope, what's irrelevant, where the real boundary sits.

**2. Proposed change.** Concrete and minimal: what changes, what is deleted, what is deliberately left untouched.

**3. Correct across every affected case.** A table over *all* cases the change touches, not just the obvious one, showing it's right for each and that already-correct cases stay unchanged. This is how a coherent change proves it isn't over-reaching.

| Case | Today | Under the change | Result |
|------|-------|------------------|--------|
| …    | …     | …                | changed / unchanged |

**Completeness, a required line under the table:** *cases I might be missing, and how I'd find them.* Name where you searched for siblings, producers and inputs (the `grep`, the call-site scan, the type's consumers) and what would surface one you overlooked. A table of the cases you already found proves coverage of those, not of the change's full reach.

**4. Why it's the most coherent and user-friendly choice.** Reuse (the existing helper or abstraction it leans on), idiom-fit, whether it *mirrors an existing strategy* in the codebase, contract preservation, the smallest correct blast radius, project-constraint fit (cite `CLAUDE.md` where relevant), and the end-user or API payoff.

**5. Defense against the alternatives.** Every rejected candidate gets a real rebuttal, not a line: *why* it is non-exhaustive, over-reaching, disproportionate or paradigm-violating. Distinguish the right-but-disproportionate north-star from the proportionate-now choice, and **log the north-star as a follow-up** rather than dismissing it. Inside an SDD run the orchestrator files it as a `follow-up` note (subagent-driven-development's *Run Notes*); a decision-only run names it in the defense and leaves the filing to the orchestrator. Otherwise the defense is the record.

**6. Implementation and close plan.** Name the execution route first (*Modes*). *Inline build:* who implements (the coder agent) and the lite-review self-gate, then the caller's close: durable coverage or the domain-appropriate proof, `verification-before-completion` (the design reviewer must PASS), and `finishing-a-development-branch`. *Planned execution:* route to `lean-spec` → `lean-plan` → `subagent-driven-development`. In decision-only mode the plan is a hand-off note, not yours to execute.

Then ask to proceed (build) or hand back (decision-only). The per-task variant hands back without asking.

## Rationalizations — All Mean "Do the Research and Write the Defense"

| Excuse | Reality |
|--------|---------|
| "The first approach works, ship it" | Working ≠ coherent. An implementation that ignores existing patterns is debt the next reader pays. |
| "There's only one way to do this" | Usually means stage 2 was skipped. Read the siblings before deciding. |
| "Defending alternatives is busywork" | The defense *is* the deliverable. It's what makes the choice trustworthy and reviewable. |
| "One-line rejections are enough" | A real rebuttal per alternative is what makes the choice trustworthy. |
| "The 'what' is still a bit open" | Then you're in the wrong skill: settle the design in brainstorming first. |
| "It's determined, so just build it" | Determined ≠ small. A major determined change is settled design that hands off to spec and plan; route it to planned execution. |
| "I'll add the test after" | The before/after check comes first. A test written around a working change proves nothing. |
| "Handle the obvious case now, siblings later" | Same-intent siblings ship in this change; the correctness table lists them. Only a separate, larger improvement may be deferred. |

## Red Flags — Stop, You're About to Violate the Discipline

- You typed an approach before dispatching research or reading a sibling implementation.
- You can name only one candidate.
- Your change introduces a helper the codebase already provides.
- You rejected an alternative without saying why it's less coherent.
- You got approval at stage 4 but moved on without persisting the defended choice to `.claude/output/decisions/`.
- You're implementing or closing in decision-only mode, which the caller owns.
- You're about to build a major, multi-task change inline instead of routing it to spec → plan → execution.
- You're about to hand back without the before/after check flipping or the `*-review-lite` gate running.
