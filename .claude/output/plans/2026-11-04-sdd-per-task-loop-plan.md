# SDD Per-Task Review-Fix Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

Replace SDD's per-task review-fix loop with script-computed triage over tagged findings (spec §4), add the coder and decision-doc evidence `check` enforces, the scripted gate and `ready`, the plan-contract checks, and the prose that drives them.

## 2. Spec references

- `.claude/output/specs/2026-11-04-sdd-per-task-loop-design.md` (§4 behavior, §6 contracts, §7 invariants, §8 decisions, §9 acceptance)
- `.claude/output/intent/2026-11-04-sdd-per-task-loop-intent.md` (revised 2026-11-05)

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Create | `chris-code/skills/subagent-driven-development/scripts/triage.py` | Pure tier and step rules (§4.1-§4.2) |
| Create | `chris-code/tests/test_triage.py` | Rule tests for the pure module |
| Modify | `chris-code/skills/subagent-driven-development/scripts/ledger.py` | Schema 2, record checks, `triage`/`gate`/`ready`, renderers, removals |
| Modify | `chris-code/skills/subagent-driven-development/scripts/task_brief.py` | `Verify:` command, `open:` rows, row shape |
| Test | `chris-code/tests/test_ledger.py` | Schema-2 fixtures; new and removed behavior |
| Test | `chris-code/tests/test_note_store.py` | Schema-2 fixtures; `--rule`; close batch |
| Test | `chris-code/tests/test_task_brief.py` | Plan-contract refusals; fixture rows |
| Test | `chris-code/tests/test_contract_enum_drift.py` | Schema version and contract-example guards |
| Test | `chris-code/tests/test_no_stale_references.py` | Removed names; skip `site/` and `CHANGELOG.md` |
| Modify | `chris-code/agents/spec-reviewer.md` | Tags, `case`, `contests`, `reopens`, re-check scope, open-choice rule |
| Modify | `chris-code/agents/python-quality-reviewer.md` | Same, plus consumer search, CLAUDE.md and sentinel checks |
| Modify | `chris-code/agents/rust-quality-reviewer.md` | Same as python |
| Modify | `chris-code/agents/pytorch-quality-reviewer.md` | Same as python |
| Modify | `chris-code/agents/python-review-lite.md` | Tags at `final`; public-symbol reach rule |
| Modify | `chris-code/agents/rust-review-lite.md` | Same as python |
| Modify | `chris-code/agents/python-coder.md` | Coder obligations (§4.3, §4.4, §4.11) |
| Modify | `chris-code/agents/rust-coder.md` | Same as python |
| Modify | `chris-code/agents/pytorch-coder.md` | Same as python |
| Modify | `chris-code/skills/subagent-driven-development/implementer-prompt.md` | Same as the coders |
| Modify | `chris-code/skills/subagent-driven-development/SKILL.md` | Per-task loop, pre-flight, whole-change gate |
| Modify | `chris-code/skills/executing-plans/SKILL.md` | Light path (§4.9) |
| Modify | `chris-code/skills/remediating-issues/SKILL.md` | Per-task variant: holistic only, decision `cases`/`couplings`/`premise` |
| Modify | `chris-code/skills/lean-plan/SKILL.md` | `Cases:` rows, `open:` rows, `Verify:` rule, light-path offer |
| Modify | `chris-code/skills/verification-before-completion/SKILL.md` | Close batch in the completion report |
| Modify | `chris-code/skills/requesting-code-review/SKILL.md` | Commit gate is `gate` |
| Modify | `chris-code/docs/explanation/execution-mechanics.md` | The fix loop |
| Modify | `chris-code/docs/explanation/the-pipeline.md` | Per-task variant line |
| Modify | `chris-code/docs/reference/ledger.md` | Command reference |
| Modify | `chris-code/docs/reference/agents.md` | Record fields |
| Modify | `chris-code/docs/tutorials/getting-started.md` | Triage step |
| Modify | `chris-code/docs/slides/chris-code-guide.html` | Fix loop and ledger views |
| Modify | `chris-code/README.md` | Fix-loop paragraph and per-task diagram |
| Modify | `chris-code/CHANGELOG.md` | 0.11.0 entry |
| Modify | `chris-code/.claude-plugin/plugin.json` | Version 0.11.0 |

