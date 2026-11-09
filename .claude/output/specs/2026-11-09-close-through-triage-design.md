# The Close Through Triage Design Spec

## 1. Scope

The completion close (`verification-before-completion`: design reviewers, intent reviewer, the optional mutation gate) runs through the same ledger machinery as the per-task loop. The close gates write typed records, `ledger.py triage --task close` decides each step, blocking findings are fixed in place, and every other finding waits for the user's ruling: fix, file or drop. The close's own requirements check (Step 4) is replaced by a plan coverage check before the build. Close-scoped user rulings stop being filed as run-notes, and a coder's skipped store note is no longer filed as a follow-up. Intent: `.claude/output/intent/2026-11-09-close-through-triage-intent.md`.

## 2. Goals

- An intent `not-met` or an S4+ finding from any close gate blocks finishing; every other close finding waits for the user's ruling, and the close finishes only when nothing blocks or waits (intent 1).
- Close findings are routed by `triage` from typed records, never sorted by the orchestrator (intent 2).
- A blocking finding is fixed in place from a triage-taken baseline and re-checked only by the gate that raised it, scoped to the fix; no remediation plan or second SDD run (intent 3).
- At most two close fix rounds, then escalation to the user, who rules each open finding fix, file or drop (intent 4).
- An agent confirms spec coverage of the plan before any coder runs, and a brief can't be built from a spec-citing plan that skipped it (intent 5).
- A close ruling never reaches a coder or holds a task, and a coder's skipped store note is never filed (intent 6).
- `run-state` shows the close's rounds, rulings and what still waits for a decision after a compaction (intent 7).

## 3. Non-goals

- No change to the per-task loop's routing, its two-round cap, or the whole-change gate at `final`.
- No change to what each gate judges (design rubric, spec-blind intent judgment, mutation workflow and rigor budgets), only to how its result is recorded and routed.
- No migration of a close already in progress: it restarts as a new close (§7).
- `cannot_verify` is unchanged (run data shows it is no longer a problem).
- The completion report and the close batch's fix / file / ignore choice stay for the run's other follow-ups; close findings are decided inside the close (§4).

## 4. System behavior

**Starting the close.** After tests, lints and the whole-change gate, `ledger.py close-round --note "<work being closed>"` starts a close: it records the HEAD under review and refuses while the close owns an open question, disclosure or unrun task-note (as today), or when the store already holds a close this release started: an unfinished one resumes at triage, and a finished one is final, so a new close needs a cleared store (a legacy entry, which carries a `round` field, never blocks). Two closes in one store would mix their records. The mutation-gate question is asked before the dispatch, as in 0.15.0, and its answer is logged on `--task close`.

**Dispatch.** Every applicable gate goes out in one message: each matching `*-design-reviewer`, `intent-reviewer`, and `mutation-tester` when the user chose it. Each writes its prose report and a typed record (§6), and runs `ledger.py check` on the record. The orchestrator never fixes or sorts while a gate is out.

**Triage at the close.** `ledger.py triage --task close` gives every close finding exactly one disposition, from the finding's own id and the user's latest ruling on it:

| The user's latest ruling on the finding | Disposition |
|---|---|
| none; an intent `not-met`, S4–S5, or a failing commit gate | fix (blocking) |
| none; anything else | waiting for the user |
| `fix` | fix (blocking) |
| `file` | file: a follow-up when the close finishes |
| `drop` | drop |

Blocking findings route as task findings do: local or class reach to a `patch` round, contract reach (or reach a coder raised) to a `holistic` round with one decision doc from the per-task `remediating-issues` variant. Nothing that isn't blocking is ever sent to a coder.

**Where a finding lives.** A finding a fix step has sent lives in its gate's record: the raising gate re-checks it, and a re-check that no longer raises it means it is fixed. A finding no fix step has sent is carried by triage itself, in each entry, from the first triage that saw it, so a re-check scoped to a fix diff never loses it.

**Rulings.** A ruling is a progress note on `--task close` starting `user ruling:` with a verb and finding ids: `user ruling: fix <id> <id>`, `user ruling: file <id>`, `user ruling: drop <id>`; free text may follow. A finding's latest ruling wins, so a ruling can always be changed. A ruling that names no finding id decides nothing, and the mutation-gate ruling starts no round. A ruling naming an id triage doesn't know is reported, never silently ignored.

