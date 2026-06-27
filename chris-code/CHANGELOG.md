# Changelog

All notable changes to **chris-code** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Versions are markers in `plugin.json`; the project is shared by cloning, not by tagged GitHub releases.

This history was reconstructed retroactively from git (development began 2026-05-20). chris-code is a superset of [obra/superpowers](https://github.com/obra/superpowers): forked from **v5.1.0**, then hardened with selective **v6.0.0** backports.

## [Unreleased]

### Added
- `coherent-change` **batch mode** — a set of end-state-framed changes (audit / review findings) runs as one consolidated research pass → a defended choice per change → **one** `lean-spec` → **one** `lean-plan` → SDD. `coherent-change` is now the universal *application* engine.
- A **workflow catalog** in the docs (the How-to landing) — a graph, *when to use it*, and *how to invoke* for every canonical route — plus new recipes: build a feature, debug an unknown cause, remediate in batch.

### Changed
- `coherent-change` now **sizes the change at the approval checkpoint** and recommends an execution route: a single coherent edit builds inline (as before); a major / multi-task change routes the defended choice to planned execution (`lean-spec` → `lean-plan` → `subagent-driven-development`) instead of being built in one shot. Closes the gap where a directly-invoked major change had no path into the planned-execution workflow.
- **Discovery skills now route to remediation.** `code-archaeology`, `bug-hunt`, and `technical-review` terminate at their artifact and **offer** batch remediation (bug-type → `remediating-issues`, structural → `coherent-change` batch) or defer — closing the previously-manual discovery→remediation seam.
- **`python-review` / `rust-review` no longer apply patches.** They stay interactive discovery and route their proposed end-states through `coherent-change`, which finds the method and runs the close.
- **`remediating-issues`' Batch Path** is now a bug-framed caller of `coherent-change` batch mode (one consolidated spec → plan), not per-issue fan-out.

## [0.3.0] - 2026-06-26 — Rigor hardening & documentation

Made the structure honest about what it proves, added the missing intent axis, and gave the framework a full documentation site.

### Added
- **Intent integrity.** A frozen **intent ledger** (≤7 observable acceptance statements, assistant-drafted during `brainstorming`) and a spec-blind **intent re-check** as `verification-before-completion` Step 5.
- **The conformance pair** as registered agents: a new spec-blind `intent-reviewer`, and `spec-reviewer` promoted from a dispatch prompt template to a language-agnostic registered agent.
- **"Brief carries intent, coder demands it"** — the dispatch loop that states a task's *why* explicitly and has coders escalate when it's missing.
- A **Zensical (Diátaxis) documentation site** under `chris-code/docs/`, built fully on-the-fly via `uvx` (no `pyproject.toml`), with a GitHub Pages workflow. A `CHANGELOG.md` (this file).

### Changed
- **Gate honesty** — reframed "more stages" as raising *recall*, not proof, across the decks and `verification-before-completion`; checklists are a floor, not a ceiling.
- **Integrator grounding** — the orchestrator re-reads the actual code slice behind a judgment-shaped verdict instead of trusting the summary; reviewers emit a lossiness flag.
- Reconciled the README and docs against source (13 agents, 25 skills); added a determined-change engine section to the README; relocated the visual decks to `chris-code/assets/decks/`.

### Fixed
- Design-reviewer lane formatting on both visual decks.
- Removed a session-internal "fork path parked" reference that leaked decision context into a durable skill.

### Removed
- The forking guardrail note (G-1), reverted once forking proved version-dependent and unreliable; its rationale is retained as future-extension material, not shipped guidance.

## [0.2.0] - 2026-06-24 — superpowers v6.0.0 backport & the change engine

Backported v6.0.0's execution mechanics, added the read-only senior review gate, and introduced the determined-change engine.

### Added
- **The determined-change engine** `coherent-change` (research → defend the most coherent implementation → implement → lite-review, producing a defended choice) and its bug specialization `remediating-issues`.
- **Senior read-only design-reviewer agents** (`python-design-reviewer`, `rust-design-reviewer`) for the verification gate, registered in the manifest.
- **Execution mechanics (v6.0.0 backports)** in `subagent-driven-development`: file handoffs, pre-flight plan review, a durable progress ledger, and reviewer-integrity rules, with `task-brief` / `review-package` / `progress` scripts.
- The visual decks (overview, from-superpowers).

### Changed
- `coherent-change` adopts **build-and-handback** — the engine builds and lite-reviews; callers own the heavyweight close.
- Reframed document length as **word-efficiency** under "contracts stay, choreography goes"; replaced word budgets with the efficiency framing.
- Added instruction-precedence / anti-suppression clauses to review agents; PASS-with-findings treated as **not-clean** (in-scope findings fixed in-change).
- Reframed the SDD task brief as a reference sheet, not a restatement of the spec.
- Reconciled v5.1.0 provenance with the v6.0.0 backport; corrected the superpowers comparison against the v5.1.0 baseline.

### Fixed
- The prove-RED recipe now runs **before** staging — `git stash pop` restores the working tree but not the index, which silently dropped the fix from the commit.
- The final-gate `review-lite` no-op, and the reconnected cycle backstop.

## [0.1.0] - 2026-06-08 — Foundation

The initial chris-code workflow, forked and generalized from superpowers v5.1.0.

### Added
- The chris-code **plugin manifest** and the `using-chris-code` session-start meta-skill (generalized from an earlier project-specific "ferrum" agent/skill set).
- **The agent layer**: coder agents `python-coder`, `pytorch-coder`, `rust-coder` (exclusive, most-specific-wins dispatch); `python/pytorch/rust-quality-reviewer` (additive); `python/rust-review-lite` commit gates; `bug-hunter` — with `.ipynb` support for the Python agents.
- New-over-superpowers skills: `lean-spec`, `lean-plan`, `technical-review`, `regression-test`, and the `bug-hunt` / `test-sweep` / `code-archaeology` / `release` campaigns.
- A top-level repository README with three install methods, and a chris-code README with the workflow graph and skill/agent reference.

### Changed
- **Overhauled `subagent-driven-development`** with staged parallelism by file footprint, specialized per-task agents, and a final full-diff review.
- Adapted the inherited superpowers skills — `brainstorming` (spec-readiness check), `test-driven-development`, `systematic-debugging` (boundary checks), `using-git-worktrees` (hard gate on fallback), `receiving-code-review`, `requesting-code-review`, `writing-skills` — and converted all DOT graphs to Mermaid.
- Made `verification-before-completion` concrete and unified scope dispatch across the plugin (exclusive vs. additive).

### Fixed
- A Mermaid parse error and the `pytorch-coder` dependency tiebreaker.

### Removed
- superpowers-specific language and project-specific ("Ferrum") terms throughout the skills.

[Unreleased]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.3.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.2.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.1.0]: https://github.com/chris-santiago/claude-plugins/commits/main
