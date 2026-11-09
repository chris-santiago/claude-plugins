# The Close Through Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

Route the completion close through typed records and `ledger.py triage --task close`, replace the close's requirements check with a plan coverage check, and stop filing close rulings as run-notes; release chris-code 0.16.0.

## 2. Spec references

- `.claude/output/specs/2026-11-09-close-through-triage-design.md §4 System behavior`
- `.claude/output/specs/2026-11-09-close-through-triage-design.md §6 Canonical interfaces / data contracts`
- `.claude/output/specs/2026-11-09-close-through-triage-design.md §7 Invariants and constraints`
- `.claude/output/specs/2026-11-09-close-through-triage-design.md §9 Acceptance criteria`
- `.claude/output/intent/2026-11-09-close-through-triage-intent.md`

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Modify | `chris-code/skills/subagent-driven-development/scripts/triage.py` | close rule set beside the task rule set |
| Modify | `chris-code/skills/subagent-driven-development/scripts/ledger.py` | close roles, `close` scope, paths, `close-round`, close triage, filing, defer, promotion, commit, run-note filing |
| Modify | `chris-code/skills/subagent-driven-development/scripts/store_state.py` | `closing` / `finished` verdicts, remediation verdict removed |
| Modify | `chris-code/skills/subagent-driven-development/scripts/task_brief.py` | `Spec coverage:` line enforced with `--spec` |
| Test | `chris-code/tests/test_triage.py` | close rule set |
| Test | `chris-code/tests/test_ledger.py` | close records, paths, close-round, end-to-end closes, run-note filing |
| Test | `chris-code/tests/test_store_state.py` | new verdicts, legacy close entries |
| Test | `chris-code/tests/test_task_brief.py` | coverage line |
| Test | `chris-code/tests/test_note_store.py` | close follow-up fields, `from: close` |
| Test | `chris-code/tests/test_shared_protocol.py` | typed-record section identical across the two design reviewers |
| Modify | `chris-code/agents/{python,rust}-design-reviewer.md`, `intent-reviewer.md`, `mutation-tester.md` | typed record beside the report |
| Modify | `chris-code/agents/spec-reviewer.md` | plan coverage mode |
| Modify | `chris-code/skills/verification-before-completion/SKILL.md` | close rewritten around triage; Step 4 removed |
| Modify | `chris-code/skills/subagent-driven-development/SKILL.md` | close rulings on `--task close`, narrower run-note rule, `final-r2` gone |
| Modify | `chris-code/skills/lean-plan/SKILL.md` | coverage step and `Spec coverage:` line |
| Modify | `chris-code/skills/remediating-issues/SKILL.md`, `chris-code/skills/coherent-change/SKILL.md`, `chris-code/skills/finishing-a-development-branch/SKILL.md` | close-gate variant and round-2 references removed |
| Modify | `chris-code/README.md`, `chris-code/docs/**`, `chris-code/assets/decks/**`, `chris-code/docs/slides/chris-code-guide.html` | describe the new close |
| Modify | `chris-code/CHANGELOG.md`, `chris-code/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | release 0.16.0 |

## 4. Constraints

- The per-task loop, its rule set, its two-round cap and the whole-change gate at `final` are unchanged; every existing per-task test passes unmodified except where it asserts a removed close contract (`close-round --expect`, `final-r2`, `--task gate|ruling`).
- The orchestrator writes no close finding and assigns no tier; every close tier comes from `triage.py`.
- Blocking at the close is exactly: intent `not-met` (any severity) or severity 4–5 from any close gate. Everything else is filed, once.
- A filed or deferred close finding is filed once, even when a re-check raises it again.
- Snapshots, baselines and fix cycles at `close` reuse the 0.15.0 helpers (`_step_fix_cycle`, `_fix_is_open`, `_check_fix_baseline`); no parallel copies.
- Close scope log = entries after the latest `close_round` entry; legacy `close_round` entries (with a `round` field) never block a new close.
- `triage.py` stays pure (no file I/O, no git, no import of ledger).
- Helper scripts get correctness fixes only; no refactors outside what this plan needs.
- Plugin prose: no hard-wrapped markdown, no project names, task numbers or run histories, em-dashes at most about one per 150 words.
- Tests run from the repo root: `python3 -m unittest discover -s chris-code/tests -q`.

## 5. Tasks

### Task 1: Close rule set in triage.py
- Consumes: close tiers and step kinds from spec §4 *Triage at the close* and §6 *Triage entry at `close`*
- Cases:
  - intent not-met at S2 → blocking, patch (local reach)
  - design S4 local → blocking, patch; design S4 contract → blocking, holistic
  - design S3, mutation survivor (S3), any S1–S2 → filed, once
  - not-met plus S3 → patch sending only the not-met; S3 filed
  - only filed findings, no can't-tell → done on the first entry
  - open can't-tell → clarify (no round), even with blocking work present
  - blocking open after 2 patch/holistic rounds → escalate
  - ruling logged after escalate → ruling round sending the open blocking findings
  - blocking finding resolved `user ruling: defer ...` → settled and filed; plain waiver → settled, not filed
  - promotion naming a filed finding → ruling round sending it (reopened)
  - filed finding raised again by a re-check → not filed twice
  - held contest → escalate, as in tasks
- [ ] Add the close rule set as a pure function with the task set's entry shape (spec §5, `triage.py` bullet)
- [ ] Recheck at close is `raising` for patch, holistic and ruling; `intent` for clarify
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 2: Close records, scope and paths
- Consumes: record contracts from spec §6 *Close records*, *Paths*, *`close-round`*
- Cases:
  - design record `pass`/`concerns` with tagged findings → passes `check`
  - intent record: not-met statement with a finding citing it → passes; not-met with no finding → refused; finding citing a met statement → refused; can't-tell without `needs` → refused; `pass` with a not-met → refused
  - mutation record `skipped` / `inconclusive` with no findings → passes
  - status outside the role's set → refused
  - `path --task close --agent X` → `close-X.json`; `--kind report` → `close-X-report.md`
  - `path --task gate` / `--task ruling` → error naming `--task close`
  - close decision doc named `close-decision-c<N>` → accepted
  - `close-round --note T` with no open close → appends `close_round` with head and note; with a close of this release not `done` → refused; after legacy entries only → appends
  - `close-round --expect N` → error naming the new usage
  - `append --type progress --task close` and `note --from close` → accepted
- [ ] Add the three roles and their validation (spec §6)
- [ ] Add `close` to every scope table, regex and parser; drop `final-r2`, `gate`, `ruling` scopes (spec §6 *Paths*)
- [ ] Replace `close-round` with the single-start form (spec §4 *Starting the close*)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 3: Close triage, filing and commit in ledger.py
- Consumes: close rule set built in Task 1 → `triage.py`; close records and scope built in Task 2 → `ledger.py`
- Cases:
  - spec §9 bullets 1–6, each driven through `cmd_check` and `cmd_triage` → the stated step and filings
  - filed follow-up → carries `finding`, `source`, `report`, `from: close` and the finding's rule
  - clarify step → no snapshot entry
  - fix round at close → snapshot with `fix_cycle`; coder record `close-<coder>` at cycle 2 passes `check`
  - `commit --task close` with the fix finished → commits the footprint, completes nothing; with the fix open → refused, nothing committed
  - promotion after `done` → ruling round at close; the promoted follow-up resolved as promoted
- [ ] Wire `triage --task close` to the close rule set, with the finding inputs it needs (source role, statement verdicts)
- [ ] File close deferrals with their fields; honor `user ruling: defer`; read promotion rulings (spec §6 *Deferral and promotion*)
- [ ] `commit --task close` follows the `final` fix path (spec §4 *Fixing*)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 4: run-state for the close
- Consumes: close scope log built in Task 2 → `ledger.py`
- Cases:
  - tasks incomplete → resume (unchanged)
  - all tasks complete, close started, latest close triage not done → closing, next action names the close's latest step
  - latest close triage done → finished
  - store with only legacy close entries or a `close-gate remediation r1:` note → not `remediation` (verdict removed); classified by the new rules
  - rounds section → lists `close` with its triage kinds in order
- [ ] Rework `store_state.py` verdicts (spec §4 *`run-state`*)
- [ ] Render the close's rounds, rulings and deferrals in `run-state`
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 5: Spec coverage line in task_brief.py
- Consumes: `Spec coverage:` contract from spec §6
- Cases:
  - `--spec S`, plan with `Spec coverage: S — pass (<existing report>)` → brief built
  - `--spec S`, `Spec coverage: S — user ruling: <text> (<existing report>)` → brief built
  - `--spec S`, no coverage line → refused, message names the lean-plan step
  - `--spec S`, line names another spec → refused
  - `--spec S`, report file missing → refused
  - no `--spec` → no check
- [ ] Parse and enforce the line when `--spec` is given
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 6: Skipped store notes are not filed
- Consumes: coder deferral filing in `ledger.py`
- Cases:
  - `notes_skipped` naming `note#run-note[…]` → nothing filed
  - `notes_skipped` naming `note#task-note[…]` → nothing filed
  - `notes_skipped` naming a reviewer finding id → filed as before