**Can't-tell.** While any intent statement is `can't-tell`, triage prints a `clarify` step naming the intent reviewer and the access each statement needs; it starts no fix round and counts toward no cap. A statement the user settles (`resolve <id> --note "user ruling: ..."`) stops holding it. Clarify comes before any fix round, so a late `not-met` joins it, and it never stands in for the step before it.

**Fixing.** A fix round's coder writes `close-<coder>.json` (its first close fix is cycle 2, like the first fix at `final`), works from the baseline triage printed, and its fix is committed with `ledger.py commit --task close`, which commits a finished fix without completing anything (the `final` fix path's behavior). Re-check is `raising`: only the gates whose blocking findings were sent re-check, given the round's `Fix baseline` and the settled ids, and they judge the fix diff and its consumers. A new finding in a re-check gets its disposition like any other.

**Cap and decisions.** After two `patch`/`holistic` rounds with blocking work open, or after a ruling round that leaves it open, or when a gate holds a coder's contest, triage escalates. When nothing blocks but findings wait for the user, triage prints one `decide` step listing them, each for the orchestrator to put to the user with a recommendation. A `fix` ruling logged after an `escalate` or `decide` step starts a ruling round, re-checked by the raising gates; `file` and `drop` rulings just settle their findings.

**Done.** Triage prints `done` when nothing blocks, waits, is held or can't-tell. At that entry it files one follow-up per finding ruled `file` (carrying the finding's id, its raising record, its report path and its rule) and one per deferral the close coder recorded (sites outside its fix, root causes a decision excluded). Nothing is filed before `done`. The close is final: a later ruling starts nothing.

**Plan coverage check.** As lean-plan's last step, when the plan cites a spec, the `spec-reviewer` runs in plan coverage mode with only the spec and the plan. Its report lists each spec requirement no task covers and each task doing work the spec doesn't ask for, with a verdict `PASS` or `GAPS`. The planner closes each gap (add or extend a task, or the user cuts it from the spec) and re-dispatches once; anything left goes to the user. The plan then carries a `Spec coverage:` line (§6). `task_brief.py --spec <spec>` refuses a plan without a valid line for that spec. A plan with no spec skips the check.

**Close rulings and skipped notes.** A ruling about the close is a progress note on `--task close`, never a run-note; run-notes remain only for rules coders must act on. When a coder lists a store note (an id starting `note#`) in `notes_skipped`, triage never files it as a follow-up; skipped reviewer findings are filed as before.

**`run-state`.** Its verdicts become `fresh`, `resume`, `closing`, `finished`, `foreign`, `ambiguous`. `closing`: every task complete and a close started but not `done`; its next action names the close's latest step. `finished`: the latest close reached `done`. The run's rounds section lists the close like a task (its triage kinds in order), with its rulings and the findings still waiting for a decision.

## 5. Architecture

- **`triage.py`** gains the close rule set beside the task rule set: a pure function of the same shape that takes the close's findings (each with source role, severity, reach, and an intent verdict where present), can't-tell statements, the user's latest ruling per finding and prior entries, and returns the step, the findings it carries and, at `done`, what to file. The task rule set is untouched.
- **`ledger.py`** validates the three new record roles, adds `close` as a scope everywhere a scope is named (records, decisions, paths, triage, commit, progress, notes, `_scope_log`), reads the latest ruling per close finding, and files the `file`-ruled findings and the close coder's deferrals at `done`. Its close scope log is everything after the latest `close_round` entry.
- **`store_state.py`** classifies the store with the new verdict set and drops the remediation verdict.
- **`task_brief.py`** enforces the `Spec coverage:` line when given `--spec`.
- **Agents.** The three close gates write a typed record next to their report. `spec-reviewer` gains plan coverage mode, which writes a report only.
- **Skills.** `verification-before-completion`'s close is rewritten around the flow in §4; Step 4 is removed. SDD documents close rulings on `--task close` and the narrower run-note rule. `lean-plan` gains the coverage step. `remediating-issues` loses its close-gate variant. `finishing-a-development-branch`, docs, README, guide and decks follow.

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

**Triage entry at `close`.** Same shape as a task entry, plus `carried` (the findings no fix step has sent, each with its id, source, severity, reach, rule, sites and whether it is a not-met) and `waiting` (the ids waiting for a ruling). New kinds: `clarify` (recheck `intent-reviewer`, no snapshot, no round) and `decide` (no recheck, no snapshot, no round). Finding tiers in an entry: `patch`, `holistic`, `held`.

**Close follow-ups.** Filed only at `done`: a `file`-ruled finding's follow-up carries `finding` (its id), `source` (the raising record stem) and `report` (its report path) beside its text and rule; a close coder's deferral is a plain follow-up with its rule.

**Paths.** `PATH_SCOPES` becomes `final`, `close`. `--task gate` and `--task ruling` fail with a message naming `--task close`. Records and decisions at the close: `close-<agent>`, `close-decision-c<N>`. `final-r2` naming is removed.

**`close-round`.** `close-round --note TEXT` (no `--expect`) appends `{"type": "close_round", "head", "note"}` and prints the head. A legacy `--expect` fails with a message pointing at the new usage.

**`Spec coverage:` line.** One line in the plan's header:

```
Spec coverage: <spec path> — pass (<report path>)
Spec coverage: <spec path> — user ruling: <verbatim> (<report path>)
```

`task_brief.py --spec S` requires a line whose spec path resolves to `S` and whose report file exists.

## 7. Invariants and constraints

