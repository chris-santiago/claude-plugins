# Rigor Level Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

Add a resolved `light | standard | heavy` rigor level that scales plan rows, coder tests, reviewer severity for missing cases, and mutation depth, gating and model to the project.

## 2. Spec references

- `.claude/output/specs/2026-11-05-rigor-level-design.md` §4.1-4.2 resolution, §4.3 table, §4.4 every-level rules, §4.5 where the level appears, §6 interfaces, §7 invariants, §9 acceptance
- `.claude/output/intent/2026-11-05-rigor-level-intent.md`

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Create | `chris-code/skills/subagent-driven-development/scripts/rigor.py` | resolver module and CLI |
| Test | `chris-code/tests/test_rigor.py` | resolver rules over throwaway git repos |
| Modify | `chris-code/skills/subagent-driven-development/scripts/task_brief.py` | stamp the task's level, refuse a lowering line |
| Test | `chris-code/tests/test_task_brief.py` | stamp and refusal |
| Create | `chris-code/skills/subagent-driven-development/rigor.md` | the per-role table and every-level rules |
| Modify | `chris-code/agents/{python,rust,pytorch}-coder.md`, `chris-code/skills/subagent-driven-development/implementer-prompt.md` | read the brief's level, test to it |
| Modify | `chris-code/agents/spec-reviewer.md`, `chris-code/agents/{python,rust,pytorch}-quality-reviewer.md` | severity for a missing case by level; can't-fail S3 |
| Modify | `chris-code/agents/mutation-tester.md`, `chris-code/skills/verification-before-completion/SKILL.md` | level, plan, file levels in the dispatch; breaks and gating by level; sonnet at light |
| Modify | `chris-code/skills/lean-plan/SKILL.md`, `chris-code/skills/test-driven-development/SKILL.md`, `chris-code/skills/subagent-driven-development/SKILL.md` | rows to the level; heavy edge list; briefs carry the level |
| Modify | `chris-code/README.md`, `chris-code/docs/**`, `chris-code/CHANGELOG.md`, `chris-code/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | document; release 0.12.0 |
| Test | `chris-code/tests/test_contract_enum_drift.py` | every consumer names `rigor.md` |

## 4. Constraints

- Levels are ordered `light < standard < heavy`; a task or file level is never below the project level.
- Thresholds: under 5,000 counted lines `light`, 5,000-30,000 `standard`, over 30,000 `heavy`. Order: base, then binding floor (`standard`), then numeric raise (+1, capped at `heavy`).
- `CLAUDE.md` line `Test rigor: <level>` wins; any other value is an error (exit 2), never a fallback. No git work tree or no counted source → `standard` with the reason.
- The resolver is stateless and deterministic: no store writes, no network, no test runs.
- `task_brief.py` imports `rigor`; `rigor.py` must not import `task_brief` at module level (no import cycle). `rigor.py` may import `ledger` for the stage map and footprints.
- The `heavy` column is today's behavior; a `heavy` project changes only by the explicit can't-fail S3 rule.
- A plan or brief without `Rigor:` lines keeps working: every task takes the project level.
- `bug-hunt`, `test-sweep`, `*-review-lite`, the design reviewers and the intent reviewer are not changed.
- No project names (no internal project, task, or wave names) in the plugin's prose, docs, or changelog.
- Prose: no hard-wrapped Markdown; em-dashes at most ~1 per 150 words.

## 5. Tasks

### Task 1: Project level
- Cases:
  - 4,999 counted source lines, no markers → light; 5,000 → standard; 30,000 → standard; 30,001 → heavy
  - test files, `vendor/`/`node_modules/`/`target/`-style paths, `*_pb2.py`, and non-source files → not counted
  - 1k lines + `pyo3` in Cargo.toml → standard; 1k + `numpy` in pyproject → standard; 1k + both → heavy; 40k + numpy → heavy
  - `numpy-utils`-style name that only contains a marker → no raise
  - Python backend + JS frontend, no binding marker → no floor
  - `Test rigor: light` in CLAUDE.md on a 40k repo → light, reason `set in CLAUDE.md`; `**Test rigor:** Heavy` → heavy; `Test rigor: medium` → exit 2 naming the allowed values
  - not a git work tree, or no tracked source → standard with the reason
- [ ] Write `test_rigor.py` cases for `project_level` first, then implement it in `rigor.py` (spec §4.1, §6.1, §6.3)
- [ ] CLI `rigor.py [--repo DIR]` prints `<level>: <reasons>` (spec §6.2)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -p 'test_rigor.py'`

