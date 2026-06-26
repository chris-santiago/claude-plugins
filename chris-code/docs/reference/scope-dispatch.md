# Scope dispatch & models

## Dispatch modes

Agents and review skills match by `scope.extensions` and `scope.require_dependencies` in their frontmatter. The dispatch mode depends on the role:

| Role | Dispatch | Example (PyTorch project, `.py` files) |
|------|----------|----------------------------------------|
| `*-coder` | **Exclusive** — most specific wins | `pytorch-coder` (not `python-coder`) |
| `*-quality-reviewer` | **Additive** — all matching fire | `python-quality-reviewer` + `pytorch-quality-reviewer` |
| `*-review-lite` | **Additive** — all matching fire | `python-review-lite` |
| `*-design-reviewer` | **Additive** — all matching fire | `python-design-reviewer` + `rust-design-reviewer` |
| `*-review` skills (standalone) | **Additive** — all matching fire | `python-review` + `rust-review` |
| `spec-reviewer`, `intent-reviewer` | **Explicit** — language-agnostic, dispatched by name | `spec-reviewer` per task; `intent-reviewer` at completion |

**Exclusive** means exactly one agent does the work — the most specific match. **Additive** means every agent matching the file extensions fires on the same diff; if findings conflict, the more specific agent's guidance wins. **Explicit** agents aren't matched by file type at all — the skills dispatch them by name.

## Model selection

Each role runs on the least powerful model that can handle it. Where an agent's frontmatter pins no `model`, it inherits the dispatch model.

| Model | Used for |
|-------|----------|
| **Haiku** | Isolated functions, clear spec, 1–2 files, mechanical changes |
| **Sonnet** | Multi-file coordination, integration, pattern matching — the coders |
| **Opus** | Architecture and design judgment, broad understanding — the quality, design, and conformance reviewers |

Every dispatch announces its model and agent, e.g. *"Dispatching sonnet rust-coder agent for Task 5 (refactor pipeline)."*
