---
name: lean-spec
description: Use when writing a design spec for a feature, phase, or subsystem — produces a lean canonical design artifact, not an implementation guide or coding walkthrough
---

# Lean Spec

## Overview

Write a technical design spec as a minimal durable document. The spec makes system behavior, architecture, constraints, and acceptance criteria unambiguous. It is a canonical design artifact — not an implementation plan, not a task list, not a coding walkthrough.

**Announce at start:** "I'm using the lean-spec skill to write the design spec."

**Save specs to:** `.claude/output/specs/YYYY-MM-DD-<feature-name>-design.md`

## Core Principle

**Contracts stay. Choreography goes.** Keep content that remains valid even if the implementation order, file layout, or coding approach changes. Remove everything else.

## Spec vs Plan Rule

- If changing it would change **system behavior, architecture, interfaces, invariants, or acceptance criteria** → keep in spec.
- If changing it would only change **implementation order, coding approach, task assignment, or file-touch sequence** → remove from spec.

## Before Writing

1. Read relevant existing specs, CLAUDE.md constraints, and source code
2. Identify what decisions are already locked vs. what needs to be decided
3. Understand the user-visible behavior the spec must define

## Output Structure

```markdown
# [Feature Name] Design Spec

## 1. Scope
What is being built; one paragraph.

## 2. Goals
Bulleted list of what must be true when done.

## 3. Non-goals
Explicitly out of scope.

## 4. System behavior
User-visible and internal behavior. What happens when X? What does the user see?

## 5. Architecture
Component responsibilities. Data flow. Where computation lives.

## 6. Canonical interfaces / data contracts
Public interfaces, schemas, typed structures, protocol contracts.
Capture any contract that later binds separate tasks or components, so a plan
can reference it here instead of restating it. Minimal code ONLY to pin down a
public API, schema, or semantic rule that would otherwise be ambiguous. No
module drafts or scaffolds.
Prefer contracts that make integration a *seam-check*: a boundary a reviewer can
verify by reading the two sides against the contract, without holding the whole
system in context. The sharper the seam, the less an integrator has to trust a
compressed report.

## 7. Invariants and constraints
Non-negotiable guarantees. Backward compat. Performance/security requirements.

## 8. Key decisions and tradeoffs
Locked decisions with rationale. Alternatives considered and rejected.
Capture strategy choices, routing/ownership decisions, scoping decisions
(what's explicitly out of scope), configuration contracts, and ordering
constraints — these tend to hide in implementation code if not stated here.

## 9. Acceptance criteria
Observable success criteria. What must pass before this is done.

## 10. Validation strategy
How correctness is validated — at the level of behavior, not command execution.

## 11. Open questions
Only unresolved items that block correctness. Omit section if none.
```

## Grounding a Key Decision

When a section-8 decision is a *determined change against existing code* — the behavior is settled and the only open question is which implementation best fits — use `chris-code:coherent-change` in **decision-only mode** to research the codebase, generate grounded candidates, and defend the most coherent one. Capture its defended choice as the decision's rationale and rejected alternatives. The engine stops at the choice and hands back; the spec → plan → execution workflow still owns the build.

## Allowed Code

Code in the spec must be **minimal** and only used to pin down:
- A public interface or function signature
- A schema or typed structure
- A protocol contract
- A semantic rule that would otherwise be ambiguous

If code is included: keep it short, treat it as contract material, never include full module drafts or copy-paste-ready production code.

## Do Not Include

- File maps, new/modified/unchanged file sections
- Step-by-step implementation instructions or task decomposition
- Ordered edit sequences, insertion points, line-number references
- Shell commands, setup/install instructions, local dev notes
- Commit messages, checkbox tracking, subagent/worker instructions
- "Read this file first, then decide" investigation guidance
- Large code scaffolds, patch-style prose ("replace lines X–Y with…")
- Temporary execution notes that belong in a plan

## Word Efficiency

Every line must be load-bearing: behavior, an interface, an invariant, a decision, or an acceptance criterion that would otherwise be ambiguous. Length is a smell, not a limit. A spec much longer than its interface count usually carries implementation choreography, so find it and cut. Never pad to fill a budget or truncate to fit one.

## Self-Review

After writing, check:

1. **Leanness:** Remove any sentence that tells the implementer which file to edit, dictates coding order, or contains near-production code.
2. **Completeness:** Can a competent engineer design the implementation from this spec? Are all interfaces, invariants, and acceptance criteria defined? Do the acceptance criteria name the edge cases and failure modes they must cover — not just the happy path — and where a class of input or state is deliberately excluded, does the spec say so? If you can't state how you checked for missing cases, the coverage isn't proven.
3. **Durability:** Would this content survive a complete reimplementation in a different language or architecture?

Fix issues inline, then move on.

## Handoff

After saving the spec, offer:

**"Spec saved to `.claude/output/specs/<filename>.md`. Ready to write the implementation plan with `/lean-plan`?"**