## 4. Constraints

- **Worktree.** Work happens on the worktree branch; the main checkout stays on `main`. Installed chris-code skills and agents are symlinks into the main checkout, so the tooling in use is never the code under edit.
- **Tests.** Run from the repository root: `python3 -m unittest discover chris-code/tests` must exit 0. Never filter it: `ledger.py`, the fixtures, and the agent contract examples are shared contracts.
- **Realistic tests.** Each `check` rule gets one accepting test and one refusing test whose input is the mistake an agent would realistically make. No type-permutation matrices (`3.0`, `"3"`, `true`, `null` for one field). Round behavior is tested as scenarios over store fixtures.
- **Dependencies.** Stdlib only.
- **Pure triage module.** `triage.py` has no `import ledger`, no file I/O, and no subprocess. It takes plain data (record stems with their dicts, log entries, booleans `ledger.py` computes) and returns plain data. `ledger.py` runs as `__main__`, so a module importing `ledger` would load a second copy with a different `RecordError`.
- **Errors and exit codes.** Library functions raise `RecordError` or `RuntimeError`; only `main()` exits. `labels` keeps exit 1 for hits and 2 for errors. `gate` and `ready` exit 1 on a failure or blocker. Every other command exits 1 on error.
- **Schema.** `SCHEMA_VERSION = 2`. A schema-1 record is refused with a message to finish that run on the previous chris-code release or `ledger.py clear` the store. No converter.
- **Tier matrix (spec §4.1), exactly:** S1-S2 `local`/`class` → note; S1-S2 `contract` → defer; S3-S5 `local`/`class` → patch; S3-S5 `contract`, a `root cause:` concern, or a `reach_raised` finding → holistic; a held contest → held. `recurring` and `introduced_by_fix` never change a tier.
- **Round bound.** At most two rounds of kind `patch` or `holistic` per scope; ruling and polish rounds don't count.
- **Ids.** Finding, concern, and open-choice ids come from the existing `_item_id` scheme. Routing reads tags and flags; it never infers sameness from id differences, except that an id still present after a re-check means the finding is still raised.
- **Site format.** `path`, `path:line`, or `path:start-end`; lines ≥ 1, start ≤ end, path relative to the repo toplevel.
- **Gate.** Commands run from the repo toplevel through the shell (Verify lines use `!` and `&&`); they come from the plan via the orchestrator's CLI arguments. Each passes only on exit 0.
- **Scope `final`.** `triage`, `gate`, `ready`, `complete` count only entries after the last `close_round` entry and read the current prefix's records (`final`, or `final-r2` after a close round).
- **Unchanged commands** not named in spec §6.6 keep their behavior and output.
- **Removed names in tests** are built from parts, as `test_no_stale_references.py` does, so the stale-reference guard stays clean.
- **Contract examples** stay one JSON object whose first key is `"schema"`; `test_contract_enum_drift.py` parses them.
- **Prose and comments** match the surrounding file's voice, use no em-dash as default punctuation, and never cite project names, task numbers, or this review process. Code comments state behavior.

## 5. Tasks

### Task 1: Schema 2 and reviewer finding tags
- Consumes: spec §4.1, §6.1; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::validate_record`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_require_strs`
- Cases:
  - record with `"schema": 2` → accepted; `"schema": 1` → refused with the migration message
  - spec issue or quality/lite finding with `severity` 1-5, `reach` in {local, class, contract}, non-empty `rule`, non-empty `sites` → accepted
  - finding missing `reach`, or with `severity` 0 or 6 → refused, naming the entry and field
  - `sites` with `a.py:9-5` or `a.py:` or an empty list → refused, naming the site
  - spec issue with `case` and severity 2 → refused; with severity 3 → accepted
  - spec status `compliant` with only S1-S2 issues → accepted; `issues` with nothing S3+ → refused; `approved` with an S3 finding → refused
  - `recurring` entry whose site matches a finding's site → accepted; unmatched → refused, naming the site
  - reviewer `contests` entry with verdict `concede` or `hold` and a reason → accepted; verdict `maybe` or empty reason → refused
  - finding with `reopens` naming an id → accepted by `validate_record` (the store check is Task 5)
  - every agent contract example → its `schema` equals `ledger.SCHEMA_VERSION`
