# Skills

chris-code ships 25 skills. Most fire automatically — invoked by the pipeline, by another skill, or by a trigger phrase in your request — so you rarely call them by name. This page describes each one: what it does, when it fires, and what it hands off to.

The skills fall into eight groups. The first four form the idea-to-integration pipeline; the rest are the change engine, testing, completion, review, quality campaigns, and meta-skills.

---

## Design & planning

### `brainstorming`
The mandatory front door for any creative work — a new feature, a component, a behavior change. It is a **hard gate**: no implementation begins until a design exists and you've approved it, no matter how simple the task looks. It explores intent and constraints by asking questions **one at a time**, proposes two or three approaches with trade-offs, presents the design in sections, and — before handing off — freezes the **intent ledger** (≤7 observable acceptance statements in your words, which *it* drafts and you approve). Terminal state: it invokes `lean-spec`, then `lean-plan`. It never jumps straight to coding.

### `lean-spec`
Writes the design as a **minimal durable document** — system behavior, architecture, interfaces, invariants, and acceptance criteria — and nothing else. Its governing rule is *"contracts stay, choreography goes"*: if a line would change when you reimplement in another language, it belongs in a plan, not the spec. A word-efficiency principle keeps it honest — every line must be load-bearing. Output lands in `.claude/output/specs/`.

### `lean-plan`
Turns a spec into a **thin execution handoff**: what to do and where, never how. It does not paste code the implementer will discard; where a design spec already documents a requirement, it references the spec rather than restating it. This is the artifact `subagent-driven-development` executes. Output lands in `.claude/output/plans/`.

---

## Execution

### `subagent-driven-development`
Executes a plan in the current session by dispatching a **fresh subagent per task**, with three review gates after each: spec compliance → code quality → commit-lite. It maps each task's file footprint up front and uses **staged parallelism** — independent tasks run concurrently, tasks that share a file are serialized. It hands artifacts over as files (not pasted text), keeps a durable progress ledger to survive compaction, and runs a final whole-diff review pass. See [Execution mechanics](../explanation/execution-mechanics.md).

### `executing-plans`
The inline alternative to `subagent-driven-development`: load the plan, review it critically, and execute all tasks **without** dispatching subagents, with review checkpoints along the way. Use it when subagent overhead isn't worth it or the work is better kept in one context.

### `dispatching-parallel-agents`
The general pattern for 2+ independent tasks with no shared state. It dispatches one focused agent per problem domain, each with isolated context constructed exactly for its task — subagents never inherit your session history. It maps file footprints first so parallel agents can't collide.

### `using-git-worktrees`
Ensures work happens in an **isolated workspace** before execution begins. It prefers the platform's native worktree tools; where none exists, it does **not** silently fall back to working in place — it stops and warns, because a silent fallback once caused real damage.

---

## The change engine