- [ ] Skip store-note ids when collecting coder deferrals
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -q`

### Task 7: Agent contracts
- Consumes: record contracts from spec §6; plan coverage mode from spec §4 *Plan coverage check*
- Cases: n/a — agent prompt text; record shapes are pinned by Task 2's `check` tests
- [ ] Design reviewers: a shared typed-record section (record path from dispatch, role `design-reviewer`, tags per rubric, `ledger.py check` until it passes), identical in both files
- [ ] Intent reviewer: `statements` and one finding per not-met, `needs` on can't-tell
- [ ] Mutation tester: closing-review mode writes the record (survivors as S3 local findings); on-demand mode writes none
- [ ] Spec reviewer: plan coverage mode (spec and plan only, report with `PASS` / `GAPS`, uncovered requirements and out-of-spec tasks)
- [ ] Add the design reviewers' record section to the shared-section drift test
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -p 'test_shared_protocol.py' -q`

### Task 8: Skills
- Consumes: spec §4 (whole section)
- Cases: n/a — skill prose; behavior is pinned by Tasks 1–6
- [ ] Rewrite verification's close around spec §4; remove Step 4, `--expect`, round 2 re-dispatch, per-round remediation plans and the four-way sort; mutation ruling on `--task close`
- [ ] SDD: close rulings on `--task close`, run-notes only for rules coders act on, `final-r2` and close remediation runs removed
- [ ] lean-plan: the coverage step and the `Spec coverage:` line in the plan format
- [ ] remediating-issues: drop the close-gate variant; coherent-change and finishing-a-development-branch: drop round-2 references
- [ ] Verify: `! /usr/bin/grep -rEq --exclude-dir=scripts -- '--expect|final-r2|--task gate|--task ruling|[Cc]lose-gate variant|Requirements Check|close-gate remediation r1' chris-code/skills`

### Task 9: Docs, decks and release
- Consumes: spec §4; skill text from Task 8
- Cases: n/a — documentation and version metadata
- [ ] README, `docs/` (reference, explanation, how-to, tutorial), the guide (`docs/slides/chris-code-guide.html`, with `assets/decks/chris-code-guide.html` kept identical), and the decks describe the new close; re-render the Marp decks' HTML
- [ ] CHANGELOG `## [0.16.0] - <date>` section; bump plugin and marketplace to 0.16.0
- [ ] Verify: `! /usr/bin/grep -rEq -- '--expect|final-r2|--task gate|--task ruling|[Cc]lose-gate variant|Requirements Check|close-gate remediation r1' chris-code/README.md chris-code/docs chris-code/assets && python3 -m unittest discover -s chris-code/tests -q`

## 6. Acceptance checks

- `python3 -m unittest discover -s chris-code/tests -q` — all pass
- Every bullet of spec §9 holds, each backed by a test from Tasks 1–6
- A standalone `python-quality-reviewer` pass over the script changes and a re-check, both approving, before the merge question