- [ ] Add `SITE_RE` and `_validate_finding_tags`; apply them in `validate_record` for spec, quality, and lite records; add the `contests` shape.
- [ ] Bump `SCHEMA_VERSION`; add the schema-1 message.
- [ ] Change every `"schema": 1` to `2` in contract examples (`agents/*.md`, `implementer-prompt.md`, `remediating-issues/SKILL.md`) and in fixtures (`test_ledger.py`, `test_note_store.py`, `test_task_brief.py`); give fixture findings valid tags. Only version lines change in prose files.
- [ ] Generalize the schema regex in `test_contract_enum_drift.py` to assert equality with `ledger.SCHEMA_VERSION`.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 2: Coder record and decision doc fields
- Consumes: spec §4.3, §4.4, §6.2, §6.3; built in Task 1 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::SITE_RE`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::_validate_decision`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_validate_fix`
- Cases:
  - sweep with `findings`, `rule`, `rows`, and `searched` {command, result} → accepted; with `inspected` instead → accepted
  - sweep with neither `searched` nor `inspected`, or a blank `searched.result` → refused, naming the sweep
  - row with `site` and `hunk` → accepted; with `site` and `already_correct` → accepted; with only `site` → refused
  - `tests_first` entry with test, command, failed_output → accepted; `n/a` `structural` with a reason → accepted; `n/a` `existing` naming a test → accepted
  - `tests_first` `n/a` `trivial` → refused (not in the list); `existing` without a test → refused
  - `open` entry with `precedent` site → accepted; with `no_precedent` reason → accepted; with neither → refused
  - `contested` reason `wrong` or `plan-conflict` with evidence → accepted; reason `disagree` → refused
  - `test_changes` entry with kind `changed`/`deleted`/`skipped` and a reason → accepted; kind `edited` or blank reason → refused
  - `root cause: src/cache.py:12 evidence` → accepted; `root cause: the cache` → refused
  - `consumers_checked` entry with empty `consumers` and `searched` → accepted; without evidence → refused
  - decision fix choice whose every case has `site` and `test`, with `couplings` whose sites are case sites and a `premise` {assumption, probe} → accepted
  - decision case missing `test`, a coupling site no case lists, or a missing `premise` → refused, naming the choice
- [ ] Add `_validate_coder_evidence` (sweeps, rows, tests_first, open, contested, reach_raised, notes_skipped, test_changes, decision_rows, decision) and apply it in `validate_record` for coder records.
- [ ] Extend the decision `fix` choice validation for `cases[].site`, `cases[].test`, `couplings`, `premise`.
- [ ] Update the existing decision fixtures to the new shape; add tests for every case above to `test_ledger.py`.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 3: Store checks on coder records (footprint, labels, model)
- Consumes: spec §4.6, §6.2; built in Task 2 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::_validate_coder_evidence`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::stage_map`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_normalize_path`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::find_process_labels`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_check_coder_model`
- Cases:
  - `sites_outside` path not in the task's latest `stage` files → accepted; equal to a footprint file (after `_normalize_path`) → refused, naming it
  - `root cause:` path inside the footprint → refused; outside → accepted
  - `final` scope → footprint is the union of every task's latest footprint
  - record carrying `sites_outside` for a task with no `stage` entry → refused with the `ledger.py stage` message; a record with neither field → no stage entry needed
  - record outside a store → footprint and labels checks skipped
  - finished fix whose changed files have no label hit → accepted; a hit excused by a `label false positive: <file>: <line>` concern → accepted; any other hit → refused, listing `path:line: label`
  - store not inside a git work tree → labels scan skipped, other checks still run
  - `open` entry whose `precedent` path doesn't exist in the repo → refused, naming it; an existing path → accepted
  - `agent: executing-plans` on any model → accepted; dispatched coder on opus without a logged ruling → refused (unchanged)
