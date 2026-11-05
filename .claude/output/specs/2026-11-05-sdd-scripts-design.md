# SDD Rules Into Scripts Design Spec

## 1. Scope

Four mechanical decisions that subagent-driven-development (SDD), verification-before-completion and executing-plans now leave to the orchestrator's reading of prose move into the SDD scripts: `triage` takes the fix baseline itself; `run-state` classifies the store and names the next action; one `ledger.py commit` command takes a ready task from staging to a completed commit; and `ledger.py path` prints every handoff path. The prose rules each one replaces are deleted from the skills and docs. Intent: `.claude/output/intent/2026-11-05-sdd-scripts-intent.md`.

## 2. Goals

- A fix dispatch's `Fix baseline` and task file list come from `triage`'s output; an SDD run never calls `snapshot`.
- Re-running `triage` while a fix is open reprints that fix's step and baseline and never starts a new round.
- `run-state` opens with one verdict (`fresh`, `resume`, `remediation`, `finished`, `foreign`, `ambiguous`) and the next action.
- `ledger.py commit` replaces the ready → stage → gate → commit → complete sequence, and stages and commits exactly the task's footprint.
- Every record, report and brief path the orchestrator hands an agent comes from `ledger.py path`.
- SDD, verification, executing-plans and the reference docs lose the rules these replace.

## 3. Non-goals

- Routing the close round's findings through `triage` (deferred until a real run on 0.11+ produces data).
- Changing triage's routing rules, the record schemas (beyond the report-path naming below), or any agent's review behavior.
- Moving verification's close-round inline and test-only fixes onto `ledger.py commit`: they have no recorded footprint and keep their review-lite path.
- Retiring the `snapshot`, `gate` or `append --type complete` commands; they stay for manual and standalone use.
- A main-branch guard in `commit`.

## 4. System behavior

### 4.1 Triage takes the fix baseline

