# Coming from superpowers? Read this first.

chris-code is derived from [obra/superpowers](https://github.com/obra/superpowers). If you know superpowers, you already know 80% of chris-code: the same brainstorm → plan → execute → review → finish pipeline, most of the same skill names, the same TDD and systematic-debugging discipline. This doc explains the 20% that changed and, more importantly, *why*.

> **Baseline:** this comparison is against the **v5.1.0** fork point, where chris-code's design diverged. chris-code has since selectively backported mechanisms from **v6.0.0** (file handoffs, pre-flight review, a durable progress ledger, reviewer-integrity rules); see the plugin README.

## TL;DR

Day to day, three things feel different:

1. **Your specs and plans get shorter.** chris-code refuses to write 2,500-word specs and 10,000-word plans full of code the implementer will throw away. Specs capture contracts, plans capture *what and where*, and the code gets written against the real codebase, not the plan.
2. **Coding and review run through dedicated agents, not generic subagents.** chris-code ships named `*-coder`, `*-quality-reviewer`, and `*-review-lite` agents that auto-dispatch by file type. You rarely pick one by hand.
3. **Every task passes the same review gates.** Spec compliance, then code quality, then a pre-commit idiom/lint gate. No task is "small enough to skip."

Everything below is the reasoning behind those, then the specifics.

---

## The big picture: five thematic shifts

### 1. Lean artifacts over exhaustive ones

**The why.** superpowers' `writing-plans` told you to document everything "as if the engineer has zero context," with complete code in every step. In practice, implementing agents ignored the pasted code and wrote their own, so the effort was wasted and the plan-vs-reality mismatch caused confusion.

chris-code adopts **"contracts stay, choreography goes."** A spec records only the invariants that survive an architectural rewrite. A plan tells the executor *what* to do and *where*, and trusts it to write code that fits the actual repo. A word-efficiency principle keeps it honest: every line must be load-bearing, and length is a smell rather than a limit.

### 2. A real agent layer, dispatched by scope

**The why.** superpowers is skills-only. Its coding and review happen inline or through generic subagents steered by prompt-template files (`implementer-prompt.md`, `code-reviewer.md`). That works, but every dispatch is hand-rolled.

chris-code adds **nine dedicated agents** with frontmatter scoping. The right one fires automatically based on file extension and project dependencies: `pytorch-coder` wins over `python-coder` in a torch project; all matching `*-quality-reviewer`s fire additively. You describe the task; the routing is mechanical.

### 3. Review is a uniform, multi-stage gate

**The why.** superpowers already reviews every task in two stages (spec compliance, then code quality) through dispatched reviewer subagents, plus a final whole-branch pass. chris-code keeps that spine and hardens it: the reviewers are dedicated, scope-dispatched agents rather than generic subagents driven by prompt templates; lint becomes its own mandatory gate; a `*-review-lite` idiom check runs pre-commit; and a final full-diff pass catches cross-task drift. Every gate re-reads the actual code, not the agent's summary ("Do Not Trust the Report").

### 4. Parallelism is a feature, not a footgun

**The why.** This one is a direct reversal. superpowers lists "dispatch multiple implementation subagents in parallel" as a **Red Flag** (they conflict). chris-code maps each task's file footprint up front, groups non-overlapping tasks into stages, and runs each stage concurrently. Same safety concern, solved by scheduling instead of prohibition.

### 5. Native tools first, with hard gates

**The why.** superpowers already prefers native worktree tools (its rewrite names `EnterWorktree`) and asks consent, falling back to a manual `git worktree` only when no native tool exists, and announcing the fallback when it happens. chris-code shares that native-first preference but replaces the fallback with a **hard gate**: if the native tool is unavailable, **stop and warn**, never fall back to working in place. The gate exists because a silent fallback once caused real damage (subagents targeting the wrong directory).

There's also a quieter sixth shift in **voice**: chris-code strips superpowers' persuasion scaffolding (Real-World-Impact stat blocks, "Red Flags - STOP" lists, rationalization tables, the "your human partner" framing) in favor of terse, mechanical instructions. Same rules, less rhetoric.

---

## What stayed the same

If you relied on these, they carry over essentially unchanged (renames and diagram-format swaps aside):

- **brainstorming** still gates creative work and runs the same intent → approaches → design flow.
- **test-driven-development** still enforces RED-GREEN-REFACTOR.
- **systematic-debugging** still runs the same four-phase root-cause method with the Iron Law and architecture-questioning phase.
- **finishing-a-development-branch** still offers the same merge / PR / keep / discard menu.
- **dispatching-parallel-agents**, **receiving-code-review**, and the session-start discovery skill (now `using-chris-code`) are the superpowers skills with light edits.

---

## Large divergences in skills you already know

These four are the ones where muscle memory will mislead you. Framed as before → after:

| Skill | superpowers | chris-code |
|---|---|---|
| **writing-plans** | The plan skill: exhaustive, full code in every step. (The spec comes from brainstorming.) | **Plan slimmed to `lean-plan`; spec promoted to `lean-spec`.** Spec = contracts only. Plan = what/where handoff, no inline code. |
| **subagent-driven-development** | Two-stage review; parallel implementers discouraged. | **Three gates per task** (spec → quality → commit-lite), scope-based agent selection, and **deliberate staged parallelism** by file footprint. |
| **verification-before-completion** | Single-command gate: "what command proves this? run it." | **Four-step hard pipeline:** Tests → Lints → Full Review (scope-matched `*-review` skills) → Requirements. |
| **requesting-code-review** | The *primary, mandatory* review path. | **Demoted to ad-hoc.** Routine review now lives in the automated agent/skill gates. Base SHA `HEAD~1` → `git merge-base HEAD main`. |

---

## What's new, and why

### New skills (9)

| Skill | Why it exists |
|---|---|
| `lean-spec` | Promotes the spec to a dedicated skill. superpowers produced a design/spec doc inside `brainstorming`; chris-code makes writing it a first-class step. |
| `regression-test` | Lock in every bug fix with a test for the bug and its siblings before moving on. |
| `python-review` | Senior Python refactor/API-design review as an on-demand pass. |
| `rust-review` | The same, for Rust. |
| `technical-review` | Math/algorithm/numerical-correctness review for ML code, which general review misses. |
| `bug-hunt` | Parallel adversarial edge-case test campaign across subsystems. |
| `test-sweep` | Iterative combinatorial test-and-fix campaign to find API-surface gaps. |
| `code-archaeology` | Surface dead code, stubs, and spec-vs-impl gaps before a milestone. |
| `release` | Version bump + changelog + GitHub release in one flow. |

### New agents (9) — the layer superpowers doesn't have

| Agents | Role |
|---|---|
| `python-coder`, `pytorch-coder`, `rust-coder` | One coder per task, most-specific wins by scope + dependencies. |
| `python-quality-reviewer`, `pytorch-quality-reviewer`, `rust-quality-reviewer` | Additive post-spec quality review; all matching fire. |
| `python-review-lite`, `rust-review-lite` | Fast pre-commit idiom/lint gate returning clean / block / escalate. |
| `bug-hunter` | Adversarial edge-case test writer dispatched by `bug-hunt`; never fixes. |

---

## Smaller and cosmetic changes

- **Renames:** `using-superpowers` → `using-chris-code` (otherwise verbatim); `superpowers:` skill references → `chris-code:` throughout.
- **Diagrams:** Graphviz/DOT examples swapped for Mermaid across skills.
- **Paths:** output dirs moved to `.claude/output/{specs,plans}`; worktrees to `.claude/worktrees/`.
- **Small hooks added to familiar skills:** `test-driven-development` gained a bug-hunter-derived edge-case checklist; `systematic-debugging` gained a "System Boundaries" check (FFI, serialization, type coercion) and a `regression-test` follow-up; `dispatching-parallel-agents` gained a file-footprint check.
- **Dropped everywhere:** Real-World-Impact stats, "Red Flags - STOP" lists, "Common Rationalizations" tables, dated session anecdotes, and "your human partner" phrasing.
- **Known nit:** `writing-skills` switched its example to Mermaid but still references `@graphviz-conventions.dot` just below and still ships the graphviz files. Cleanup pending.

---

## Appendix: receipts

### Inventory

Verified against two agreeing sources: the local plugin catalog cache (superpowers v5.1.0) and the live `obra/superpowers` GitHub tree.

| | superpowers | chris-code |
|---|---|---|
| Skills | 14 | 23 |
| Agents | 0 | 9 |
| Commands | 0 | 0 |
| Hooks | 1 | 0 |

Every superpowers skill is present in chris-code (one renamed: `using-superpowers` → `using-chris-code`; one split: `writing-plans` → `lean-plan`, with the spec promoted to `lean-spec`). chris-code is therefore a true superset.

### Full skill mapping and content verdict

Verdicts come from reading both versions of each skill line by line.

| superpowers skill | chris-code | Content verdict |
|---|---|---|
| using-superpowers | using-chris-code | Lightly edited (rename only) |
| dispatching-parallel-agents | dispatching-parallel-agents | Lightly edited (+ footprint check) |
| test-driven-development | test-driven-development | Lightly edited |
| systematic-debugging | systematic-debugging | Lightly edited |
| finishing-a-development-branch | finishing-a-development-branch | Lightly edited |
| brainstorming | brainstorming | Moderately revised |
| executing-plans | executing-plans | Moderately revised |
| receiving-code-review | receiving-code-review | Moderately revised |
| writing-skills | writing-skills | Moderately revised |
| subagent-driven-development | subagent-driven-development | Heavily rewritten |
| verification-before-completion | verification-before-completion | Heavily rewritten |
| requesting-code-review | requesting-code-review | Heavily rewritten |
| using-git-worktrees | using-git-worktrees | Heavily rewritten |
| writing-plans | lean-plan (spec → lean-spec) | Heavily rewritten / slimmed |
