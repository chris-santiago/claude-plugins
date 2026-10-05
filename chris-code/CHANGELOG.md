# Changelog

All notable changes to **chris-code** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Versions are markers in `plugin.json`; the project is shared by cloning, not by tagged GitHub releases.

This history was reconstructed retroactively from git (development began 2026-05-20). chris-code is a superset of [obra/superpowers](https://github.com/obra/superpowers): forked from **v5.1.0**, then hardened with selective **v6.0.0** backports.

## [Unreleased]

## [0.5.0] - 2026-10-04 — Batched, coherent remediation

Review findings stop cascading: every review loop batches its verdicts, triages once, and routes non-trivial fixes through the coherence engine, with the close capped at two rounds.

### Changed
- **Batched, coherent remediation at every review loop.** Fix rounds were cascading: findings fixed one gate at a time as point patches, outside the coherence engine, each fix surfacing new findings on its own surface.
  - **Per task (SDD):** the spec reviewer and quality reviewers now run in parallel (spec-first ordering removed), and every verdict accumulates before one triage. Trivial findings (no behavior change, one site, no contract) go straight to the coder. Non-trivial ones first go through `remediating-issues`' new **per-task variant**: decision-only, with one decision doc of defended choices and no approval checkpoint. The coder fixes against that doc. A recurring finding's doc must replace the failed mechanism. Cycle ≥ 3 escalation is unchanged.
  - **Completion close:** `verification-before-completion` runs its design, intent, and mutation gates as one **close round**, dispatched together and triaged once. Non-trivial findings go through `remediating-issues`' new **close-gate variant** (decision doc, then `lean-plan`, then SDD on the same store; the only batch that skips `lean-spec`). Round 2 re-checks at the same report paths. A new finding on code the remediation never touched is logged as a follow-up, and anything non-trivial left after round 2 goes to the user.
  - **`ledger.py close-round --expect N`** records each round, and the HEAD it reviewed, as a typed progress entry and refuses a third, so the two-round cap and round 2's remediation range survive compaction. `--expect` fails when the store disagrees (for example, a fresh close finding an earlier run's rounds), so a stale store can't silently start a new run at round 2.
  - **`ledger.py clear`** now also removes the run's handoff files (briefs, reports, per-task decision docs, gate reports, review packages). Gate reviewers read their report path as their prior verdict, so a surviving report would anchor an unrelated run on stale findings.

### Fixed
- **Gate reviewers join the file-handoff system**: the design reviewers and `intent-reviewer` — the last agents returning full reports inline into the orchestrator's context — now write their report to a dispatch-supplied path under the run store and return only `PASS | CONCERNS` plus the path (read-only on the checkout otherwise; a re-run reads its own prior report; an ad-hoc dispatch with no path still gets the report inline). `verification-before-completion` supplies the paths via `ledger.py store-dir`. Surfaced by a live session hitting the design reviewer's inability to persist its cycle-2 verdict.

### Added
- **Diagnosis-first fix loop** (data-driven, from a 25-round wave analysis): coders self-derive `cycle` like review-lite (fix re-dispatch at the same record path), and from cycle 2 their record must carry a `diagnosis` (`root_cause`, `end_state`, `resolves_cluster` — `check` enforces it); re-reviewing agents judge the fix against the stated cause. Spec- and quality-reviewers gain a `recurring` field (same finding class at the same site across cycles) — the typed fix-failure signal; when it fires, the next fix dispatch must carry a **defended mechanism choice**. Cycle ≥3 still always escalates to the user, but a recurring-mechanism signature that persisted through a defended fix arrives briefed with a `coherent-change` defended choice.
- **Fixture-reality principle** in all coder and quality-reviewer contracts: RED proofs and pinned fixtures must be produced by the real path under test (or a documented mirror) — a hand-built shape the production path never emits pins the wrong behavior. Three same-shaped failures in one wave earned the contract line.
- **Reviewer accumulation rule**: never dispatch a fix while any reviewer for the same task is still out — one fix dispatch carrying every reviewer's record path.
- **The fix loop is now taught, not just wired**: a "The fix loop" section in execution-mechanics, a README bullet, a guide callout, and an intro-deck line with companion notes — accumulation, diagnosis-first, recurrence-not-new-findings as the failure signal, and the cycle-3 briefing rule.

### Fixed
- **The missing-record-path backstop no longer overreaches ad-hoc dispatches**: coders skip the typed record (noting its absence) when a dispatch carries no store artifacts at all, and the review-lites return their verdict as a standalone pre-commit gate; the refusal now fires only on an SDD-shaped dispatch that omits the record or scripts path. The unconditional 0.4.0 form would have made plugin coders and review-lites refuse every legitimate non-SDD dispatch (e.g. a project agent delegating a fix, or the plain pre-commit gate).

## [0.4.0] - 2026-08-28 — Typed handoffs & grounded integration

