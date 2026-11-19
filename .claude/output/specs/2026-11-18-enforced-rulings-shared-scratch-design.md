# Enforced Inline Rulings, One Shared Break-Check Copy and Typed Unverified Items Design Spec

Intent ledger: `.claude/output/intent/2026-11-18-enforced-rulings-shared-scratch-intent.md`.

## 1. Scope

Three parts of subagent-driven-development ask for a behavior in prose that nothing enforces, and run data shows the prose losing every time: the inline-fix offer was never put to the user, orchestrators forbade `ledger.py scratch` because one build cache per task and reviewer is unaffordable on a large compiled project, and `claim-checker` was never dispatched because most `cannot_verify` items are not claims a read can settle. This spec moves each behavior into the ledger: an offered round waits for the user's logged answer, a run has one leased and resource-capped break-check copy, and each `cannot_verify` item names what settles it and is settled only that way. Three `ledger.py` defects found in the same data are fixed alongside.

## 2. Goals

- An inline-eligible fix round does not move until the user's answer for that round is logged, and the answer decides who fixes it (intent 1).
- A run's break checks use one source copy and one build cache, whatever its task and reviewer count (intent 2).
- Only one reviewer at a time runs commands in the copy; another waits or learns who holds it (intent 3).
- A restored break is always rebuilt before the next test run (intent 4).
- A break-check command past its time or memory limit is stopped and reported as stopped (intent 5).
- Every `cannot_verify` item is settled by a recorded command result, a filed note, or `claim-checker`'s verified quotation; never by the orchestrator's own note (intent 6).
- `commit` commits both sides of a rename; a gate command naming a missing program fails; an `n/a` tests-first entry without a test is valid (intent 7).

## 3. Non-goals

- No change to which rounds triage marks inline-eligible, to the fix tiers, the two-round cap, or what an inline fix must do once the user chooses it.
- No standing or per-run answer to the inline offer: each offered round is asked.
- No change to what a break check samples, how a break is judged caught, or the rigor budgets.
- The close's mutation gate keeps its own isolated worktree and is not capped by this spec; it has no run data to design from.
- No project-configured build folders: the copy and cache locations are the ledger's.
- No migration of a `cannot_verify` item written before this release (§7).
- No change to `duplication_pending`, open behavior choices, escalations or finding rulings.

## 4. System behavior

### 4.1 The inline offer

**Offered.** A round is *offered* when its triage step is marked inline and its fix has not finished. An offered round has one of three answer states: unanswered, `coder`, or `orchestrator`.

**Unanswered.** Triage prints the offer as the first line of its output, with the round's findings and the command that logs the answer, and lists "the user's answer on who fixes" as what the round waits on. `baseline` refuses the round and `check` refuses a coder's fix record for it. The task is parked, and `run-state` lists it as parked on the offer: it joins the stage's batched question with its findings listed and a recommended answer, and the rest of the stage keeps going. At `final` and the close, which have no stage, the orchestrator asks at once.

**Answered `coder`.** The round proceeds exactly as a round that was never offered.

**Answered `orchestrator`.** `baseline` serves the round to the orchestrator, `check` refuses a coder's fix record for it, and the orchestrator's finished fix is logged with the closing call (§6.1), which is refused under any other answer state.

**Changing the answer.** A later answer replaces an earlier one while the round's fix is unfinished; after that it is refused.

**Ruled off.** A round the user rules off (every sent finding filed or dropped) ends as it does today and needs no answer.

**Reprints.** Running triage again on an unanswered round reprints the offer and starts no new round.

### 4.2 The break-check copy

**One per run.** A store has one scratch copy and one build cache, at fixed paths in the user-private temp folder. They live until the store is cleared or the branch is finished; a task's commit deletes neither.

**Lease.** A reviewer takes the copy for one task before touching it. Taking refreshes the copy to the working tree as it is now and records the holder. While held, another reviewer's take waits a bounded time inside the call, then reports busy with the holder's agent, task and idle time; the reviewer calls again and never builds anywhere else. The holder releases the copy when its break check ends. The same holder may take again (a re-check), which refreshes. A lease with no command running and none for 20 minutes is idle and may be taken over. A task's commit releases a lease still held for that task.

**Refresh.** The copy is brought to the current tree through git inside the copy: every edit left in it is discarded, only files that differ are rewritten, and each rewritten file gets a new modification time. Restoring a break with git inside the copy does the same. Git-ignored files in the copy (build outputs a reviewer copied in) survive a refresh.

