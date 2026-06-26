# Skills

chris-code ships 25 skills. Most are invoked automatically by the pipeline or by other skills; some are user-triggered. Skill triggers are described in each skill's own description — the tables below summarize role and invocation.

## Workflow skills (pipeline order)

These form the core idea-to-integration pipeline. Each invokes specific skills and dispatches agents automatically.

| Skill | Purpose | Invoked by |
|-------|---------|------------|
| `using-chris-code` | Session-start skill discovery | Plugin system (auto) |
| `brainstorming` | Explore intent, requirements, design before implementation; freezes the intent ledger | User, or `using-chris-code` |
| `lean-spec` | Write a contracts-only design spec | `brainstorming` |
| `lean-plan` | Write a thin execution handoff (what & where, no code) | `brainstorming` |
| `using-git-worktrees` | Isolated workspace via native worktree tools | `executing-plans` / `subagent-driven-development` |
| `subagent-driven-development` | Execute a plan per task: file-handoff dispatch, staged parallelism, durable progress ledger | `lean-plan` handoff |
| `executing-plans` | Execute a plan inline, without subagents | `lean-plan` handoff (alternative) |
| `dispatching-parallel-agents` | Dispatch 2+ independent tasks concurrently | Any skill needing parallelism |
| `test-driven-development` | RED-GREEN-REFACTOR cycle | Coder agents during implementation |
| `systematic-debugging` | Four-phase root-cause investigation | When bugs arise |
| `remediating-issues` | Remediate a known bug/issue: frame → build → close | User, or a review/audit finding |
| `coherent-change` | Build a *determined* change to fit the codebase: research → defend → implement → lite-review | `remediating-issues` / `systematic-debugging` / `lean-spec` / direct |
| `verification-before-completion` | Five-step completion gate: tests → lints → review → requirements → intent re-check | Before claiming done |
| `finishing-a-development-branch` | Merge / PR / keep / discard + worktree cleanup | After verification passes |
| `requesting-code-review` | Ad-hoc review (fresh perspective, pre-refactor) | User-triggered |
| `receiving-code-review` | Handle review feedback with technical rigor | When review feedback is received |
| `writing-skills` | TDD applied to skill creation | When creating/editing skills |
| `regression-test` | Write regression tests after a bug fix | `systematic-debugging` / `remediating-issues` |

## Standalone skills (user-invoked)

Not part of the linear pipeline — run these on demand.

| Skill | Purpose |
|-------|---------|
| `python-review` | Senior-level Python refactoring & API-design review |
| `rust-review` | Senior-level Rust refactoring & API-design review |
| `technical-review` | Math / algorithm / numerical-correctness review for ML code |
| `bug-hunt` | Parallel adversarial edge-case test campaign across subsystems |
| `test-sweep` | Iterative combinatorial test-and-fix campaign |
| `code-archaeology` | Find dead code, unimplemented features, and spec-vs-impl gaps |
| `release` | Version bump + changelog + GitHub release |

## The determined-change engine

`coherent-change` is the shared build engine behind the fix/change front-ends. `remediating-issues` (known bugs) and `systematic-debugging` (diagnosed fixes) delegate the *build* to it and own their *close*; `lean-spec` calls it decision-only to take just the defended choice into its plan; invoked directly, you are the caller and run the close. See [The pipeline → The determined-change engine](../explanation/the-pipeline.md#the-determined-change-engine).