The typed handoff layer: agents hand reasoning to each other as files and decisions to the orchestrator as validated JSON records, the store moves out of `.git/`, and judgment-shaped verdicts are grounded by a dedicated quoting agent instead of orchestrator re-reads.

### Added
- **`claim-checker` agent** (haiku, read-only, non-judging): settles one decidable factual claim about code by quoting the lines that answer it (`holds` / `does-not-hold` / `not-decidable-by-reading`, evidence mandatory). `subagent-driven-development` now grounds judgment-shaped verdicts and spec-reviewer `cannot_verify` items **by dispatch, not by reading** — the orchestrator formulates a decidable claim and the checker does the looking, so grounding stops costing the context the file handoffs protect. Agent count: 15.
- **Typed handoff layer** in `subagent-driven-development`: the nine per-task-loop agents write JSON records validated against a shared contract (`scripts/ledger.py` — `check` as the agent's own write-time gate, `open`/`resolve` with content-derived ids, `shapes`, typed completion), and `scripts/task_brief.py` gates briefs on an intent statement and validates `Consumes:` pointers. Backed by a stdlib-only test suite under `chris-code/tests/`.
- `coherent-change` **batch mode** — a set of end-state-framed changes (audit / review findings) runs as one consolidated research pass → a defended choice per change → **one** `lean-spec` → **one** `lean-plan` → SDD. `coherent-change` is now the universal *application* engine.
- A **workflow catalog** in the docs (the How-to landing) — a graph, *when to use it*, and *how to invoke* for every canonical route — plus new recipes: build a feature, debug an unknown cause, remediate in batch.

### Changed
- **A malformed `progress.jsonl` line now raises** instead of being skipped with a stderr warning — the log feeds `resolve`'s already-resolved gate, so a silently dropped resolution line would silently re-open an item. This was the one place the loud-failure rule bent.
- **Findings hand over by path, never by paraphrase**: when a review comes back `issues`/`block`/`escalate`, the fix dispatch carries the reviewer's record path instead of the orchestrator restating the findings — restating is where a finding quietly loses its severity, `file:line`, or reasoning.
- **The SDD store moved out of `.git/`**: `ledger.py store-dir` now resolves to `.sdd/` at the repo toplevel (per-worktree via `--show-toplevel`) and seeds a `.gitignore` containing `*` inside it, so the store ignores itself with no edit to the repo's ignore rules. `review-package`'s default outfile now routes through `store-dir` instead of deriving its own path. A session in flight against the old location keeps reading it via `--store "$(git rev-parse --git-path sdd)"`.
- `coherent-change` now **sizes the change at the approval checkpoint** and recommends an execution route: a single coherent edit builds inline (as before); a major / multi-task change routes the defended choice to planned execution (`lean-spec` → `lean-plan` → `subagent-driven-development`) instead of being built in one shot. Closes the gap where a directly-invoked major change had no path into the planned-execution workflow.
- **Discovery skills now route to remediation.** `code-archaeology`, `bug-hunt`, and `technical-review` terminate at their artifact and **offer** batch remediation (bug-type → `remediating-issues`, structural → `coherent-change` batch) or defer — closing the previously-manual discovery→remediation seam.
- **`python-review` / `rust-review` no longer apply patches.** They stay interactive discovery and route their proposed end-states through `coherent-change`, which finds the method and runs the close.
- **`remediating-issues`' Batch Path** is now a bug-framed caller of `coherent-change` batch mode (one consolidated spec → plan), not per-issue fan-out.
- **Docs, guide, and intro deck teach the two-chain flow**: markdown artifacts (brief → report → verdict) are the reasoning chain between agents, JSON records the decision chain to the orchestrator — new guide section, new deck slide with a `two_chains` figure, and a "two chains" paragraph in execution-mechanics.

### Fixed
- **A dispatch that omits the record path is now refused, not silently accommodated**: the first live trial produced no typed records because the orchestrator's dispatch stopped at the report instruction and the coder, told never to compute paths, silently skipped its record. The Report-file bullet now names dispatch elements 6–7, and every record-writing contract stops and asks (`NEEDS_CONTEXT` / refusal) when the record or scripts path is missing.
- **Stale grounding prose retired**: execution-mechanics, the assurance model, context-and-dispatch, the README's integrator-grounding bullet, and the deck companion all said the orchestrator "re-reads the actual code slice" — updated to the ground-by-dispatch (`claim-checker`) model; `scope-dispatch.md` gains the claim-checker row; the guide's pre-existing stale 13-agent counts fixed.

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
- **Execution mechanics (v6.0.0 backports)** in `subagent-driven-development`: file handoffs, pre-flight plan review, a durable progress ledger, and reviewer-integrity rules, with `task-brief` / `review-package` / `progress` scripts (`task-brief` and `progress` since renamed to `task_brief.py` and `ledger.py`).
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
[0.5.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.3.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.2.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.1.0]: https://github.com/chris-santiago/claude-plugins/commits/main
