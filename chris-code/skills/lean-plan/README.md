# lean-plan

## Intent

Replace the superpowers writing-plans skill with a lean alternative that produces thin execution handoffs instead of verbose implementation guides.

The superpowers writing-plans skill mandates "complete code in every step" and produces 5,000–10,000 word plans full of inline code blocks. In practice, implementing agents ignore the pasted code and write their own — the code blocks are pure waste. This skill produces plans that tell the executor WHAT to do and WHERE, referencing the design spec for requirements instead of restating them.

## Rationale

The insight came from observing that:
1. **Implementing agents discard pasted code.** They read the spec, understand the requirement, and write code that fits the actual codebase state — not code drafted before implementation began.
2. **Duplicated spec content rots.** When the plan restates the spec, any spec update creates a silent divergence. Referencing the spec by section avoids this.
3. **Token cost is real.** A 10,000-word plan consumes ~15k tokens of context. A 400-word plan consumes ~600. The executor gets more working room.
4. **Trust the executor.** The plan targets a skilled engineer who can read a spec and write code. It doesn't need to hold their hand through "write test, run test, write code, run test, commit" for every action.

## Relationship to other skills

- **lean-spec** — produces the design spec that lean-plan references. The spec defines *what must be true*; the plan defines *what to do* in what order.
- **superpowers:writing-plans** — the skill lean-plan replaces. The global CLAUDE.md redirects brainstorming's plan-writing handoff to lean-plan.
- **superpowers:subagent-driven-development / superpowers:executing-plans** — consume the plan produced by lean-plan. The 7-section format (Objective, Spec references, Files, Constraints, Tasks, Acceptance checks, Open questions) is designed to be dispatched task-by-task to subagents.

## Target output

200–450 words for a normal single-subsystem plan, up to 800 for multi-file multi-task plans. 7 structured sections. No inline code unless essential for an exact contract, schema, or command. Precise spec references replacing duplicated detail.