- The task rule set, the per-task loop and its stores behave exactly as in 0.15.0; existing per-task tests pass unchanged.
- The orchestrator writes no close finding and assigns no tier; every tier comes from triage.
- Every close finding has exactly one disposition at a time (fix, waiting, file, drop or held), derived from its id and the latest ruling, and the close ends with each fixed and re-checked, filed once at `done`, or dropped.
- Nothing is filed before `done`, so nothing is filed twice.
- A close fix commits only the coder's footprint and never completes a scope.
- A store whose close began under an earlier release is not converted: `close-round` starts a new close after its entries, and the old entries are ignored by close triage.
- Snapshots, baselines and fix cycles at `close` follow the 0.15.0 rules (`fix_cycle`, history-aware open fix, one reuse per snapshot).
- Prose follows the repo rules: no hard-wrapped markdown, no project names, task numbers or run histories in plugin text.

## 8. Key decisions and tradeoffs

- **What blocks: intent + S4+.** Chosen over "every S3+" (today, which produced long remediation chains) and "intent only" (would ship a design-flagged correctness bug). Design S3 findings and mutation survivors wait for the user's ruling instead of being fixed by default.
- **Sorting by typed records + triage,** over the orchestrator applying the rule to prose: the per-task loop already removed that judgment from the orchestrator, and records survive compaction.
- **Fix in place,** over a remediation plan per round: blocking items are now few, the `final` fix path already exists, and per-round plans re-dispatched every gate.
- **Re-check by the raising gates only, even after a holistic round:** re-running every gate is what made a second close round expensive. Triage carries every unsent finding itself, so a narrow re-check loses nothing.
- **One disposition per finding, from one source** (its id and the latest ruling), over filing, deferral and promotion as separate mechanisms: those spread a finding's state across records, notes and resolutions, and each reviewed interaction between them was a bug. The cap mirrors tasks (two rounds, then the user).
- **`close` is its own scope,** separate from `final`, so the whole-change gate's rounds and the close's rounds are counted apart.
- **Plan coverage before the build,** over a spec reviewer at the close or dropping the check: a missing requirement starts at planning, the check reads two documents instead of a whole change, and with it every link spec → plan → task → ask is checked by an agent. It reuses `spec-reviewer` (spec conformance is its job) instead of a new agent.
- **Enforcement at `task_brief.py --spec`:** deterministic and already the SDD entry point; inline execution relies on lean-plan's step.
- **No migration:** the only real-world closes ran outside the ledger's close commands; restarting a close is cheaper than converting one.

## 9. Acceptance criteria

- A close with one design S3, one mutation survivor, one intent not-met and one design S4 produces a fix round sending exactly the not-met and the S4; the other two are carried and, once nothing blocks, listed in a `decide` step.
- A close with only S1–S3 findings and no not-met goes straight to `decide`; ruling them `file` reaches `done` and files each once, with rule, source and report path.
- A finding a narrow re-check doesn't repeat is still carried and still decided.
- A can't-tell yields `clarify` (no snapshot, no round); after the re-check turns it into not-met, the next triage starts a fix round including it.
- A patch fix at `close` committed through `commit --task close` and re-checked clean by its raising gate reaches `done`; gates that raised nothing sent are not in the re-check set.
- Two fix rounds that leave blocking work open escalate; `user ruling: fix <id>` starts a ruling round sending it; `user ruling: file <id>` on the rest reaches `done` with them filed.
- `user ruling: fix <id>` on a waiting finding starts a ruling round sending it, and a fixed one (its gate stops raising it) reaches `done`; a later ruling on the same id replaces the earlier one.
- `check` refuses each malformed close record listed in §6.
- `task_brief.py --spec S` refuses a plan with no `Spec coverage:` line, one naming another spec, and one whose report is missing, and accepts a valid pass line and a valid user-ruling line.
- A coder's `notes_skipped` naming `note#run-note[...]` or `note#task-note[...]` files nothing; a skipped reviewer note is still filed.
- `run-state` reports `closing` mid-close with the close's latest step as the next action, `finished` after `done`, and lists the close's rounds.
- `path --task gate`, `path --task ruling` and `close-round --expect` fail with messages naming the replacement.
- The full suite passes; the verification skill no longer describes Step 4, round 2 as a re-dispatch of every gate, remediation plans per round, or the orchestrator's four-way sort.

## 10. Validation strategy

Unit tests on the close rule set in `triage.py` cover each tier and step kind, including the cap, rulings (and a changed ruling), carried findings, decide, clarify and done-time filing. Store-level tests drive whole closes through `cmd_check` and `cmd_triage` as a coder and gates would, the way 0.15.0's task-loop tests do, so record validation and routing are exercised together. `store_state` tests cover the new verdicts on synthetic logs, including a store with legacy close entries. `task_brief` tests cover the coverage line. Drift tests keep the typed-record sections shared across the two design reviewers identical, and the docs are checked against the acceptance list by reading.