### `coherent-change`
The engine for **determined** work — changes whose intended behavior is already settled (a refactor, a migration, an API alignment, an already-specced behavior) where the only open question is *which implementation fits the codebase*. It researches the codebase with parallel `Explore` agents, generates two to four grounded candidates, and produces a **defended choice**: the selected approach, a correctness table over every affected case, and a real rebuttal of each alternative. In **build mode** it implements and lite-reviews a single coherent edit; a **major** change it instead routes to planned execution (`lean-spec` → `lean-plan` → `subagent-driven-development`), and in **decision-only mode** (when `lean-spec` calls it for a decision) it stops at the defended choice. Handed a **set** of changes (audit / review findings), **batch mode** runs one consolidated research pass and routes the whole set into one `lean-spec` → `lean-plan` → SDD. It is the universal *application* engine — anything with a settled end-state runs through it. See [The determined-change engine](../explanation/the-pipeline.md#the-determined-change-engine).

### `remediating-issues`
The bug specialization of the engine. For a known defect with more than one plausible fix, it confirms the bug is real and still open, completes `systematic-debugging`'s root-cause phase, delegates the build to `coherent-change`, then runs the bug close — `regression-test` → `verification-before-completion` → `finishing-a-development-branch` — and records the resolution against its origin. A *set* of bugs runs through `coherent-change` batch mode (one consolidated spec → plan), with regression coverage and origin recording folded into the one plan.

### `systematic-debugging`
The four-phase root-cause method for any bug, test failure, or unexpected behavior — invoked **before** proposing a fix, because random patches mask the underlying issue and breed new bugs. Phase 1 (root cause) is a required sub-step of `remediating-issues`. It includes a System Boundaries check (FFI, serialization, type coercion) and a mandatory `regression-test` follow-up.

---

## Testing

### `test-driven-development`
The RED-GREEN-REFACTOR cycle: write the test first, watch it fail, write the minimal code to pass, then refactor. Coder agents follow it during implementation. Writing a test around already-working code proves nothing about the behavior — the failing test comes first.

### `regression-test`
**Mandatory after any bug fix**, before reporting it done or committing. It writes durable coverage of the *specific failure mode*, proven to fail on the pre-fix code (run RED while the fix is unstaged). The cost of a missed regression test is a repeat bug; the cost of invoking it unnecessarily is zero — so it never skips.

---

## Completion

### `verification-before-completion`
The five-step hard gate before any "done" claim: **Tests → Lints → Full review (`*-design-reviewer` agents) → Requirements → Intent re-check (spec-blind `intent-reviewer`)**. Evidence before assertions, always; a PASS that carries findings is not clean. See [The assurance model](../explanation/the-assurance-model.md).

### `finishing-a-development-branch`
Runs once implementation is complete and verified. It presents the integration options — merge, open a PR, keep the branch, or discard — and handles the chosen workflow plus worktree cleanup.

---

## Review

### `requesting-code-review`
Ad-hoc review outside the automated gates — when you're stuck, before a refactor, or for a fresh perspective. By default it scopes the change to `git merge-base HEAD main`..`HEAD`.

### `receiving-code-review`
The discipline for *handling* review feedback: technical evaluation, not performative agreement. Verify each finding against the actual code before acting; a stated rationale never auto-downgrades a real finding, and a questionable suggestion is checked, not blindly implemented.

### `python-review` · `rust-review`
Senior-level, interactive refactoring and API-design review of a package/module/subsystem. They recover architectural intent, identify drift (utility-module sprawl, dict-shaped domain data, mode-flag creep, leaky internals), and propose changes as **end-states**. They are *discovery* — they do **not** apply patches; they route the proposed changes to `coherent-change` (single or batch), which finds the method and runs the close. (The read-only `*-design-reviewer` agents are the automated-gate counterparts.)

### `technical-review`
For Python ML code: reviews mathematical correctness, algorithmic logic, numerical stability, and research alignment — loss functions, estimators, optimization steps, anything implementing a published algorithm. Covers PyTorch, Lightning, scikit-learn, scipy, numpy, lightgbm. Terminates at a review artifact, then offers batch remediation (correctness bugs → `remediating-issues`, algorithmic/structural changes → `coherent-change` batch) or defer.

---

## Quality campaigns

### `bug-hunt`
A repeatable parallel campaign: one `bug-hunter` agent per subsystem, each writing edge-case tests and reporting failures as bugs. Pass a subsystem name to scope it. The agents find bugs; they don't fix them — bug-hunt ends by offering batch remediation via `remediating-issues`, or you keep the report for later.

### `test-sweep`
An iterative combinatorial test-and-fix campaign: write systematic test modules across cross-cutting dimensions of the API, run them, fix failures via TDD, then use the failure patterns to derive the next suite. Runs for N rounds or until convergence, pausing only for genuine design decisions.

### `code-archaeology`
Surfaces unimplemented features, silently dropped parameters, dead code paths, skipped tests, and spec-vs-implementation gaps — run it before declaring a milestone done or before a major refactor, or when behavior a user expects is mysteriously absent. It ends at a prioritized report and offers batch remediation — bug-type findings → `remediating-issues`, structural findings → `coherent-change` batch — or defer.

---

## Meta

### `using-chris-code`
The session-start skill: establishes how to find and use skills, requiring a Skill-tool check before any response. Loaded automatically by the plugin system.

### `writing-skills`
TDD applied to *process documentation* — used when creating, editing, or verifying skills. A skill is tested the way code is: against the behavior it's meant to produce.

### `release`
Cuts a release — bump the version across the repo, generate a changelog from conventional commits, update the changelog file, and create a tagged GitHub release. Triggered explicitly only; never auto-invoked.