### Task 2: Task levels and the per-file map
- Consumes: `project_level` built in Task 1 → `rigor.py`
- Cases:
  - task with `- Rigor: heavy` in a light project → heavy; with `Rigor: standard` in a standard project → standard
  - task with no `Rigor:` line → project level
  - `Rigor: light` in a standard project, or `Rigor: extreme` → refused (exit 2), naming the task, its line, and the project level with reasons
  - `Rigor:` inside a code fence → ignored
  - `--files`: a file in one raised task's footprint → that level; in two raised tasks' footprints → the higher; in no raised task → not listed
- [ ] Tests first, then `task_level` and the `--plan/--task` and `--plan/--store/--files` CLI paths (spec §4.2, §6.2)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -p 'test_rigor.py'`

### Task 3: Briefs carry the level
- Consumes: `task_level` built in Task 2 → `rigor.py`
- Cases: any task → brief has `Rigor: <level> (<reasons>)` before the task entry; raising task → its level; lowering or unknown `Rigor:` line → `BriefValidationError` naming the task and both levels
- [ ] Tests first in `test_task_brief.py`, then `task_brief.py` (spec §4.5, §6.4)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 4: The rigor table
- Cases: n/a — reference prose; its content is spec §4.3-4.4 verbatim in substance
- [ ] Write `rigor.md`: the level order and how the level is resolved (pointing at `rigor.py`), the per-role table, the realistic-caller definition, the every-level rules
- [ ] Verify: `rg -q 'realistic caller' chris-code/skills/subagent-driven-development/rigor.md`

### Task 5: Coders and reviewers apply the level
- Consumes: `rigor.md` built in Task 4
- Cases: n/a — contract prose; each contract points to its row of `rigor.md` instead of restating it
- [ ] Coders and `implementer-prompt.md`: read the brief's `Rigor:` line, write tests to its row, realistic first, every `Cases:` row tested at every level
- [ ] Spec and quality reviewers: severity for a missing case by the brief's level; a test that can't fail is S3 at every level; the quality reviewers' edge-case bullet becomes "covered to the brief's rigor level"
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 6: Mutation by level
- Consumes: `rigor.md` built in Task 4; `--files` built in Task 2
- Cases: n/a — contract prose; breaks, gating, and model per the `rigor.md` mutation rows
- [ ] `mutation-tester.md`: the `Rigor:`, `Plan:`, and `File levels:` inputs; breaks and gating per file level; report states the level applied per file (spec §6.5)
- [ ] verification Step 6: resolve the level and file levels, pass them and the plan path, and dispatch with `model: sonnet` at light, documented as the one exception to frontmatter models
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 7: Planning, TDD, docs, release
- Consumes: `rigor.md` built in Task 4; `rigor.py` CLI built in Tasks 1-2
- Cases: every consuming contract (3 coders, implementer prompt, spec reviewer, 3 quality reviewers, mutation tester, TDD, lean-plan) → names `rigor.md`; one missing → the drift test fails naming it
- [ ] lean-plan: resolve the level before writing rows, the optional raise-only task `Rigor:` line in the format, Self-Review §5 checks rows against the level
- [ ] TDD: "realistic first" ahead of the edge-case list, which becomes the heavy list, pointing to `rigor.md`
- [ ] SDD SKILL.md: briefs carry the level; a dispatch never restates or lowers it
- [ ] Drift test in `test_contract_enum_drift.py`
- [ ] README, docs (scripts reference, mutation-tester and reviewer entries, execution mechanics), CHANGELOG 0.12.0, plugin and marketplace versions
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

## 6. Acceptance checks

- `python3 -m unittest discover chris-code/tests` — all pass
- `python3 chris-code/skills/subagent-driven-development/scripts/rigor.py --repo <a large Python+Rust project with torch>` → `heavy` with reasons
- `python3 chris-code/skills/subagent-driven-development/scripts/rigor.py` on this repo → a level with reasons
- Spec §9 criteria each covered by a test or a `rg` check
