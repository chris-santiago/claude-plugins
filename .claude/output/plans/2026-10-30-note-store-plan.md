# Orchestrator Note Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

Add typed orchestrator notes, delivery tracking, the stage map, handles, `run-state`/`report` views, a store lock and two fix-loop integrity checks to SDD's ledger, wire `task_brief.py` to the store, and update the skills and docs so the store is the only path notes travel.

## 2. Spec references

- `.claude/output/specs/2026-10-30-note-store-design.md` (whole spec; §4 behavior, §6 contracts, §9 acceptance)
- `.claude/output/intent/2026-10-30-note-store-intent.md`

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Modify | `chris-code/skills/subagent-driven-development/scripts/ledger.py` | entries, commands, gates, views, lock, fix-loop checks |
| Modify | `chris-code/skills/subagent-driven-development/scripts/task_brief.py` | notes from the store, delivery entry, drop `--note` |
| Test | `chris-code/tests/test_ledger.py` | new behavior |
| Test | `chris-code/tests/test_task_brief.py` | new brief behavior |
| Test | `chris-code/tests/test_contract_enum_drift.py` | coder contracts show `baseline` |
| Modify | `chris-code/agents/python-coder.md`, `rust-coder.md`, `pytorch-coder.md` | `baseline` record field |
| Modify | `chris-code/skills/subagent-driven-development/implementer-prompt.md` | `baseline` record field |
| Modify | `chris-code/skills/subagent-driven-development/SKILL.md` | Run Notes section and integration |
| Modify | `chris-code/skills/verification-before-completion/SKILL.md` | report, follow-ups, close gates |
| Modify | `chris-code/skills/executing-plans/SKILL.md` | session delivery, filing notes |
| Modify | `chris-code/skills/finishing-a-development-branch/SKILL.md` | report before cleanup |
| Modify | `chris-code/skills/remediating-issues/SKILL.md`, `chris-code/skills/coherent-change/SKILL.md` | follow-up note in an SDD run |
| Modify | `chris-code/docs/explanation/execution-mechanics.md`, `chris-code/docs/reference/skills.md`, `chris-code/README.md` | describe the store |
| Create | `chris-code/docs/reference/ledger.md` | ledger command reference |
| Modify | `chris-code/zensical.toml`, `chris-code/docs/reference/index.md` | link the new page in the nav and the reference index |
| Modify | `chris-code/CHANGELOG.md`, `chris-code/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.10.0 |

## 4. Constraints

- Run every test from the repo root: `python3 -m unittest discover -s chris-code/tests`. `pytest` is not installed. Some task_brief tests depend on the working directory.
- `progress.jsonl` stays append-only; only `clear` deletes it. Every refusal appends nothing and writes nothing.
- Existing entry types, ids and command behavior on stores without new entries stay unchanged, except the two fix-loop checks (spec §4.8). Existing tests keep passing unless they relied on a trivial snapshot after a flagged review or on a fix record without `baseline`; update only those.
- Records written before the upgrade stay loadable: `baseline` is optional at load and required only at `check` on a finished fix (cycle 2 or later, `done`/`done_with_concerns`), mirroring how coder `model` is handled.
- New entries carry `at` (UTC ISO-8601, seconds). Note ids are `note#<kind>[<first 8 hex of sha1 over canonical JSON of {kind, text, for, owner, from}, absent keys omitted>]`, matching the existing `_entry_digest` style.
- The lock is POSIX `flock` on `<store>/.lock`, held across read, checks and write in every mutating command (spec §6.4). Read-only commands take no lock. `clear` never deletes `.lock`.
- Refusals raise `RecordError` (exit 1) with the offending ids and the remedy; argument errors exit 2 via argparse.
- New subcommands follow the existing pattern: a `cmd_*` function that raises, an `add_parser(..., parents=[store_parent])`, a `main` branch, and a line in the module docstring's usage block. Exported derivations go in `__all__`; `cmd_*` handlers stay out of it.
- `task_brief.py` touches the log only through exported ledger functions; it never writes `progress.jsonl` directly. A failed brief writes no file and no delivery entry.
- Stages render as "stage N", never "S<N>" (collides with severity tags).
- Helper scripts are not packages: no refactors beyond what the change needs.
- Prose: never hard-wrap markdown; at most about one em-dash per 150 words; no project names, wave names or task numbers from any user project in plugin text, changelog or docs.
- No skill or doc calls a ledger script by a relative `scripts/` path; use `$SDD_SCRIPTS/...` (`tests/test_scripts_path.py`).
- Commits carry no Claude authorship trailer.

