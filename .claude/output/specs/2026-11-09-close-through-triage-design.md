# The Close Through Triage Design Spec

## 1. Scope

The completion close (`verification-before-completion`: design reviewers, intent reviewer, the optional mutation gate) runs through the same ledger machinery as the per-task loop, and both loops keep every finding as its own run of entries in the progress log. The close gates write typed records; `ledger.py triage` turns every reviewer and gate record into finding state changes and decides each step; blocking findings are fixed in place; the user rules on the rest with one command. The close's own requirements check (Step 4) is replaced by a plan coverage check before the build. Close-scoped user rulings stop being filed as run-notes, and a coder's skipped store note is no longer filed as a follow-up. Intent: `.claude/output/intent/2026-11-09-close-through-triage-intent.md`.

## 2. Goals

- An intent `not-met` or an S4+ finding from any close gate blocks finishing; every other close finding waits for the user's ruling, and the close finishes only when nothing blocks or waits (intent 1).
- Close findings are routed by `triage` from typed records, never sorted by the orchestrator (intent 2).
- A blocking finding is fixed in place from a triage-taken baseline and re-checked only by the gate that raised it, scoped to the fix; no remediation plan or second SDD run (intent 3).
- At most two fix rounds, then the user rules each open finding fix, file or drop (intent 4).
- A finding's state lives in the log, one entry per change, in tasks and at the close: no record rewrite can erase or reset it.
- An agent confirms spec coverage of the plan before any coder runs, and a brief can't be built from a spec-citing plan that skipped it (intent 5).
- A close ruling never reaches a coder or holds a task, and a coder's skipped store note is never filed (intent 6).
- `run-state` shows the close's rounds, rulings and what still waits for a decision after a compaction (intent 7).

## 3. Non-goals

- No change to the per-task loop's tiers, its two-round cap, its notes, holistic rounds, contests, `check` rules for a fix, or the whole-change gate at `final`; only where a finding's state is kept and how the user rules on it.
- No change to what each gate judges (design rubric, spec-blind intent judgment, mutation workflow and rigor budgets), only to how its result is recorded and routed.
- No migration of a close already in progress: it restarts as a new close (§7). A task store from 0.15 is seeded once (§4).
- `cannot_verify`, open behavior choices and `root cause:` concerns keep their current handling.
- The completion report and the close batch's fix / file / ignore choice stay for the run's other follow-ups; close findings are decided inside the close.

## 4. System behavior

**Starting the close.** After tests, lints and the whole-change gate, `ledger.py close-round --note "<work being closed>"` starts a close: it records the HEAD under review and refuses while the close owns an open question, disclosure or unrun task-note, or when the store already holds a close this release started: an unfinished one resumes at triage, and a finished one is final, so a new close needs a cleared store (a legacy entry, which carries a `round` field, never blocks). The mutation-gate question is asked before the dispatch and its answer is logged on `--task close`.

**Dispatch.** Every applicable gate goes out in one message: each matching `*-design-reviewer`, `intent-reviewer`, and `mutation-tester` when the user chose it. Each writes its prose report and a typed record (§6), and runs `ledger.py check` on the record. The orchestrator never fixes or sorts while a gate is out.

**Findings in the log.** Every reviewer and gate finding, in a task and at the close, is its own run of entries in the progress log, keyed by its content-derived id. Its current state is its latest entry; nothing overwrites it, so a re-check that no longer mentions a finding can't erase it. Reviewer and gate records are observations: triage turns what they raise, concede and hold into state changes. A finding's states:

| State | Meaning |
|---|---|
| `fix` | must be fixed; not yet sent to a coder |
| `sent` | in a fix round, awaiting its re-check; carries the round and the raising record's version at the send |
| `held` | its reviewer held the coder's contest; the user decides; carries the record's version at the hold |
| `waiting` | the user decides (a close finding below the blocking line, or any open finding once the fix rounds are spent) |
| `note` | a task's minor finding, for the coder to fix or skip alongside a round |
| `noted` | a note sent to a coder (final) |
| `filed` | a follow-up was filed for it |
| `fixed` | its reviewer re-checked without raising it, or conceded its contest (final) |
| `dropped` | the user dropped it |

