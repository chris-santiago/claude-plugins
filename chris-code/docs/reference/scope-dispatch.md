# Scope dispatch & models

## Dispatch modes

Agents and review skills match by `scope.extensions` and `scope.require_dependencies` in their frontmatter. The dispatch mode depends on the role:

| Role | Dispatch | Example (PyTorch project, `.py` files) |
|------|----------|----------------------------------------|
| `*-coder` | **Exclusive** — most specific wins | `pytorch-coder` (not `python-coder`) |
| `*-quality-reviewer` | **Paired** — per language, the reviewer of the coder picked for those files | `pytorch-quality-reviewer` (for `pytorch-coder`) |
| `*-review-lite` | **Additive** — all matching fire | `python-review-lite` |
| `*-design-reviewer` | **Additive** — all matching fire | `python-design-reviewer` + `rust-design-reviewer` |
| `*-review` skills (standalone) | **Additive** — all matching fire | `python-review` + `rust-review` |
| `spec-reviewer`, `intent-reviewer` | **Explicit** — language-agnostic, dispatched by name | `spec-reviewer` per task; `intent-reviewer` at completion |
| `mutation-tester` | **Explicit** — language-agnostic, dispatched by name | `mutation-tester` at completion (Step 5), in an isolated worktree |
| `claim-checker` | **Explicit** — language-agnostic, dispatched by name | one decidable claim per dispatch, to settle a spec reviewer's `read` `cannot_verify` item |

**Exclusive** means exactly one agent does the work, the most specific match, for each language: a task whose files span two languages gets a coder for each, and the first hands off to the coder of record, which finishes the task. **Paired** means that for each language a task touches, the quality reviewer of the same name as the coder picked for those files reviews them (`python-coder` → `python-quality-reviewer`). It checks that coder's principles and patterns, general language ones included, so a PyTorch task gets `pytorch-quality-reviewer` alone and a task touching Rust and Python gets one reviewer for each. **Additive** means every agent matching the file extensions fires on the same diff; if findings conflict, the more specific agent's guidance wins. **Explicit** agents aren't matched by file type at all — the skills dispatch them by name. `mutation-tester` is explicit because it breaks code and runs the project's own tests, which needs no language-specific tooling; it fires once whenever the change includes testable source.

## Model selection

Each role has a fixed model, pinned in its agent's frontmatter, and the orchestrator passes no `model` override. Two roles run as `general-purpose` agents, which have no frontmatter, so their dispatch names the model: `sonnet` for the fallback implementer and `opus` for the `remediating-issues` research agent.

| Model | Used for |
|-------|----------|
| **Sonnet** | The coders and the `*-review-lite` whole-change gates |
| **Opus** | The spec, quality, design and intent reviewers, `mutation-tester`, `bug-hunter`, and the `remediating-issues` research agent |
| **Haiku** | `claim-checker` |

Design judgment lives in the decision doc and the brief, so coders implement choices that are already made. Coders never run above sonnet on the orchestrator's judgment. The user can rule an opus coder for a task at any time, and the stage's batched question offers one when a task escalates. It combines with whatever the user rules for the next fix, such as a fix they name. The ruling is logged in the ledger, the coder checks its own model against it before changing anything, and `ledger.py check` refuses a finished coder record on any model but sonnet without it. Reviewers on opus also read code written by a different model, so their blind spots correlate less with the author's.

Every dispatch announces its model and agent, e.g. *"Dispatching sonnet rust-coder agent for Task 5 (refactor pipeline)."*