## 5. Tasks

### Task 1: Store lock, timestamps and the run scope
- Consumes: spec §6.4 lock, §4.3 last bullet, §4.4 run-level rulings
- Cases: lock held by every mutating command (`append`, `resolve`, `snapshot`, `close-round`, `clear`, `check`'s history append) across read-check-write; two processes appending concurrently yield only whole valid lines in `progress.jsonl` and `history.jsonl`; read-only commands take no lock; `clear` leaves `.lock`; lock file created on first use in a store with no `.lock`; `append --type progress --task run` accepted and stored as `"run"`; `append --type complete --task run` refused with nothing appended; `--task 0`, `--task -1`, `--task foo` still exit 2; `read` renders a run-scoped progress entry
- [ ] Add the lock helper and wrap every existing mutating command (spec §6.4)
- [ ] Add the `at` timestamp helper used by all new entry types
- [ ] Accept `run` as a progress task scope; refuse it for `complete`
- [ ] Tests, including a multi-process append test
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 2: Notes: filing, resolution, rendering
- Consumes: spec §4.1, §4.6, §6.1, §6.2 (`note`, `resolve`); lock and `at` from Task 1 → `ledger.py`
- Cases: each of the seven kinds files and prints its id; `task-note` requires `--for` (positive int); `disclosure` and `question` require `--owner` (positive int or `close`); `--for` on any other kind, `--owner` on any other kind, empty `--text`, unknown kind → refused; `--from` accepts a positive int, `final` or `run`; `--for`/`--owner` naming a completed task → refused naming `--owner close`; identical note (same id) filed twice → refused naming the existing id and whether it is resolved; `resolve` of an open task-note, run-note, follow-up, disclosure or question succeeds; empty note text on any note resolve → refused; question resolve without `user ruling:` (case-insensitive) → refused; checkpoint or disposition id → refused as not resolvable; already-resolved note id → refused (existing message); unknown note id → refused listing open resolvable ids; record-derived resolvable items keep today's behavior; `read` renders every note kind and resolutions of note ids readably (no "unknown entry")
- [ ] `note` subcommand and entry (spec §6.1, §6.2)
- [ ] Extend `resolve` to open note ids (spec §4.6)
- [ ] Render notes in `read`
- [ ] Tests (functions and one CLI subprocess per subcommand)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 3: Delivery, waivers and the delivery gates
- Consumes: spec §4.2, §4.3, §6.1 (`delivery`, `waiver`), §6.3; notes from Task 2 → `ledger.py`
- Cases: required set for an unfinished task = its active task-notes + active run-notes + open disclosures it owns; questions are never required (never embedded) but block; completed tasks have nothing required; a resolved (superseded/retired) note is never required; delivered = listed in a delivery for the task, or waived for (task, id); `notes --task N` prints required notes marked delivered/undelivered plus owned questions; `--deliver` records exactly the currently required ids (`via: session`), and a second `--deliver` with nothing new still succeeds; `--waive ID --reason TEXT` with an id not required for N, an empty reason, or without `--reason` → refused; `--deliver` and `--waive` together → exit 2; `complete --task N` refuses on any undelivered note, open owned disclosure or open owned question (listing ids) and still refuses on open escalations; a note filed after N's latest delivery is undelivered; a run-note filed while tasks 5 and 6 are in flight blocks both and not a completed task; `close-round` refuses on any open disclosure, open question, or active task-note whose target is unfinished, appending nothing; `open` lists undelivered notes per unfinished task, open disclosures and open questions, and no follow-ups, dispositions or checkpoints; exported derivations and the locked delivery-append function exist for `task_brief.py`
- [ ] Derivations (required, delivered, undelivered, active) as exported pure functions
- [ ] `notes` subcommand with `--deliver` and `--waive`; `delivery` and `waiver` entries
- [ ] Gates in `complete` and `close-round`; new items in `open`; render in `read`
- [ ] Tests
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 4: Stage map and handles
- Consumes: spec §4.3 (`stage`), §6.1 (`stage`, `handle`), §6.2; lock from Task 1 → `ledger.py`
- Cases: `stage --task N --stage K --files ...` records an entry; re-staging N replaces its footprint and stage (latest wins); paths normalized (`./a.py` and `a.py` equal; posix normpath); overlapping path with another unfinished task in the same stage → refused naming the task and paths; same path in a different stage, or with a completed task, → allowed; empty `--files`, stage 0 or negative → exit 2 or refused; `handle --task N|final --role NAME --agent ID` records an entry; latest per (task, role) wins; empty role or id → refused; `read` renders both
- [ ] `stage` and `handle` subcommands and entries
- [ ] Tests
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 5: Views and the guarded clear
- Consumes: spec §4.5 (`run-state`, `report`), §4.3 (`clear`); entries from Tasks 1–4 → `ledger.py`
- Cases: `run-state` on an empty store, a mid-run store and a finished store shows spec §4.5's seven sections in order; task state is complete (complete entry), in flight (any delivery, record or snapshot), else not started; tasks with state but no stage listed as unstaged; fix counts for in-flight tasks; notes owed per unfinished task and active task-notes for not-started targets; handles only for unfinished tasks and `final`, labeled session-only; only the newest checkpoint with its timestamp; `report` lists rulings (progress and resolutions starting `user ruling:`, any case, including `run` scope and question resolutions), open filed follow-ups, `unlisted case:` concerns derived from current coder records (case-insensitive prefix), resolved follow-ups with resolutions, dispositions and waivers, disclosures (resolved with landing note; open flagged), questions (ruled; open flagged); `clear` with any open follow-up, disclosure or question → refused listing them, nothing deleted; `clear --discard-open` deletes as today; `clear` on a store with none open behaves as today; `.lock` survives either way
- [ ] `run-state` and `report` subcommands
- [ ] `clear` guard and `--discard-open`
- [ ] Tests
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 6: Fix-loop integrity checks
- Consumes: spec §4.8, §6.1a; lock from Task 1 → `ledger.py`
- Cases: coder record `baseline` optional at load (absent loads; present must be a non-empty string, else malformed); at `check`, a finished fix record (cycle ≥ 2, `done`/`done_with_concerns`) without `baseline` → refused; naming a tree with no snapshot for the record's task → refused; reusing a baseline an earlier cycle of the same record used (per history) → refused; same cycle re-checked with the same baseline (resumed `needs_context`/`blocked` fix, rewritten record) → passes; python and rust coder records of one task sharing one baseline at their own cycles → pass; cycle-1 and `needs_context`/`blocked` records need no baseline; `final` scope works the same; coder history entries carry `baseline`; `snapshot` without `--non-trivial` refused while any current reviewer record of the task (all reviewer roles, task-N or final scopes) has non-empty `recurring` or `introduced_by_fix`, naming the records, appending nothing; allowed when those lists are empty or absent; `--non-trivial` with a route proceeds and `fix-count` increments; update only the existing tests that relied on the old behavior
- [ ] `baseline` validation at load and at `check`; history field
- [ ] Trivial-snapshot refusal on flagged reviewer records
- [ ] Tests
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 7: task_brief.py reads notes from the store
- Consumes: spec §4.2, §4.7; exported derivations and the delivery-append function from Task 3 → `ledger.py`
- Cases: `--note` rejected by argparse (exit 2); required task-notes and run-notes embedded under "Cross-task notes" with id and source; owned disclosures under "Disclosures this task owes", section omitted when none; no required notes → "(none)"; superseded or retired notes never embedded; questions never embedded; a successful brief appends one delivery listing exactly the embedded ids; any validation failure, a malformed `progress.jsonl` (exit 2, message names file and line) or a failed brief write → no brief file and no delivery entry; store with no `progress.jsonl` → brief builds with "(none)"; rebuilding a brief for the same task logs a new delivery
- [ ] Remove `--note` and the `note` request field
- [ ] Read required notes during validation; embed; append delivery after the write
- [ ] Update tests that used `note=`; add the cases above
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 8: Coder contracts show `baseline`
- Consumes: spec §6.1a; check behavior from Task 6 → `ledger.py`
- Cases: each of `python-coder.md`, `rust-coder.md`, `pytorch-coder.md` and `implementer-prompt.md` shows `"baseline"` in its typed-record JSON and a field bullet saying it is the dispatch's `Fix baseline:` tree on a fix (cycle 2+), never a tree the coder made, and that `check` refuses a reused or unsnapshotted one; the contract-drift test fails if any coder contract omits it
- [ ] Edit the four contracts
- [ ] Extend `tests/test_contract_enum_drift.py`
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 9: SDD skill text
- Consumes: spec Appendix (SDD bullet); commands from Tasks 1–7
- Cases: n/a — prose. Must cover: a "Run Notes" section (seven kinds and when to file each; only the orchestrator files; subagents report cross-task items in their records; never keep cross-task state in a file of your own; one-time import of an existing free-form notes file, then no further appends); pre-flight records the stage map with `stage`; File Handoffs drops `--note` and routes cross-task notes through `note`; unlisted cases derived by `report`; Durable Progress adds `run-state` at start and after compaction, a checkpoint before any pause or `/compact`, `handle` at dispatch with the fresh-dispatch fallback, and the corrected list of commands that read the log; deferred root cause → follow-up note; judgment calls on concerns → disposition; waivers; fix-baseline and fix-cap passages say `check` and `snapshot` enforce them; Red Flags (no private notes file; no session end without a checkpoint); example workflow uses `note` instead of `--note`
- [ ] Edit `SKILL.md`
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests` (scripts-path and stale-reference tests)

### Task 10: Other skills
- Consumes: spec Appendix; commands from Tasks 1–7
- Cases: n/a — prose. verification-before-completion: completion report built from `ledger.py report`; "log as a follow-up" names `note --kind follow-up`; close-owned questions asked and disclosures landed before `close-round`. executing-plans: `notes --task N --deliver` at task start; files notes the same way. finishing-a-development-branch: run `ledger.py report` and carry follow-ups and disclosures into the PR body or summary before removing the store. remediating-issues and coherent-change: inside an SDD run, the north-star follow-up is a `follow-up` note.
- [ ] Edit the five skills
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

### Task 11: Docs, changelog and version
- Consumes: Tasks 1–10
- Cases: n/a — docs. `execution-mechanics.md` (durable progress, cross-task notes, follow-ups, fix-loop checks); README ledger bullets; `docs/reference/ledger.md` listing every subcommand with one line each, linked from the reference index and site nav; `docs/reference/skills.md` SDD paragraph; CHANGELOG `0.10.0` with a title and lead paragraph, Added/Changed sections, each bullet led by a bold sentence; version `0.10.0` in `chris-code/.claude-plugin/plugin.json` and the root `.claude-plugin/marketplace.json`
- [ ] Edit docs and README; create the ledger reference page
- [ ] Changelog and version bump
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests`

## 6. Acceptance checks

- `python3 -m unittest discover -s chris-code/tests` — all pass
- Every acceptance criterion in spec §9 is covered by a test
- `ledger.py --help` lists `note`, `notes`, `stage`, `handle`, `run-state`, `report`
- No `--note` remains in task_brief usage, SKILL.md or docs; no ledger call by relative `scripts/` path