**Guarded commands.** Every command that builds or runs code in the copy goes through `scratch run`, which requires the caller's lease, runs in the copy with the shared cache set for the build tool, and enforces the run's time and memory limits over the command's whole process group. On a breach it kills the group and exits 124 (time) or 125 (memory) with a line naming the limit. Otherwise it passes the command's output and exit status through. The take prints the `scratch run` form and no cache variable, so the guarded path is the only documented one.

**Limits.** Defaults: 900 seconds; 12 GB or half of physical memory, whichever is less. The orchestrator may set the run's limits once per run or change them later with a logged command; a reviewer cannot pass limits to `scratch run`.

**A stopped break.** A break whose command the guard stopped is neither caught nor a surviving test. The reviewer reports it as stopped, with the limit, never reruns it, and raises no finding from it.

### 4.3 Typed `cannot_verify` items

A spec reviewer's item states what would settle it (§6.3). A requirement nothing can check (a claim about how the work was done that the tree cannot show) is not an item; the reviewer says it in its report.

| `needs` | Meaning | Settled by |
|---|---|---|
| `run`, command `gate` | "The task's Verify command passes on the final tree", which the reviewer was told not to run | The scope's commit: it never blocks `ready`, and is settled when the scope completes |
| `run`, a command | A command the gate does not run must pass | `resolve --run` executes it and records the exit status, output tail and tree; settled on exit 0 |
| `elsewhere` | Text or code outside the scope's files that the change made untrue | Triage files it: a task-note when an unfinished task's footprint holds a site, a follow-up otherwise; settled by the filing |
| `read` | One factual claim about named lines | A checked `claim-checker` record whose verdict is `holds` |

**A failed run.** `resolve --run` on a non-zero exit records nothing and prints the output. The orchestrator sends it to the spec reviewer, who raises a tagged finding in place of the item.

**A stale run.** A run resolution holds for the tree it ran on. When the scope's files change afterwards, the item is open again.

**`does-not-hold`.** `resolve` refuses. The claim record's evidence goes to the spec reviewer, who raises a tagged finding in place of the item.

**`not-decidable-by-reading`.** Only the user settles it.

**The user's ruling.** `resolve --note "user ruling: ..."` settles any item of any kind, as it settles every other user decision. No other note settles a typed item.

**`open`** prints each item with its kind and the one action that settles it.

### 4.4 Defects

- **Rename.** When a scope's footprint holds both paths of a rename, `commit` stages and commits the deletion with the addition, and the scope completes.
- **Missing program.** A gate command (test or lint) that names a program the gate's shell cannot find fails the gate and names the program, whatever exit status the command as a whole returns. `resolve --run` applies the same rule.
- **`n/a` entry.** A tests-first entry marked `n/a` needs no `test` field. An entry with neither is refused with a validation message.

## 5. Architecture

- **The progress log** stays the one place state lives. It gains the inline answer, the run's scratch limits, and the run resolution's exit status and tree. Offered, answered, parked and stale are all derived from the log and the records, never stored as flags.
- **Triage** decides offers as today and adds the unanswered offer to what a round waits on. It files `elsewhere` items with the deferrals it already files.
- **`ready`, `baseline` and `check`** are the choke points that refuse. No new command is needed for a refusal.
- **Scratch** owns the copy, the cache, the lease and the guard. The lease is a small file beside the copy, since reviewers are separate processes with no shared lock; the guard is a supervisor process around the reviewer's command.
- **`claim-checker`** becomes a record-writing agent like every other; its record is validated by `check` against the file it quotes.
- **The gate's command runner** is shared by the commit gate and `resolve --run`, so the missing-program rule has one definition.

## 6. Canonical interfaces / data contracts

### 6.1 Inline

```
ledger.py inline --task N|final|close --by coder|orchestrator --note "user ruling: <their words>"
ledger.py inline --task N|final|close --done [--files F ...]
```

The first logs the answer; refused when the scope's latest round is not offered, or its fix has finished. The second logs the orchestrator's finished fix as today's `inline` does; refused unless the answer is `orchestrator`. The note that today's closing call requires moves to the answer.

Log entry: `{"type": "inline_ruling", "task", "baseline": <the round's tree>, "by", "note", "at"}`. A round's answer is its latest such entry for its baseline.

### 6.2 Scratch

