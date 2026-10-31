# Ledger commands

`ledger.py` is the typed record store behind `subagent-driven-development`, `executing-plans` and `verification-before-completion`. It lives in the SDD skill's `scripts/` directory and is always called through `$SDD_SCRIPTS`, the skill's absolute scripts path. Every command except `diff-since` and `labels` takes `--store DIR`; the default store is `.sdd/` at the repo toplevel.

Commands that write the store hold an exclusive lock on its `.lock` file while they read, check and write, so parallel agents never interleave lines or both pass a check only one of them should. The store doesn't exist until its first write (normally `store-dir`), and only that write runs unlocked. A refusal writes nothing, not even the store.

## Reading the run

| Command | What it prints |
|---|---|
| `run-state` | Where the run stands: the stage map with each task's state, non-trivial fix counts for tasks in flight, notes owed, open disclosures and questions, the count of blocking items, agent handles, and the latest checkpoint |
| `read` | The whole store as markdown: every record, then every progress-log entry |
| `open` | What blocks: open record items (`cannot_verify`, `duplication_pending`, escalations, open statuses, malformed records), notes tasks in flight haven't received, and open disclosures and questions |
| `completed` | Task ids with a completion entry, one per line |
| `shapes` | Shared symbols the coders declared, as every brief carries them |
| `stats` | Each task's verdicts cycle by cycle from the check history, every fix's route, and the records that flagged `introduced_by_fix` or `recurring` |
| `report` | What the completion report lists: user rulings, follow-ups (filed ones and the coders' `unlisted case:` concerns), dispositions and waivers, disclosures with where each landed, and questions with their rulings |
| `notes --task N` | The notes task N must receive, marked delivered or not, and the questions it owns |
| `fix-count --task N` | How many non-trivial fixes the task has had |
| `findings <decision-path>` | The finding ids a decision record at that path must account for, and the decisions it must reconcile with |
| `baseline <tree> --task N` | How a fix baseline was routed: a decision record, `settled-by`, trivial, or `unrecorded` (a non-trivial snapshot from before routes were logged) |
| `store-dir` | The resolved store path, creating it and its self-ignoring `.gitignore` if needed |

## Writing the run

| Command | What it does |
|---|---|
| `note --kind KIND --text "..." [--for N] [--owner N\|close] [--from N\|final\|run]` | Files an orchestrator note and prints its id. Kinds: `task-note` (`--for` a task), `run-note`, `disclosure` and `question` (`--owner` a task or `close`), `follow-up`, `disposition`, `checkpoint` |
| `notes --task N --deliver` | Records that the session (not a brief) delivered every note the task requires |
| `notes --task N --waive ID --reason "..."` | Records that a required note doesn't apply to the task, with why |
| `stage --task N --stage K --files PATH...` | Records a task's stage and file footprint; refuses a path another unfinished task in the same stage claims |
| `handle --task N\|final --role NAME --agent ID` | Records the agent id behind a task's role, so it can be continued after a compaction |
| `append --type progress\|complete --task N\|final\|run --note "..."` | A progress note or a task's completion. `--task run` is for rulings about the whole run. `complete` refuses while the task has an open escalation, an undelivered note, or an open disclosure or question it owns |
| `resolve ID [--note "..."]` | Closes an open item or note. Escalations and questions need `user ruling: ...`; a disclosure's note says where it landed |
| `snapshot --task N\|final --label "..." [--non-trivial (--decision RECORD \| --settled-by cases\|ruling)]` | Records the working tree as a fix baseline and prints its tree id. While a reviewer record of the task flags `recurring` or `introduced_by_fix`, refuses a trivial snapshot or one `--settled-by cases` |
| `close-round --expect 1\|2 --note "..."` | Starts the next close-gate round. Refuses past two rounds, on a store that disagrees with `--expect`, and while any disclosure or question is open or a task-note waits on a task that never completed |
| `check <record-path>` | Validates a record an agent just wrote and appends its summary to the check history. A finished fix must name its own `baseline`: one with a snapshot for the task that no earlier cycle of the record used |
| `clear [--discard-open]` | Deletes the run's records, handoff files and logs. Refuses while follow-ups, disclosures or questions are open, unless the user confirmed the loss |

## Reading the working tree

| Command | What it does |
|---|---|
| `diff-since <tree> [<path>...]` | The diff since a snapshot tree, new files included, limited to the task's files |
| `labels <tree> [<path>...]` | Lists review-process labels (task and finding ids, cycle numbers, commit hashes) on lines added since the tree; exits 1 if any |

`task_brief.py`, beside it, builds each task's brief from the plan, embeds the task's notes from the store, and logs their delivery.