- [ ] Add `task_footprint` and `_excused_label_hits`; wire both into `check_record`; add the model exemption.
- [ ] Add tests for every case above to `test_ledger.py`, using temporary git repos as the existing labels tests do.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 4: Pure triage rules
- Consumes: spec §4.1, §4.2, §4.5, §6.5
- Cases:
  - each matrix cell → its tier; S3 `local` flagged `recurring` → patch; S3 `contract` → holistic; `root cause:` concern → holistic; `reach_raised` S3 `local` → holistic; contest answered `hold` → held
  - first triage, open S3 `local` only → patch, recheck `raising`; only gate findings sent → recheck `gate`
  - first triage, an S3 `contract` or a `root cause:` → holistic, recheck `all`
  - after one patch round, open S3 `local` → patch (round 2); open S3 `contract` → holistic (round 2)
  - after one holistic round, a new S3 `local` → patch (round 2)
  - after two patch/holistic rounds with open work → escalate, recheck `none`
  - escalate followed by a `user ruling:` entry → ruling over open non-waived findings, recheck `raising`; escalate with no new ruling → escalate again; a ruling round that leaves open work → escalate
  - no open work, notes never sent → polish, recheck `none`; notes sent in an earlier round and covered by the coder record → not open, done
  - no open work, a task note filed and undelivered → polish
  - nothing open → done
  - contest answered `concede` → finding closed; contested finding unanswered → not closed (the record is refused in Task 5)
  - defer finding → listed for filing; a defer id already in an earlier entry's `filed` → not listed again
  - coder records at c1 (sonnet) and c2 (opus) → `model: opus`; no coder record → `model: null`
  - previous entry had 5 findings; now 3 open, 1 flagged `recurring`, 1 flagged `introduced_by_fix` → `survived: 1`, `introduced: 1`, `closed: 4`
  - first entry → `closed: 0`
  - `triage.py` source → contains no `import ledger`
