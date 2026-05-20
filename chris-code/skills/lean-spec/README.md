# lean-spec

## Intent

Constrain the spec-writing phase of the brainstorming workflow so design specs are canonical, durable design artifacts — not bloated implementation guides.

The superpowers brainstorming skill defines the *process* of arriving at a design (explore, question, propose, present, approve) but says nothing about what the resulting spec *document* should look like. Without constraints, specs balloon with file maps, step-by-step implementation instructions, large code scaffolds, and task decomposition that belongs in a plan. This skill fills that gap.

## Rationale

The core insight is **"contracts stay, choreography goes."** A spec should contain only content that remains valid even if the implementation order, file layout, or coding approach completely changes. If changing something would only affect how/when code gets written — not what the system does — it belongs in a plan, not the spec.

This produces two benefits:
1. **Durability** — the spec stays useful as a reference long after implementation. It doesn't rot as files get renamed or tasks get reordered.
2. **Cost** — a 1000-word spec costs a fraction of a 6000-word spec in context window, and agents actually read the whole thing.

## Relationship to other skills

- **superpowers:brainstorming** — owns the process of arriving at the design. lean-spec is invoked at step 6 ("Write design doc") to constrain the document output.
- **lean-plan** — the next step after lean-spec. The spec defines *what* must be true; the plan defines *what to do* to make it true. The spec vs plan rule keeps the boundary clean: if it defines system behavior, architecture, interfaces, or invariants, it's spec; if it defines implementation order or task sequence, it's plan.

## Target output

500–1500 words for a single-subsystem spec. 11 structured sections (scope, goals, non-goals, system behavior, architecture, interfaces, invariants, decisions, acceptance criteria, validation strategy, open questions). Minimal code only to pin down public interfaces or schemas.
