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
Minimal code ONLY to pin down a public API, schema, or semantic rule
that would otherwise be ambiguous. No module drafts or scaffolds.

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

## Target Length

- **500–1500 words** for a single-subsystem spec
- **Up to 2500 words** for a multi-component spec spanning 5+ interfaces
- If the spec exceeds these bounds, look for implementation choreography to cut

## Self-Review

After writing, check:

1. **Leanness:** Remove any sentence that tells the implementer which file to edit, dictates coding order, or contains near-production code.
2. **Completeness:** Can a competent engineer design the implementation from this spec? Are all interfaces, invariants, and acceptance criteria defined?
3. **Durability:** Would this content survive a complete reimplementation in a different language or architecture?

Fix issues inline, then move on.

## Handoff

After saving the spec, offer:

**"Spec saved to `.claude/output/specs/<filename>.md`. Ready to write the implementation plan with `/lean-plan`?"**