- [ ] Create `triage.py` with tier, open-work, step, recheck, and telemetry functions over plain data.
- [ ] Create `test_triage.py` with a test for every case above.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 5: `ledger.py triage`, settlement, and `resolve`
- Consumes: spec §4.2, §4.5, §4.6, §6.5, §6.6; built in Task 4 → `chris-code/skills/subagent-driven-development/scripts/triage.py`; built in Task 3 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::task_footprint`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::finding_ids`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::concern_ids`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_check_resolvable`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::cmd_note`
- Cases:
  - `triage --task 3` with clean reviewer records → appends one entry of kind `done` and prints it
  - `triage` with one S3 local finding → entry kind `patch`, prints the finding's id, tier, rule, and the raising reviewer
  - `triage` while a record in scope is malformed → refuses, names it, writes nothing; with no reviewer record → refuses
  - a coder record with `contested` → the entry lists each contest with the reviewer that raised it, and prints them for forwarding
  - a re-check record that omits an answer to a contest the last entry forwarded to it → `check` refuses it, naming the contest
  - a conceded contest, a waived finding, and an accepted open choice → all three ids in the next entry's `settled`, with the entry's `tree` set to the current tree
  - a finding with `reopens` naming a settled id and a site in lines changed since that settlement tree → accepted; site outside changed lines → refused; naming an id that isn't settled → refused
  - an S1-S2 `contract` finding, a `notes_skipped` entry, or a `sites_outside` site → filed once as a follow-up with its rule; an outside site covered by a later task's footprint → filed as a task-note for that task; a second `triage` → nothing refiled
  - `resolve <open finding id> --note "user ruling: waive"` → accepted, and the next triage excludes it; with a note not starting `user ruling:` → refused
  - `resolve <open-choice id> --note "user ruling: accept"` → accepted
  - open: a re-check finding whose id equals a settled finding's id (identical text) but carries no `reopens`: does `check` refuse it?
  - open: does a ruling round cover every open non-waived finding at the escalation, or only findings a ruling names by id?
- [ ] Add `triage_inputs` (records, log, undelivered notes, rulings since the last escalate, footprints) and `latest_triage`; add `cmd_triage` and its subparser; file deferrals through the existing note path.
- [ ] Add the `contests` completeness and `reopens` store checks to `check_record`.
- [ ] Extend `_check_resolvable` to finding and open-choice ids.
- [ ] Add tests for every case above to `test_ledger.py`, as scenarios over store fixtures.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 6: Fix checks and removal of the route machinery
- Consumes: spec §4.3, §6.2, §8 removals; built in Task 5 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::latest_triage`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::find_baseline`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_check_fix_baseline`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::diff_trees`
- Cases:
  - finished fix with a `patch` triage entry between the previous snapshot and its baseline → accepted; with no fix-kind entry in that window → refused
  - patch fix where every sent finding is in exactly one of sweeps, contested, reach_raised, notes_skipped (notes only) → accepted; a sent finding missing → refused naming it; one listed twice → refused
  - a row whose hunk overlaps the fix diff → accepted; a row hunk on lines the fix didn't change → refused (claimed but not built)
  - a sent finding flagged `recurring` at `a.py:40` with no row for `a.py:40` → refused
  - S3 finding sent in a patch round with no `tests_first` entry → refused; with an `n/a` `existing` entry → accepted
  - holistic fix naming `task-3-decision-c2` at cycle 2, doc passing `check`, every case mapped in `decision_rows` to an overlapping hunk → accepted; a case unmapped → refused; the c1 doc named at cycle 2 → refused
  - a pre-existing test file where the fix changes `assert x == 2` to `assert x == 3` → refused without a `changed` entry, accepted with one
  - fix deletes a `def test_` function, or adds `@pytest.mark.skip` / `#[ignore]` → refused without a `deleted` / `skipped` entry
  - fix edits a helper in a pre-existing test file with no assertion on the changed line → no entry needed
  - fix adds a new test file → no `test_changes` needed
  - `baseline TREE --task 3` after a patch entry → prints `round: patch`, `recheck: raising`, the findings and contests; after a holistic entry → also prints the expected decision path; with no fix-kind entry → errors
  - `snapshot --task 3 --label x` → records task, label, tree; a removed route flag → rejected by argparse; old log entries carrying route fields → still load and render
  - the removed fix-count command → rejected as unknown
- [ ] Add the triage-entry, coverage, row-hunk, flagged-site, tests-first, decision-row, and test-change checks to `check_record`.
- [ ] Rewrite `cmd_baseline`; strip route flags from `cmd_snapshot`; delete `non_trivial_fix_count`, `SETTLED_BY`, `_check_flagged_fix_route`, `_check_reroute`, the route helpers and the fix-count wiring, including from `__all__`.
- [ ] Replace the route and fix-count tests in `test_ledger.py` with tests for every case above; build removed names from parts.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 7: `ledger.py gate` and the gate requirement on `complete`
- Consumes: spec §4.7, §6.4, §6.6; built in Task 3 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::task_footprint`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_excused_label_hits`
- Cases:
  - staged scope files, labels clean, lint exit 0, test exit 0 → `pass`, `findings: []`, exit 0
  - labels hit not excused → `fail`, no finding, hit printed, exit 1; excused hit → passes
  - lint exit 1 → `fail`, no finding
  - test exit 1 → `fail` with one S3 `local` finding whose rule names the command and whose sites are the scope files
  - test command `! rg -q 'TODO' src/` with no matches → passes
  - no `--lint` given → lint skipped and recorded as skipped
  - scope with no footprint → refused with the `ledger.py stage` message; nothing staged in the scope → refused before running anything
  - gate record → written to `<scope>-gate.json`, passes `check` under role `gate`; `fail` listed by `open`
  - staged tree → recorded via `git write-tree`; the real index unchanged after the run
  - `append --type complete` with a passing gate whose blobs match HEAD for every scope file → accepted; no gate, a failed gate, or a file changed after the gate → refused, naming the file