- When `triage` logs a new step whose kind is a fix kind (`patch`, `holistic`, `ruling`, `polish`), it appends a snapshot entry for the scope immediately after the triage entry, in the same locked section, and prints two extra lines: `Fix baseline: <tree>` and `Task files: <the scope's footprint, space-separated>`.
- `done` and `escalate` steps take no snapshot and print neither line.
- **An open fix is reprinted, not re-derived.** A fix is open when the scope's latest triage entry is a fix kind and no coder record in the scope with status `done` or `done_with_concerns` carries that entry's snapshot tree as its `baseline`. While a fix is open, `triage` prints the latest entry and its baseline unchanged, whatever else changed in the records (a coder's `needs_context` rewrite included), and logs nothing.
- The existing unchanged-inputs reprint also prints the latest entry's baseline when that entry is a fix kind.
- `baseline <tree>` and `check`'s baseline rules work unchanged on a triage-taken snapshot: they already resolve "the triage entry before this snapshot".

### 4.2 The store knows its plans, and `run-state` classifies it

- `task_brief.py`, on building a brief, appends a `plan` entry when the store has no entry for that plan's normalized path. Building more briefs from the same plan adds nothing.
- `run-state [--plan PLAN]` prints, before its existing sections, a `Verdict:` line and a `Next:` line. Without `--plan`, the latest recorded plan is used; with none recorded, classification uses only the store's other entries.
- Classification, first matching row wins:

| # | Condition | Verdict | Next |
|---|---|---|---|
| 1 | the progress log is empty | `fresh` | start at the plan's first task |
| 2 | no plan recorded, nothing completed, no close round | `fresh` | start at the plan's first task (only setup entries exist) |
| 3 | no plan recorded, and something completed or a close round exists | `ambiguous` | the store predates plan recording: read it and ask the user before clearing |
| 4 | the requested plan is not recorded | `foreign` | another plan's store: `clear` it (show `report` first when anything is open) |
| 5 | no close round | `resume` | the plan's first task `completed` doesn't list; when every task is complete, the whole-change gate, then verification |
| 6 | two close rounds | `finished` | this run has closed: `clear` before starting again |
| 7 | one close round, and the requested plan was first recorded after it and isn't the remediation note's plan | `finished` | the round belongs to an earlier, closed run: `clear` first |
| 8 | one close round and a remediation note | `remediation` | resume the note's plan at its first incomplete task; when it completes, the whole-change gate (`final-r2`), verification's round 2, then the note's front-end. When the requested plan is the original plan, say to run the note's plan instead |
| 9 | one close round, no remediation note | `ambiguous` | a close interrupted before its note, or a close that needed no remediation: ask the user |

- A **remediation note** is a `progress` entry on task `final` whose note starts `close-gate remediation r1:` and names `plan <path>` and `front-end <skill>` (the format verification already logs).
- A plan's task numbers come from its task headings, parsed the way `task_brief.py` parses them. A `--plan` path that doesn't exist is a usage error.

### 4.3 `ledger.py commit`

`commit --task N|final --message MSG --test CMD [--lint CMD] [--light]` runs, stopping at the first failure:

1. **Ready.** The blockers `ready` reports (`--light` passes through). Any blocker: print them, exit 1, stage nothing.
2. **Footprint.** For a task, the latest `stage` footprint. For `final`, every task's footprint plus the `changed_files` of the scope's coder records. For a task, a `changed_files` entry on its latest coder record outside the footprint is refused, naming the files and telling the orchestrator to re-issue `stage`.
3. **Stage.** Every change under the footprint paths (edits, new files, deletions), and nothing else.
4. **Gate.** The `gate` checks (labels, lint, test) on the staged footprint, writing the gate record. When the last gate record passed on exactly the tree just staged, the gate is not re-run. A failure: print the gate lines, exit 1, no commit.
5. **Commit.** Only the footprint paths, with MSG verbatim. Paths other tasks staged stay staged and are not committed. Git hooks run normally; a refused commit exits 1 with git's output and appends nothing.
6. **Complete.** Append `complete` for the scope with note `commits <before7>..<after7>` (and `light` when given), through the existing checks. If they refuse (a hook changed a gated file), print the new commit and the refusal and exit 1; the commit is never undone.

It prints the gate lines, `committed <hash>`, and `<scope> complete`.

`gate` changes to stage the footprint itself (the same rule as step 3), so re-checking a gate finding is `gate` then `triage`, with no staging step in prose.

### 4.4 `ledger.py path`

`path --task SCOPE [--agent NAME] [--kind record|report|brief]` prints an absolute path in the store; `--kind` defaults to `record`.

| SCOPE | Stem | record | report | brief |
|---|---|---|---|---|
| `N` | `task-N-<agent>` | `<stem>.json` | `<stem>-report.md` | `task-N-brief.md` (no `--agent`) |
| `final` | `final-<agent>`, or `final-r2-<agent>` once a close round exists | `<stem>.json` | `<stem>-report.md` | refused |
| `close` | `final-close-r<R>-<agent>`, R the latest close round | `<stem>.json` | `<stem>-report.md` | refused |
| `ruling` | `final-close-ruling-<agent>` | `<stem>.json` | `<stem>-report.md` | refused |
| `gate` | `gate-<agent>` | refused | `<stem>-report.md` | refused |

- `--agent` is required except for `brief`, and is refused when empty or containing `/`, `\` or `..`.
- `close` and `ruling` are refused when no close round exists.
- `clear` removes the new report names and keeps removing the old ones (`task-*-*.md`, `design-review-*.md`, `intent-recheck.md`, `mutation-review.md`).

## 5. Architecture

- **`store_state.py`** (new, beside `triage.py`): pure functions. `classify` takes the facts of §6.2 and returns a verdict and its next action. No file, git or ledger access.
- **`ledger.py`**: gathers the facts from the store and calls `classify` for `run-state`; owns `commit`, `path`, the triage snapshot and the open-fix check, and gate's staging. `path` uses the same scope logic (`scope_prefix`, close-round count) the records already use.
- **`task_brief.py`**: records the plan entry through `ledger.py`, as it already records deliveries.
- **Skills and docs**: SDD, verification, executing-plans, `docs/reference/ledger.md`, `docs/reference/agents.md` and `docs/explanation/execution-mechanics.md` call the commands and drop the replaced rules.

## 6. Canonical interfaces / data contracts

### 6.1 Progress entries

- `{"type": "plan", "path": "<repo-relative POSIX path>", "at": "<iso>"}`: one per distinct plan.
- A triage-taken snapshot is the existing snapshot entry, `{"type": "snapshot", "task": <scope>, "label": "triage <kind> round <R>", "tree": "<tree>"}`, logged directly after its triage entry.

### 6.2 `store_state.classify`

```python
Verdict = Literal["fresh", "resume", "remediation", "finished", "foreign", "ambiguous"]

def classify(*, has_entries: bool, plans: list[str], plan: str | None,
             plan_first_index: int | None, completed: set[str], plan_tasks: list[int],
             close_round_indices: list[int], remediation: dict | None) -> tuple[Verdict, str]:
    """remediation: {"plan": path, "front_end": skill} from the note, or None.
    Indices are positions in the progress log. Returns the verdict and the Next text."""
```

### 6.3 Command outputs

- `triage` on a fix step, after its existing lines: `Fix baseline: <tree>` then `Task files: <paths>`.
- `run-state`: first two lines `Verdict: <verdict>` and `Next: <action>`, then the existing sections.
- `commit`: gate lines as `gate` prints them, then `committed <hash>` and `<scope> complete`; exit 0 only when both happened.
- `path`: one absolute path, exit 0; a refusal exits 2 with the reason.

## 7. Invariants and constraints

- `commit` never stages or commits a path outside the scope's footprint, and never undoes a commit.
- Every fix-kind triage entry is followed by exactly one snapshot entry for its scope; no other entry type sits between them.
- An open fix never gains a second triage entry.
- Stores written by 0.13.0 keep working: no plan entry (rows 2 and 3), manual snapshots, old report names. No record schema version changes.
- Scripts stay stdlib-only; `ledger.py` imports `store_state` and `triage` and `task_brief` imports `ledger`, with no import cycle at module load (as `rigor.py` imports `task_brief` lazily today).
- No agent contract changes beyond the report paths it is handed.

## 8. Key decisions and tradeoffs

- **Classification is a pure module** (approach A, chosen over everything in `ledger.py`, or a wrapper `orchestrate.py`): the table is testable without git, and I/O commands stay with their siblings.
- **`commit` runs `git commit` itself** (the user's choice over stopping before the commit): the orchestrator still alone runs it, and `ready` refuses a task with no `done` triage step, so a subagent can't commit through it.
- **The plan is recorded by `task_brief.py`** (the user's choice over a `start` command, or no plan identity): no new step, and every SDD and executing-plans run builds briefs.
- **`gate` stages the footprint itself, and `commit` skips a gate that already passed on the same tree.** This is needed so a gate-finding fix is re-checked with `gate` alone, without re-introducing a staging rule, and without running the tests twice.
- **`final`'s footprint adds the coder's changed files**, since a whole-change fix has no stage entry and no parallel task.
- **Reports are uniformly `<stem>-report.md`**, renaming 0.13.0's `-review.md` reviewer verdicts and the coder's `task-N-report.md`; gate reports become `gate-<agent>-report.md` so a re-run finds its prior report at a fixed path.
- **`snapshot`, `gate` and `append --type complete` remain**, for executing-plans' manual fix snapshot, verification's test-only fix, and standalone use.

## 9. Acceptance criteria

- Each intent-ledger statement holds.
- **Triage:** a fix step logs one snapshot directly after it and prints both lines; `done` and `escalate` take none; an unchanged reprint and an open-fix reprint show the same baseline; a coder `needs_context` rewrite during an open fix logs no entry; a finished fix plus a re-check logs the next step with a new baseline; the first fix at `final` with no prior coder record behaves the same; `baseline <tree>` resolves a triage-taken snapshot.
- **Plans and `run-state`:** recording a plan is idempotent and a second plan is recorded separately; each table row yields its verdict; `--plan` omitted uses the latest plan; `resume` names the first incomplete task, including a remediation plan numbered after the original's; a missing `--plan` file is a usage error; a 0.13.0 store with completions and no plan entry is `ambiguous`.
- **`commit`:** a blocker stages nothing and commits nothing; an out-of-footprint coder file is refused by name; new files and deletions in the footprint are committed; a path another task staged stays staged and uncommitted; a gate failure writes the gate record, exits 1 and commits nothing; a pass makes one commit with the verbatim message and a `complete` entry with its range; a gate already passed on the same tree isn't re-run; `--light` works; `final` includes the coder's changed files; a refused `complete` after the commit reports the commit and exits 1.
- **`gate`:** stages the footprint itself and gates it.
- **`path`:** each scope and kind, `final` switching to `final-r2` after a close round, `close` following the latest round, the refusals in §4.4, and `clear` removing old and new names.
- **Prose:** no skill or doc tells the orchestrator to run `snapshot` in SDD, stage files by hand, append `complete` after committing, or build a record or report name; the stale-store, remediation-recognition and `--expect` paragraphs are replaced by pointers to `run-state` and `close-round`'s messages.
- The full suite passes, and the release is chris-code 0.14.0.

## 10. Validation strategy

- Unit tests drive `store_state.classify` row by row with plain facts.
- Store tests build progress logs and records in a temporary git repo and run the commands, asserting on log entries, the index, commits and printed lines, the way the existing ledger tests do.
- A fixture per prose rule removed is checked by searching the skills and docs for the retired instructions (`snapshot --task`, `git add <task files>`, `append --type complete` after a commit, hand-built `final-r2-`/`final-close-` names).
- The intent re-check runs the commands against a scratch run and judges each ledger statement by observed behavior.
