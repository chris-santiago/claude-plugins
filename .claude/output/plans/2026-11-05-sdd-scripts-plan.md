# SDD Rules Into Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use chris-code:subagent-driven-development (recommended) or chris-code:executing-plans to implement this plan task-by-task.

## 1. Objective

Move four mechanical SDD decisions into the scripts (triage's fix baseline, store classification, the commit sequence, handoff paths) and delete the prose rules they replace.

## 2. Spec references

- `.claude/output/specs/2026-11-05-sdd-scripts-design.md` §4.1 triage, §4.2 plans and run-state, §4.3 commit, §4.4 path, §6 interfaces, §7 invariants, §9 acceptance
- `.claude/output/intent/2026-11-05-sdd-scripts-intent.md`

## 3. Files

| Action | Path | Reason |
|--------|------|--------|
| Create | `chris-code/skills/subagent-driven-development/scripts/store_state.py` | pure classification table |
| Test | `chris-code/tests/test_store_state.py` | table rows |
| Modify | `chris-code/skills/subagent-driven-development/scripts/ledger.py` | plan entries, run-state verdict, triage snapshot and open fix, gate staging, `commit`, `path`, `clear` patterns |
| Modify | `chris-code/skills/subagent-driven-development/scripts/task_brief.py` | record the plan |
| Test | `chris-code/tests/test_ledger.py`, `chris-code/tests/test_task_brief.py` | command behavior over temp git repos |
| Modify | `chris-code/skills/subagent-driven-development/SKILL.md`, `chris-code/skills/verification-before-completion/SKILL.md`, `chris-code/skills/executing-plans/SKILL.md`, `chris-code/skills/subagent-driven-development/implementer-prompt.md` | call the commands, drop the replaced rules |
| Modify | `chris-code/docs/reference/ledger.md`, `chris-code/docs/reference/agents.md`, `chris-code/docs/explanation/execution-mechanics.md` | document the commands and names |
| Modify | `chris-code/CHANGELOG.md`, `chris-code/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | release 0.14.0 |

## 4. Constraints

- `commit` never stages or commits a path outside the scope's footprint, and never undoes a commit. It passes the message verbatim and adds no trailers.
- Every fix-kind triage entry (`patch`, `holistic`, `ruling`, `polish`) is followed by exactly one snapshot entry for its scope, with no other entry between them. An open fix never gains a second triage entry.
- Stores written by 0.13.0 keep working: no `plan` entry, manual snapshots, old report names. No record schema version change.
- Stdlib only. No import cycle at module load: `ledger.py` may import `store_state` and `triage`; anything in `ledger.py` that needs `task_brief` imports it inside the function, as `rigor.py` does.
- `snapshot`, `gate` and `append --type complete` stay as commands.
- No agent contract changes beyond the report paths it is handed.
- No project names in plugin prose, docs or changelog. Markdown is not hard-wrapped; em-dashes at most about 1 per 150 words.
- Run the suite from the repo root: a `test_task_brief` test is cwd-dependent.

## 5. Tasks

### Task 1: Store classification table
- Cases:
  - empty log → `fresh`, next is the plan's first task
  - no plan recorded, nothing completed, no close round → `fresh`
  - no plan recorded with a completion, or with a close round → `ambiguous`
  - requested plan not among recorded plans → `foreign`
  - plan recorded, no close round, tasks 1-2 of 1-4 complete → `resume`, next task 3; tasks 1-4 complete → `resume`, next is the whole-change gate then verification
  - two close rounds → `finished`
  - one close round, plan first recorded after it and not the note's plan → `finished`
  - one close round and a remediation note naming the requested plan, tasks 1-5 complete and the plan has tasks 6-7 → `remediation`, next task 6, then whole-change gate (`final-r2`), round 2, the note's front-end
  - one close round and a remediation note, requested plan is the original → `remediation`, next says to run the note's plan
  - one close round, no remediation note → `ambiguous`
- [ ] Tests first in `test_store_state.py`, then `classify` (spec §4.2 table, §6.2)
- [ ] Verify: `python3 -m unittest discover -s chris-code/tests -p 'test_store_state.py'`

### Task 2: Plans in the store, run-state verdict
- Consumes: `classify` built in Task 1 → `store_state.py`
- Cases:
  - first brief from plan A → one `plan` entry with A's repo-relative path; another brief from A → no new entry; a brief from B → a second entry
  - A given as `./x/a.md` and as an absolute path → one entry
  - `run-state --plan A` → first lines `Verdict: …` and `Next: …`, then today's sections
  - `run-state` without `--plan` → classified against the latest recorded plan
  - `--plan` naming a missing file → usage error, exit 2
  - store with completions and no `plan` entry → `Verdict: ambiguous`
  - remediation note text `close-gate remediation r1: plan <p>, decision <d>, intent <i>, front-end <s>` → note plan `<p>`, front-end `<s>`
- [ ] Tests first; record the plan through a `ledger.py` function `task_brief.py` calls; gather §6.2 facts and print the verdict (spec §4.2, §6.1, §6.3)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 3: Triage takes the fix baseline
- Cases:
  - `patch`, `holistic`, `ruling` and `polish` steps → one snapshot entry right after the triage entry, labelled `triage <kind> round <R>`, and output gains `Fix baseline: <tree>` and `Task files: <footprint>`
  - `done` and `escalate` → no snapshot, neither line
  - unchanged inputs → reprint with the same baseline, nothing logged
  - open fix, coder record rewritten as `needs_context` → reprint of the open step and baseline, nothing logged
  - coder record `done` carrying the baseline, then a re-check → a new step and, for a fix kind, a new snapshot
  - first fix at `final`, no coder record yet → snapshot taken; the fix stays open until a final-scope coder record carries the baseline
  - `baseline <tree>` on a triage-taken snapshot → prints that round
- [ ] Tests first, then the snapshot and open-fix check in `cmd_triage` (spec §4.1, §7)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 4: Gate stages the footprint
- Cases:
  - edited, new and deleted files in the footprint → staged and gated
  - a changed file outside the footprint → left unstaged and not gated
  - no change anywhere in the footprint → refused, naming the files
  - `final` → footprint is every task's files plus the final-scope coders' `changed_files`
- [ ] Tests first, then a scope-footprint helper and staging inside `cmd_gate`; update `TestGate` cases that staged by hand (spec §4.3 step 3, last paragraph)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 5: `ledger.py commit`
- Consumes: the scope-footprint helper and gate staging built in Task 4 → `ledger.py`
- Cases:
  - a `ready` blocker → blockers printed, exit 1, index and HEAD unchanged
  - task's latest coder record lists a changed file outside the footprint → refused naming it, nothing staged
  - all ready → one commit with the message verbatim, containing exactly the footprint's changes (new and deleted files included), and a `complete` entry noting `commits <before7>..<after7>`
  - another path already staged by a parallel task → still staged afterwards, not in the commit
  - gate failure → gate record written, exit 1, no commit, no `complete`
  - last gate passed on the same staged tree → gate not re-run
  - `--light` → light `complete` entry; `--task final` → footprint includes the final coders' changed files
  - git refuses the commit (a rejecting pre-commit hook) → exit 1 with git's output, no `complete`
  - `complete` refused after the commit (hook rewrote a gated file) → prints the new commit and the refusal, exit 1, commit kept
- [ ] Tests first, then the subcommand (spec §4.3, §6.3)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 6: `ledger.py path`
- Cases:
  - `--task 3 --agent python-coder` → `<store>/task-3-python-coder.json`; `--kind report` → `task-3-python-coder-report.md`; `--task 3 --kind brief` → `task-3-brief.md`
  - `--task final` → `final-<agent>…`, and `final-r2-<agent>…` once a close round exists
  - `--task close` → `final-close-r<R>-<agent>…` for the latest round R; `--task ruling` → `final-close-ruling-<agent>…`; either with no close round → refused
  - `--task gate --agent intent-reviewer --kind report` → `gate-intent-reviewer-report.md`; `gate` with `record` → refused
  - `brief` with any scope but a task number → refused; missing `--agent` for record or report → refused; agent with `/`, `\` or `..` → refused; refusals exit 2
  - `clear` → removes `gate-*-report.md` and `*-report.md` names along with `design-review-*.md`, `intent-recheck.md`, `mutation-review.md`
- [ ] Tests first, then the subcommand and `clear` patterns (spec §4.4)
- [ ] Verify: `python3 -m unittest discover chris-code/tests`

### Task 7: Skills and docs call the commands
- Consumes: commands built in Tasks 2, 3, 5, 6
- Cases: n/a — contract prose; each replaced rule becomes a pointer to the command that now enforces it
- [ ] SDD: dispatch lists take paths from `path`; fix dispatches take `Fix baseline` and `Task files` from `triage`; the snapshot bullet, the resume-with-original-baseline sentence, hand staging, `gate` then commit then `append --type complete`, and the Durable Progress stale-store and remediation-recognition paragraphs go; resume is `run-state --plan`; Example Workflow updated
- [ ] verification: report and record paths from `path` (`gate`, `close`, `ruling`); Step 1's `--expect` sub-bullet becomes "follow `close-round`'s message"
- [ ] executing-plans: Step 1 uses `run-state --plan`; Step 3 becomes `commit --light`; paths from `path`
- [ ] implementer prompt: report path from the dispatch only (no hard-coded name)
- [ ] `ledger.md` (new commands, run-state verdict, gate staging), `agents.md` naming paragraph replaced by `path`, `execution-mechanics.md`
- [ ] Verify: `! rg -q 'snapshot --task|git add <task files>' chris-code/skills/subagent-driven-development/SKILL.md && ! rg -q 'final-close-r<N>-|final-close-ruling-<|final-r2-<agent|design-review-<agent' chris-code/skills/subagent-driven-development/SKILL.md chris-code/skills/verification-before-completion/SKILL.md chris-code/docs/reference/agents.md && python3 -m unittest discover chris-code/tests`

### Task 8: Release 0.14.0
- Cases: n/a — version markers and changelog
- [ ] CHANGELOG `## [0.14.0] - 2026-11-05 — <title>` with a summary paragraph; plugin and marketplace versions
- [ ] Verify: `rg -q '"version": "0.14.0"' chris-code/.claude-plugin/plugin.json && rg -q '0.14.0' .claude-plugin/marketplace.json && python3 -m unittest discover chris-code/tests`

## 6. Acceptance checks

- `python3 -m unittest discover chris-code/tests` — all pass
- Each spec §9 criterion is covered by a test or the Task 7 `rg` check
- A scratch run in a temp repo: `triage` prints `Fix baseline`, `run-state --plan` prints a verdict, `commit` makes one commit with a `complete` entry, `path` prints each scope's name