**First sighting.** The first time triage sees an id, its state comes from the rule of its scope. In a task: S1–S2 local or class is `note`, S1–S2 contract is `filed` (triage files its follow-up), and S3+ is `fix` (routed patch, or holistic at contract reach or a reach the coder raised). At the close: an intent `not-met`, S4–S5 or a failing commit gate is `fix`; everything else is `waiting`. A `fixed` finding raised again unchanged is refused by `check`; the problem coming back is a new finding marked `reopens` (naming a `fixed`, `dropped` or `filed` finding, at a site changed since it settled), which starts at its first-sighting state. A `dropped` or `filed` finding raised again is accepted and stays as ruled.

**Observation.** Only a re-check changes a finding: its raising record written since the finding was sent or held. A record's version is its last write plus its content digest, so a re-check with the same content still counts. Then a `sent` finding is `fixed` when gone, `held` on a hold, `fixed` on a concede, and `fix` again when still raised; a concede also closes a `held` finding. Without a re-check nothing changes, so a stale concede or hold can't act on a finding sent again. Other states (`fix`, `waiting`, `note` and the final ones) are never changed by records.

**The round in flight.** A fix step's round lasts until its coder has finished, at `final` and the close until `commit` has landed its fix, and until each finding it sent has been re-checked (its raiser's record written again: a re-check, or a new gate run) along with every other record it named (`awaiting` on its entry: every reviewer after a holistic round, the spec reviewer after an override's ruling round). A round whose every sent finding (a polish round: its notes) the user has filed or dropped is the exit from a fix that can't land (a blocked coder, a gate it can't pass): it waits only for `ledger.py discard`, which puts the round's unlanded changes back to its baseline and removes the gate record that judged them. Keeping the work is another attempt, not an ended round. Until then triage reprints the step with what it is waiting for and starts nothing, so no step can pass a finding that was never re-checked. `ready` also refuses while any finding is `sent`.

**Rulings.** The user's decisions on findings go through one command, `ledger.py rule <id>... --as fix|file|drop --note "user ruling: ..."`, in both scopes. `fix` makes the finding `fix`; `file` files its follow-up (carrying its id, raising record, report path and rule) and makes it `filed`; `drop` makes it `dropped`. A later ruling replaces an earlier one: ruling `fix` or `drop` on a `filed` finding resolves its follow-up. A finding already `fixed`, or in a completed task or a finished close, can't be ruled. `resolve` refuses a finding id and names `rule`. Open behavior choices and `root cause:` concerns aren't findings: they keep `resolve`, and an override of an open choice stays a progress note.

**The step.** Triage derives the step from the states, the scope's earlier entries, the coder's root causes and (at the close) the can't-tell statements:

1. At the close, an open can't-tell is `clarify` (re-check `intent`, no round, no snapshot), before anything else. A finished close stays `done`.
2. A finding the user ruled `fix` (its latest entry is the user's) starts a `ruling` round right after an `escalate` (task) or `decide` (close), or once the rounds are spent; past the cap the round sends only the ruled findings, and other `fix` findings become `waiting`. Before the cap, a ruled finding simply joins the next round. In a task, an override of an open choice after `done` starts a ruling round re-checked by the spec reviewer, as today.
3. Open `fix` findings or root causes start a `patch` or `holistic` round, sending them (and, in a task, the pending notes). After two such rounds, or after a ruling round, they become `waiting` instead, and the step is `escalate` in a task or `decide` at the close.
4. Otherwise, `held` or `waiting` findings make the step `escalate` (task) or `decide` (close): the user rules each with `rule`.
5. Otherwise, in a task, pending notes or an undelivered note is `polish`.
6. Otherwise `done`.

The entry records the step, the sent findings with their tiers (what `check` holds the fix to), the held, waiting and settled ids (`fixed`, `dropped`, `filed`), and the coder deferrals it filed. Coder deferrals (skipped notes, sites outside the fix, excluded root causes) are filed as follow-ups when triage first sees them, in both scopes.

**Stores from 0.15.** A scope with triage entries but no finding entries gets its finding states seeded from its latest entries (settled ids `fixed`, waived ids `dropped`, held `held`, filed `filed`, the last round's sent findings `sent`). The first write to the scope, a `rule` or a triage, persists the seed under the store lock before its own entry, then the scope continues under these rules.

**Fixing at the close.** A fix round's coder writes `close-<coder>.json` (its first close fix is cycle 2, like the first fix at `final`), works from the baseline triage printed, and its fix is committed with `ledger.py commit --task close`, which commits a finished fix without completing anything. That commit adds the coder's changed files to the scope's footprint in the log, so a file an earlier attempt changed is still gated and committed, and logs the fix as landed. A labels, lint or test failure there goes back to the coder as the same attempt; a fix that changed nothing (every finding contested) lands without a commit once the gate passes on HEAD. The same holds at `final`. Re-check is `raising`: only the gates whose findings were sent re-check, given the round's `Fix baseline` and the settled ids, and they judge the fix diff and its consumers. The close is finished at its `done` entry.

**Plan coverage check.** As lean-plan's last step, when the plan cites a spec, the `spec-reviewer` runs in plan coverage mode with only the spec and the plan. Its report lists each spec requirement no task covers and each task doing work the spec doesn't ask for, with a verdict `PASS` or `GAPS`. The planner closes each gap (add or extend a task, or the user cuts it from the spec) and re-dispatches once; anything left goes to the user. The plan then carries a `Spec coverage:` line (§6). `task_brief.py --spec <spec>` refuses a plan without a valid line for that spec. A plan with no spec skips the check.

**Close rulings and skipped notes.** A ruling about the close is a progress note on `--task close` or a `rule` command, never a run-note; run-notes remain only for rules coders must act on. When a coder lists a store note (an id starting `note#`) in `notes_skipped`, triage never files it as a follow-up.

**`run-state`.** Its verdicts become `fresh`, `resume`, `closing`, `finished`, `foreign`, `ambiguous`. `closing`: every task complete and a close started but not `done`; its next action names the close's latest step. `finished`: the latest close reached `done`. The run's rounds section lists the close like a task, with its rulings and the findings still waiting. Parked items and `ready` read held and waiting findings from the log.

## 5. Architecture

- **`triage.py`** holds the finding rules as pure functions: first-sighting states per scope, the observation of records into state changes, and the step from the states. It reads no files and never imports ledger.
- **`ledger.py`** stores finding entries, derives each finding's current state from them, seeds legacy scopes, runs observation and the step in `triage`, files deferrals and `file` rulings, and adds the `rule` command. It validates the three close record roles and adds `close` as a scope everywhere a scope is named. `check`, `ready`, `run-state`, `baseline` and the decision checks read finding state and the round's entry instead of earlier entries' carried sets.
- **`store_state.py`** classifies the store with the new verdict set and drops the remediation verdict.
- **`task_brief.py`** enforces the `Spec coverage:` line when given `--spec`.
- **Agents.** The three close gates write a typed record next to their report. `spec-reviewer` gains plan coverage mode, which writes a report only.
- **Skills.** `verification-before-completion`'s close follows §4; Step 4 is removed. SDD's stage batch rules findings with `rule`. `lean-plan` gains the coverage step. `remediating-issues` loses its close-gate variant. Docs, README, guide and decks follow.

## 6. Canonical interfaces / data contracts

**Close records.** Envelope as today (`schema: 2`, `agent`, `role`, `task: "close"`), at `close-<agent>.json` from `ledger.py path --task close --agent <agent>`; reports at `--kind report`.

| role | status values | finding list | extra fields |
|---|---|---|---|
| `design-reviewer` | `pass`, `concerns` | `findings` | |
| `intent-reviewer` | `pass`, `concerns` | `findings` (one per not-met) | `statements` |
| `mutation-tester` | `pass`, `concerns`, `skipped`, `inconclusive` | `findings` (one per gating survivor) | |

Every finding carries the schema-2 tags (`severity` 1–5, `reach` local / class / contract, `rule`, `sites`) and gets a content-derived id like any reviewer finding. A mutation survivor is severity 3, reach local, sited at the mutated line.

```
statements: [{"statement": int,          # 1-based index in the intent ledger
              "verdict": "met" | "not-met" | "can't-tell",
              "evidence": str,
              "needs": str}]             # required for can't-tell: the access or observation it needs
```

`check` refuses: a `not-met` statement with no finding citing it (`"statement": n` on the finding); a finding citing a statement that isn't `not-met`; a `can't-tell` without `needs`; `pass` with any not-met; status values outside the table.

**Finding entry.**

```
{"type": "finding", "task": <N | "final" | "close">, "id": <finding id>,
 "state": "fix" | "sent" | "held" | "waiting" | "note" | "noted" | "filed" | "fixed" | "dropped",
 "by": "triage" | "user",
 "data": {source, severity, reach, rule, sites, claim, not_met, gate},  # on the id's first entry
 "round": int,                                                        # on a sent entry
 "seen": <raising record version>,                                    # on a sent or held entry
 "tree": <work tree>,                                                 # where it settled (fixed, dropped, filed)
 "note": "user ruling: ...",                                        # on a user entry
 "at": <timestamp>}
```

**`rule` command.** `ledger.py rule <id>... --as fix|file|drop --note "user ruling: ..." [--store DIR]`: refuses an id with no finding entry, a note not starting `user ruling:`, a `fixed` finding, and a finding of a completed task or a finished close.

**Triage entry.** As before (`kind`, `round`, `recheck`, `findings` sent with tiers, `held`, `settled`, `filed`, `recheck_records`, `inputs`, telemetry), plus `waiting` and, on a fix step, `awaiting` (`{record stem: version at the step}` for re-checks beyond the sent findings' raisers). A landed final or close fix appends `{"type": "fix_commit", "task", "commit"}`. New kinds: `clarify` (close: re-check `intent`, no snapshot, no round) and `decide` (close: no re-check, no snapshot, no round).

**Paths.** `PATH_SCOPES` becomes `final`, `close`. `--task gate` and `--task ruling` fail with a message naming `--task close`. Records and decisions at the close: `close-<agent>`, `close-decision-c<N>`. `final-r2` naming is removed.

**`close-round`.** `close-round --note TEXT` (no `--expect`) appends `{"type": "close_round", "head", "note"}` and prints the head. A legacy `--expect` fails with a message pointing at the new usage.

**`Spec coverage:` line.** One line in the plan's header:

```
Spec coverage: <spec path> — pass (<report path>)
Spec coverage: <spec path> — user ruling: <verbatim> (<report path>)
```

`task_brief.py --spec S` requires a line whose spec path resolves to `S` and whose report file exists.

## 7. Invariants and constraints

- Every finding has exactly one current state, its latest finding entry; no record rewrite changes a state except through the observation rules in §4.
- No step is taken while a fix round is in flight (§4), so no scope reaches `done` with a `sent` finding.
- The orchestrator writes no finding and assigns no state; triage and the user's `rule` command do.
- A finding is filed at most once at a time: a `file` ruling or a task's S1–S2 contract tier files it, and a later ruling resolves that follow-up.
- The per-task loop's routing (tiers, two-round cap, notes, contests, holistic rounds) and `check`'s rules for a fix behave as in 0.15.0; tests that drove the loop through its records keep passing, with waivers moved from `resolve` to `rule`.
- A close fix commits only the coder's footprint and never completes a scope.
- A store whose close began under an earlier release is not converted: `close-round` starts a new close after its entries, and the old entries are ignored by close triage.
- Snapshots, baselines and fix cycles follow the 0.15.0 rules (`fix_cycle`, history-aware open fix, one reuse per snapshot).
- Prose follows the repo rules: no hard-wrapped markdown, no project names, task numbers or run histories in plugin text.

## 8. Key decisions and tradeoffs

- **What blocks at the close: intent + S4+.** Chosen over "every S3+" (which produced long remediation chains) and "intent only" (would ship a design-flagged correctness bug). Design S3 findings and mutation survivors wait for the user's ruling.
- **Findings in the log, one entry per change, for both loops,** over keeping state in records and triage entries: a record is rewritten every re-check, and every bug in the earlier designs (lost findings, forgotten holds, reopened waivers, double filing) was state reconstructed from overwritten records and carried sets. An append-only log gives each finding one history.
- **Records are observations.** Triage reads them and appends state changes; nothing else reads a finding's state from a record.
- **One ruling command for both loops,** over parsing free-text rulings or splitting waivers (`resolve`) from rulings (progress notes): structured, validated at write time, and the same in the stage batch and the close.
- **Spent rounds become `waiting`,** so escalation and the close's decision are one kind of question: the user rules the finding.
- **Fix in place at the close,** over a remediation plan per round: blocking items are few, the `final` fix path already exists, and per-round plans re-dispatched every gate.
- **Re-check by the raising gates only:** re-running every gate is what made a second close round expensive; the log keeps every unsent finding, so a narrow re-check loses nothing.
- **`close` is its own scope,** separate from `final`, so the whole-change gate's rounds and the close's rounds are counted apart.
- **Plan coverage before the build,** over a spec reviewer at the close or dropping the check: a missing requirement starts at planning, and the check reads two documents instead of a whole change. It reuses `spec-reviewer`.
- **Enforcement at `task_brief.py --spec`:** deterministic and already the SDD entry point; inline execution relies on lean-plan's step.
- **A record's version is its write, not its content,** so an identical re-check (the same finding still raised) still counts; a content digest alone would leave such a round waiting forever.
- **A failing gate at a final or close fix's commit is the coder's same attempt,** like labels and lint: the re-check can't run before the fix commits, so a new round there would only race the re-check.
- **Seed 0.15 task stores, don't convert a close:** an in-flight task keeps its waivers and holds; a close restarts cheaply.

## 9. Acceptance criteria

- A close with one design S3, one mutation survivor, one intent not-met and one design S4 produces a fix round sending exactly the not-met and the S4; the other two are `waiting`.
- A close with only S1–S3 findings goes straight to `decide`; `rule ... --as file` files each once with id, source and report path, and the next triage is `done`.
- A `waiting` or `held` finding a later re-check doesn't mention keeps its state.
- A sent finding whose gate re-checks without it is `fixed`; one still raised goes back to `fix`; a concede makes it `fixed`; a hold makes it `held`, and the hold survives later re-checks until the user rules.
- Two fix rounds that leave findings open turn them `waiting` (task `escalate`, close `decide`); `rule <id> --as fix` starts a ruling round sending only those; a failed ruling round turns them `waiting` again.
- A ruling of `file` or `drop` never starts a round; a later ruling replaces an earlier one, and ruling `fix` on a `filed` finding resolves its follow-up.
- In a task, waivers, held contests, notes and the S1–S2 contract deferral behave as in 0.15.0, with the waiver given by `rule --as drop`.
- A 0.15 task store with triage entries and no finding entries is seeded, and a waived finding stays waived, also when the user's first act on it is a `rule`.
- Triage run after a fix but before its commit (final, close) or its re-check reprints the round, logs nothing, and names what it waits for; with two gates owed, it waits for both. A stale hold never re-holds a finding the user ruled `fix`.
- A failing test at a close fix's commit leaves the round open; the coder's next attempt commits every file either attempt changed. A round whose findings the user files or drops (a blocked coder, a gate the coder can't pass) ends once `discard` restores the round's baseline, which keeps the work before the round.
- A user-ruled S1–S2 finding sent in a ruling round is re-checked by the reviewer that raised it, and the round waits for that re-check.
- A re-check may raise a finding the user dropped or filed (it stays as ruled); a `fix` ruling after a failed ruling round starts another ruling round; a waiting finding's claim reaches the coder after its record was rewritten.
- `check` refuses each malformed close record listed in §6; `rule` refuses each case listed in §6; `resolve` refuses a finding id.
- `task_brief.py --spec S` refuses a plan with no `Spec coverage:` line, one naming another spec, and one whose report is missing, and accepts a valid pass line and a valid user-ruling line.
- A coder's `notes_skipped` naming `note#run-note[...]` or `note#task-note[...]` files nothing; a skipped reviewer note is still filed.
- `run-state` reports `closing` mid-close with the close's latest step as the next action, `finished` after `done`, and lists the close's rounds and waiting findings.
- `path --task gate`, `path --task ruling` and `close-round --expect` fail with messages naming the replacement.
- The full suite passes; the verification skill no longer describes Step 4, round 2 as a re-dispatch of every gate, remediation plans per round, or the orchestrator's four-way sort.

## 10. Validation strategy

Unit tests on `triage.py` cover first sighting per scope, each observation rule, and each step kind, including spent rounds, rulings, and clarify. Store-level tests drive whole tasks and closes through `cmd_check`, `cmd_triage` and `cmd_rule` as coders, reviewers and the user would, so record validation, observation and routing are exercised together. `store_state` tests cover the new verdicts. `task_brief` tests cover the coverage line. Drift tests keep the typed-record sections shared across the two design reviewers identical, and the docs are checked against the acceptance list by reading.