- [ ] Add the `gate` role to `STATUS_ENUMS`, `cmd_gate` and its subparser, and the gate check in `cmd_append`.
- [ ] Update existing `complete` callers in `test_ledger.py` and `test_note_store.py` to pass a gate first; add tests for every case above.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 8: `ready`, `--light`, and the close batch
- Consumes: spec §4.6, §4.7, §4.9, §6.6; built in Task 5 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::latest_triage`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::_check_no_open_escalation`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::_check_task_notes_settled`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::render_report`
- Cases:
  - `ready --task 3` after a `done` triage with nothing else open → exit 0
  - each blocker → listed, exit 1: no triage yet; last step not done; a held finding; an unanswered open choice; an undelivered note; an owned open disclosure or question; an open escalation; an open `cannot_verify`; a malformed record; at `final`, an open `duplication_pending`
  - several blockers at once → all listed
  - `ready --light` with no triage entry and no reviewer records → exit 0 when the other checks pass
  - `append --type complete --light` → accepted without triage; the entry records `light`, and `report` shows the task ran light
  - `complete` without `--light` → refuses with every `ready` blocker listed
  - `note --kind follow-up --rule "size must be positive"` → stored with the rule; `--rule` on a task-note → refused; blank rule → refused
  - `report` with follow-ups under two rules and one without → grouped per rule, rule-less last under "(no rule)", one line offering a batch remediation; settled follow-ups render unchanged
- [ ] Add `cmd_ready` and its subparser; route `cmd_append`'s completion checks through the same blocker list; add `--light` to both.
- [ ] Add `--rule` to `note`; add the grouping to `render_report`.
- [ ] Add tests for every case above to `test_ledger.py` and `test_note_store.py`.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 9: Renderers: `run-state`, `read`, `stats`
- Consumes: spec §6.5, §6.6; built in Task 5 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::latest_triage`; existing `chris-code/skills/subagent-driven-development/scripts/ledger.py::render_run_state`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::cmd_stats`
- Cases:
  - `run-state` with tasks mid-loop → a "Rounds" section listing each in-flight task's triage kinds in order, and a "Parked" section listing each parked task's held findings, open choices, and escalation
  - `read` → triage entries render as `task N triage: <kind> (round R, recheck <set>)`
  - `stats` → per task, each triage entry's kind, model, closed, survived, introduced, plus the count of tests-first `n/a` entries per category
  - a log holding pre-change route-bearing snapshots → renders without error
- [ ] Update `render_run_state`, the `read` renderer, and `cmd_stats`; add tests for every case above.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 10: `task_brief.py` plan-contract checks
- Consumes: spec §4.10, §6.6; existing `chris-code/skills/subagent-driven-development/scripts/task_brief.py::validate_cases`, `chris-code/skills/subagent-driven-development/scripts/task_brief.py::_cases_blocks`
- Cases:
  - `- [ ] Verify: \`python3 -m unittest\`` → accepted; also as `- Verify:` and `**Verify:**`
  - `Verify: run the tests` (no backticked command) → refused, exit 3, naming the task; no `Verify:` outside a code fence → refused
  - `Cases: size=0, size<0 → ValueError` → accepted; `Cases: size=0 -> ValueError` → accepted
  - `Cases: validate sizes` → refused, naming the row
  - sub-bullet rows each with `→` → accepted; one sub-bullet without → refused, naming it
  - `Cases: n/a — wiring only` → accepted; `Cases: preserves ordering; covered by tests/test_x.py` → accepted
  - a row `open: what does size=None do?` → refused, naming the question
  - open: how is an inline `Cases:` value with `;`-separated segments checked: does each segment need its own arrow, or the value as a whole?
  - fixtures in `test_task_brief.py` that model a valid task → gain a `Verify:` line and arrow rows