```
ledger.py scratch take    --task N --agent NAME [--wait SECONDS]
ledger.py scratch run     --task N --agent NAME -- COMMAND ...
ledger.py scratch release --task N --agent NAME
ledger.py scratch limits  [--time SECONDS] [--memory GB]
```

- `take`: exit 0 and the copy's path on success; exit 3 and the holder (agent, task, idle seconds) when still held after the wait. Default wait 480 seconds.
- `run`: exit status of the command; 124 on the time limit, 125 on the memory limit; refused (exit 2) without the caller's lease.
- `release`: idempotent.
- `limits`: with no flag prints the run's limits; with a flag logs `{"type": "scratch_limits", "time", "memory", "at"}`.
- Lease: `{"agent", "task", "taken_at", "last_used_at", "running_pid"}`. Idle means no live `running_pid` and `last_used_at` older than 20 minutes.
- Memory is the summed resident size of the command's process group, sampled at least once a second.

### 6.3 `cannot_verify` entry (spec reviewer record)

```json
{"requirement": "...", "why": "...", "needs": "run", "command": "gate"}
{"requirement": "...", "why": "...", "needs": "run", "command": "cargo doc -p x --no-deps"}
{"requirement": "...", "why": "...", "needs": "elsewhere", "sites": ["docs/a.md:27"]}
{"requirement": "...", "why": "...", "needs": "read", "claim": "...", "path": "src/a.rs", "lines": "40-72"}
```

`check` refuses an entry with no `needs`, an unknown `needs`, or without the fields its kind requires. `should_check` is gone.

### 6.4 Claim record

Path: `ledger.py path --task N --agent claim-checker --item <item id>`.

```json
{"agent": "claim-checker", "task": 4, "item": "<item id>",
 "verdict": "holds | does-not-hold | not-decidable-by-reading",
 "evidence": [{"path": "src/a.rs", "line": 51, "text": "<the line, verbatim>"}],
 "because": "one sentence"}
```

`check` requires: `item` is an open `read` item; `holds` and `does-not-hold` carry 3 to 10 evidence lines; every evidence line equals that line of that file in the working tree, ignoring trailing whitespace; `because` is non-empty. The dispatch gives the agent the claim, the path and lines, the item id and the record path, and nothing of the reviewer's reasoning.

### 6.5 Resolve

```
ledger.py resolve <item id> --run
ledger.py resolve <item id>                      # a read item with a checked `holds` record
ledger.py resolve <item id> --note "user ruling: ..."
```

A run resolution's log entry adds `{"exit": 0, "tree": <snapshot>, "tail": <last lines>}`.

## 7. Invariants and constraints

- The checkout's working tree, index, HEAD and branch are never touched by any scratch operation.
- At most one scratch copy and one build cache exist per store.
- No command runs in the copy without the caller's live lease.
- A guard breach leaves no process of the command's group alive.
- An offered round has no path to finishing that skips a logged answer or a user ruling that ends the round.
- A typed item is never settled by an orchestrator note that lacks the `user ruling:` prefix.
- A quoted evidence line that is not in the file is never accepted.
- A `cannot_verify` entry without `needs`, in a record written before this release, keeps today's handling (resolved by note) until its record is rewritten; a record checked after this release must be typed.
- An inline-marked round whose fix had already finished before this release needs no answer; one still in flight waits for one.
- A store's per-task scratch folders from before this release are deleted by `clear`.
- POSIX only, as the ledger already is.

## 8. Key decisions and tradeoffs

