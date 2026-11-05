# Ledger commands

`ledger.py` is the typed record store behind `subagent-driven-development`, `executing-plans` and `verification-before-completion`. It lives in the SDD skill's `scripts/` directory and is always called through `$SDD_SCRIPTS`, the skill's absolute scripts path. Every command except `diff-since` and `labels` takes `--store DIR`; the default store is `.sdd/` at the repo toplevel.

Commands that write the store hold an exclusive lock on its `.lock` file while they read, check and write, so parallel agents never interleave lines or both pass a check only one of them should. The store doesn't exist until its first write (normally `store-dir`), and only that write runs unlocked. A refusal writes nothing, not even the store.

Records carry schema version 2. A record or store written by an earlier release is refused with a message to finish that run on the release that started it, or to `clear` the store and start over.

## Reading the run

| Command | What it prints |
|---|---|
| `run-state` | Where the run stands: the stage map with each task's state, each task in flight's rounds so far, what's parked for the stage's batched question (an escalation, a held finding, an open behavior choice), notes owed, open disclosures and questions, the count of blocking items, agent handles, and the latest checkpoint |
| `read` | The whole store as markdown: every record, then every progress-log entry |
| `open` | What blocks: open record items (`cannot_verify`, `duplication_pending`, escalations, open statuses, malformed records), notes tasks in flight haven't received, and open disclosures and questions |
| `completed` | Task ids with a completion entry, one per line |
| `shapes` | Shared symbols the coders declared, as every brief carries them |
| `stats` | Each task's verdicts cycle by cycle from the check history, the records that flagged `introduced_by_fix` or `recurring`, each triage round by task (kind, coder model, and how many findings it closed, saw survive and saw a fix introduce), and the tests-first `n/a` counts by category |
| `report` | What the completion report lists: user rulings, the open follow-ups grouped by rule as the close batch (fix, file or ignore each), the coders' `unlisted case:` concerns, follow-ups settled during the run, dispositions and waivers, disclosures with where each landed, questions with their rulings, and the tasks that ran light |
| `notes --task N` | The notes task N must receive, marked delivered or not, and the questions it owns |
| `findings <decision-path>` | The finding ids a holistic decision record at that path must account for, and the decisions it must reconcile with |
| `baseline <tree> --task N\|final` | The round a fix baseline starts: its kind, who re-checks it, the decision doc path for a holistic round, and the findings and contests it covers. Errors when no fix-kind triage entry precedes that snapshot |
| `store-dir` | The resolved store path, creating it and its self-ignoring `.gitignore` if needed |

## Routing a task

| Command | What it does |
|---|---|
| `triage --task N\|final` | Computes the next step from the reviewers' tagged findings, the coder's record and the scope's earlier triage entries: `patch`, `holistic`, `polish`, `ruling`, `escalate` or `done`. Appends one triage entry, files the loop's deferrals (S1-S2 contract-reach findings, notes a coder skipped, sites a sweep found outside the task) as follow-ups, and prints the step, who re-checks it, each finding's id, tier and rule, the contests to forward with each one's reviewer, and the settled findings. Refuses, writing nothing, while a record in scope is malformed or when the scope has no reviewer record |
| `ready --task N\|final [--light]` | Lists every blocker to a commit and exits 1 while any remains: triage not at `done`, a held finding, an open behavior choice, an undelivered note, an open disclosure or question the task owns, an open escalation or `cannot_verify`, a malformed record, and at `final` an open `duplication_pending`. `--light` is executing-plans' path and skips only the triage, held and open-choice checks |
| `gate --task N\|final --test CMD [--lint CMD]` | Runs labels on the staged scope files' added lines, then lint, then the task's `Verify:` command, each passing only on exit 0, and writes a gate record. Refuses when the scope has no recorded footprint or nothing staged in it. Exits 0 on pass, 1 on fail. A labels or lint failure returns to the coder as the same attempt. A test failure becomes one S3 local finding over the scope's files and enters triage |

## Writing the run

| Command | What it does |
|---|---|
| `note --kind KIND --text "..." [--for N] [--owner N\|close] [--from N\|final\|run] [--rule TEXT]` | Files an orchestrator note and prints its id. Kinds: `task-note` (`--for` a task), `run-note`, `disclosure` and `question` (`--owner` a task or `close`), `follow-up` (`--rule` is the rule it falls under, which `report` groups by), `disposition`, `checkpoint` |
| `notes --task N --deliver` | Records that the session (not a brief) delivered every note the task requires |
| `notes --task N --waive ID --reason "..."` | Records that a required note doesn't apply to the task, with why |
| `stage --task N --stage K --files PATH...` | Records a task's stage and file footprint; refuses a path another unfinished task in the same stage claims |
| `handle --task N\|final --role NAME --agent ID` | Records the agent id behind a task's role, so it can be continued after a compaction |
| `append --type progress\|complete --task N\|final\|run --note "..." [--light]` | A progress note or a task's completion. `--task run` is for rulings about the whole run. `complete` re-runs `ready` and refuses without a passing gate whose staged tree matches the committed blobs of the scope's files. `--light` is executing-plans' path and is recorded on the entry, so `report` shows which tasks ran light |
| `resolve ID [--note "..."]` | Closes an open item or note. Escalations and questions need `user ruling: ...`, and so does a reviewer finding or a coder's open behavior choice, which only you settle (waived, ruled or accepted). A disclosure's note says where it landed |
| `snapshot --task N\|final --label "..."` | Records the working tree as a fix baseline and prints its tree id. Take it after a triage entry and before the fix, since `check` holds the finished fix to that round |
| `close-round --expect 1\|2 --note "..."` | Starts the next close-gate round. Refuses past two rounds, on a store that disagrees with `--expect`, and while any disclosure or question is open or a task-note waits on a task that never completed |
| `check <record-path>` | Validates a record an agent just wrote and appends its summary to the check history. It enforces each role's contract, including a finding's severity, reach, rule and sites, a re-check's answer to every forwarded contest, and, on a finished fix, the sweep rows, tests first, decision rows and test changes the round required |
| `clear [--discard-open]` | Deletes the run's records, handoff files and logs. Refuses while follow-ups, disclosures or questions are open, unless the user confirmed the loss |

## Reading the working tree

| Command | What it does |
|---|---|
| `diff-since <tree> [<path>...]` | The diff since a snapshot tree, new files included, limited to the task's files |
| `labels <tree> [<path>...]` | Lists review-process labels (task and finding ids, cycle numbers, commit hashes) on lines added since the tree; exits 1 if any |

`task_brief.py`, beside it, builds each task's brief from the plan, embeds the task's notes from the store, and logs their delivery. It refuses a task whose `Verify:` line has no backticked command, whose `Cases:` still carries an `open:` row, or whose `Cases:` has a row that doesn't separate its situation from its expected result with `→` or `->`. A row may group cases (`size=0, size<0 → ValueError`), and `n/a — <reason>` and the refactor form (`preserves <behavior>; covered by <tests>`) are exempt.