- [ ] Add `validate_verify` and the row-shape and `open:` checks alongside `validate_cases`, called where it is; update the module docstring's exit codes.
- [ ] Add tests for every case above to `test_task_brief.py`.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 11: Reviewer contracts
- Consumes: spec §4.2, §4.4, §4.5, §4.8, §4.11, §6.1; built in Task 1 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::_validate_finding_tags`
- Cases:
  - each reviewer contract example (spec-reviewer, three quality reviewers, two review-lite agents) → passes `ledger.validate_record` with its first status alternative (new drift test)
  - each example's first finding → shows `severity`, `reach`, `rule`, `sites`; spec-reviewer's also shows `case`; each quality and spec example shows a `contests` answer
  - prose → covers tagging, the S3 floor for a named case, re-check scope per `recheck`, answering every forwarded contest, `reopens`, re-running sweep commands, judging tests-first `n/a` and flagged test changes, the open-choice rule, the quality reviewers' consumer search and CLAUDE.md and sentinel checks, and lite's public-symbol reach rule at `final`
  - prose → no remaining sentence relies on a per-task review-lite gate
- [ ] Update the six reviewer agent files; add the drift tests to `test_contract_enum_drift.py`.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 12: Coder contracts
- Consumes: spec §4.3, §4.4, §4.11, §6.2; built in Task 2 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::_validate_coder_evidence`
- Cases:
  - each coder contract example (three coders plus `implementer-prompt.md`) → passes `ledger.validate_record` with status `done` (new drift test)
  - each example → shows sweeps with rows and `searched`, `tests_first`, `open`, `contested`, `reach_raised`, `notes_skipped`, `test_changes`, `decision_rows`, `decision`
  - prose → covers the sweep procedure, tests first and the `n/a` categories, open choices with a precedent, contest, reach raise, `test_changes`, the `root cause: <path>` format and the footprint rule, running `Verify:` exactly, reading the round from `baseline`, implementing a decision doc's cases, and that `check` enforces labels
  - prose → no five-way route reading remains