- **Ask every round, enforced** (user's choice) over one pre-flight answer or always-inline. Cost: an unattended run stops at each offered round in a serial stage. Parking and the stage batch keep parallel tasks moving and fit how every other user decision is asked.
- **The answer is logged before the fix,** not with it. The old closing call recorded the ruling after the work, so nothing could refuse a round that skipped the question.
- **One copy and cache per run** (user's choice) over one per language or project-named folders. A fixed copy path keeps the build tool's cache valid across tasks, so disk use is one build. Cost: reviewers queue.
- **A lease with idle expiry,** not a process lock: reviewers are separate short-lived commands, and a reviewer that dies must not hold the copy forever. Expiry looks at a live command, so a long build is never taken over.
- **Take waits inside the call** rather than returning at once, so a reviewer needs no sleep loop; the wait stays under a tool call's limit.
- **Refresh through git** rather than a file sync. Git rewrites only what differs and stamps it now, which is exactly what the build tool's freshness check needs; a time-preserving sync is what produced stale binaries.
- **Limits are the run's, set by the orchestrator,** not flags on `run`. A cold build can legitimately need more than the default, but the party that raises a limit must not be the agent it constrains.
- **A stopped break is undecided,** not a surviving test. A break that hangs or exhausts memory says nothing about the test.
- **Type the items and route by type** (user's choice) over retiring `claim-checker`. About half of real items only needed the gate, a third were out-of-scope text, and a few were readable claims; one untyped list forced the orchestrator to judge all of them.
- **`gate` items need no action.** The commit cannot happen without the gate passing on the final tree, so a blocker there is ceremony.
- **The claim record is checked against the file.** The agent runs on the smallest model; verbatim quotation is what makes its answer trustworthy without a second reader.
- **The user's ruling settles anything.** It is the existing escape for every gate in the loop and stays the only one.
- **Missing-program detection sits in the shared command runner,** covering a negated or piped check whose exit status hides the failure.

## 9. Acceptance criteria

Inline:
- With an unanswered offered round: triage's first line is the offer; `baseline` and a coder fix record's `check` are refused; `ready` blocks; `run-state` lists the task as parked on the offer.
- After `--by coder`: `baseline` and the coder's `check` succeed, and `inline --done` is refused.
- After `--by orchestrator`: `inline --done` finishes the round, and a coder fix record for it is refused.
- A second answer before the fix finishes replaces the first; after, it is refused.
- `inline --by` on a round triage did not mark is refused. A ruled-off offered round ends with no answer.
- The same holds at `final` and the close.

Scratch:
- Two takes for different tasks give the same copy path and cache; the second, made while the first is held, exits 3 naming the holder.
- A take after the checkout changed holds the new tree, without a break a previous holder left; a file restored or refreshed has a newer modification time than before.
- `run` without the lease is refused. A command that sleeps past the time limit exits 124, one that allocates past the memory limit exits 125, and in both cases no process it started survives, including a grandchild.
- A lease idle past 20 minutes is taken over; one with a live command is not, however old.
- `limits` changes apply to the next `run`; `run` accepts no limit flag.
- A task's commit keeps the copy and cache and releases that task's lease; `clear` deletes all three.
- The checkout's status is unchanged after any sequence of scratch operations.

`cannot_verify`:
- `check` refuses an untyped or under-specified entry in a new record.
- A `gate` item never appears among `ready`'s blockers and is not open once its scope completes.
- `resolve --run` on a passing command settles the item and records exit, tail and tree; on a failing command it settles nothing; after a file of the scope changes, the item is open again.
- Triage files an `elsewhere` item as a task-note when an unfinished task's footprint holds a site and as a follow-up otherwise, and the item is then settled.
- A claim record with an evidence line that differs from the file is refused by `check`. `resolve` settles a `read` item only with a checked `holds` record, refuses on `does-not-hold`, and for `not-decidable-by-reading` accepts only a user ruling.
- `resolve --note` without the user-ruling prefix is refused for every typed item and still works for an untyped item from an older record.

Defects:
- A footprint with a renamed file commits with the old path deleted, and the scope completes.
- A gate command of the form "not (missing-program ...)" fails the gate and names the program; the same command with the program present passes.
- A tests-first `n/a` entry without `test` passes `check`; an entry with neither `test` nor `n/a` is refused with a message, not an exception.

Prose:
- The skill, the quality reviewers, the spec reviewer, `claim-checker` and the reference docs describe these contracts and no longer describe a per-task build cache, a `CARGO_TARGET_DIR` line, `should_check`, an inline claim-checker answer, or an orchestrator resolving a typed item by note.

## 10. Validation strategy

- Ledger behavior is validated by unit tests over throwaway git repositories and stores, as the existing suite does: each acceptance bullet above is a case, refusals asserted by their message.
- The guard is validated against real child processes: a sleeper, a memory grower and a process that spawns a grandchild, each under small limits.
- The lease is validated with two holders in one test process and a simulated dead holder (a lease whose recorded process is gone).
- Freshness is validated by modification times across take, break and restore, not by running a build tool.
- The agent and skill prose is validated by the existing contract tests that tie agent text to ledger enums and commands, extended to the new record fields and command forms.
- The intent ledger's seven statements are judged at the close by the spec-blind intent check against the shipped ledger and prose.