- [ ] Update the three coder agents and `implementer-prompt.md`; extend the coder drift test.
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 13: SDD skill rewrite
- Consumes: spec §4, §5, §8; built in Tasks 5-8 → `chris-code/skills/subagent-driven-development/scripts/ledger.py::cmd_triage`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::cmd_gate`, `chris-code/skills/subagent-driven-development/scripts/ledger.py::cmd_ready`
- Cases: n/a — prose contract text that must state spec §4 and name no removed command or flag
- [ ] Replace the Process flowchart with: review → triage → its printed step → ready → gate → commit → complete, including park and the stage batch.
- [ ] Pre-flight: batch `open:` rows with the thin-`Cases:` scan and write answers into the plan.
- [ ] Rewrite the fix-loop text in "Constructing Reviewer Dispatches": run `triage`, dispatch what it prints, re-dispatch exactly the `recheck` set, forward contests and the settled list, the holistic dispatch (general-purpose agent, `model: opus`, remediating-issues per-task variant, `$STORE/<scope>-decision-c<cycle>.json`), parking and the stage batch with recommendations and the "land as-is" option.
- [ ] Replace the per-task review-lite text with spec §4.7, and the whole-change gate section with §4.8.
- [ ] Update Handling Implementer Status (`root cause:` and open choices through triage), Judging from Compressed Reports (claim-checker for `cannot_verify` only), Model Selection, Durable Progress, Red Flags, and the Example Workflow.
- [ ] Verify: `! rg -n -e 'fix-count' -e '--settled-by' -e '--non-trivial' -e 'Non-trivial' chris-code/skills/subagent-driven-development/SKILL.md && python3 -m unittest discover chris-code/tests`

### Task 14: executing-plans, lean-plan, remediating-issues, verification, requesting-code-review
- Consumes: spec §4.3, §4.6, §4.9, §4.10, §6.3; built in Task 13 → `chris-code/skills/subagent-driven-development/SKILL.md`
- Cases: n/a — prose contract text across five skills that must match spec §4.3, §4.6, §4.9, §4.10, §6.3
- [ ] executing-plans: the light path per §4.9 (briefs, `stage`, open choices and tests first, quality reviewers, two rounds then the user, `gate`, `ready --light`, `complete --light`); replace "bite-sized steps" with "implement against the brief"; align its description with lean-plan's offer.
- [ ] lean-plan: `Cases:` rows with `→` and expected results, `open:` rows, the `Verify:` exit-0 rule with the `! rg -q` form, the offer describing executing-plans as the light path for small work, and Self-Review §5 rewritten to "decide every behavior as a row" without the boundary-input checklist.
- [ ] remediating-issues per-task variant: holistic rounds only, task-wide, opus, `root cause:` concerns, the decision `cases` site and test, `couplings`, `premise`; update its contract example; drop the fix-count sentence.
- [ ] verification-before-completion "After Verification Passes": the close batch grouped by rule with fix, file, or ignore per item. requesting-code-review: the commit gate is `gate`.
- [ ] Verify: `! rg -n -e 'fix-count' -e 'bite-sized' chris-code/skills/remediating-issues/SKILL.md chris-code/skills/executing-plans/SKILL.md && rg -q 'exit 0' chris-code/skills/lean-plan/SKILL.md && python3 -m unittest discover chris-code/tests`

### Task 15: Docs, release, and the stale-reference guard
- Consumes: spec §6.6, §8; built in Task 13 → `chris-code/skills/subagent-driven-development/SKILL.md`; existing `chris-code/tests/test_no_stale_references.py::STALE_PATTERNS`
- Cases:
  - a doc mentioning the removed fix-count command or a removed snapshot flag → the guard flags it; the same text in `CHANGELOG.md` or under `site/` → not flagged
  - an injected reference in the guard's self-test → caught
  - docs → describe only the new loop: `execution-mechanics.md` "The fix loop"; `reference/ledger.md` (new commands, `resolve` ids, `note --rule`, plain `snapshot`, `--light`); `reference/agents.md` (tags, contests, coder evidence, gate record, decision cases); `the-pipeline.md` per-task variant; `getting-started.md` triage step; the slides; the README fix-loop paragraph and diagram
  - `CHANGELOG.md` → a 0.11.0 entry with Added, Changed, and Removed, noting that schema-1 stores and plans without `Verify:` commands or arrow rows are refused
  - `plugin.json` version → 0.11.0
- [ ] Update the docs, slides, README, CHANGELOG, and `plugin.json`.
- [ ] Add the new patterns, the `site` skip, and the CHANGELOG exclusion to `test_no_stale_references.py`, with the pinned-pattern self-test.
- [ ] Verify: `python3 -m unittest discover chris-code/tests && ! rg -n --glob '!**/site/**' --glob '!**/CHANGELOG.md' -e 'fix-count' -e '--settled-by' -e '--non-trivial' -e 'non_trivial_fix_count' -e '_check_reroute' chris-code`

## 6. Acceptance checks

- `python3 -m unittest discover chris-code/tests` exits 0 from the repo root.
- `! rg -n --glob '!**/site/**' --glob '!**/CHANGELOG.md' -e 'fix-count' -e '--settled-by' -e '--non-trivial' -e 'non_trivial_fix_count' -e '_check_reroute' chris-code` exits 0.
- `python3 chris-code/skills/subagent-driven-development/scripts/ledger.py triage --help && python3 chris-code/skills/subagent-driven-development/scripts/ledger.py gate --help && python3 chris-code/skills/subagent-driven-development/scripts/ledger.py ready --help` exits 0.
- After merge, in a new session: one real plan on the new loop; compare its `stats` with the baseline run (2.39 fix cycles per task, 144 rulings, 45% fix-introduced later findings, reviewer dispatches per task). The intent-reviewer checks the intent ledger against it.

## 7. Open questions

- Task 10: an inline `Cases:` value with `;`-separated segments (`size>0; size=0 → ValueError`): does each segment need its own arrow, or does the value need at least one?
- Task 5: a re-check finding whose id equals a settled finding's id (identical text) but carries no `reopens`: should `check` refuse it? The spec says unmarked restatements can't be detected; identical text can be.
- Task 5: which findings a ruling round covers: every open non-waived finding at the escalation, or only those a ruling names by id?
