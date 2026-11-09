# The Close Through Triage Design Spec

## 1. Scope

The completion close (`verification-before-completion`: design reviewers, intent reviewer, the optional mutation gate) runs through the same ledger machinery as the per-task loop. The close gates write typed records, `ledger.py triage --task close` decides each step, blocking findings are fixed in place, and everything else is filed as a follow-up. The close's own requirements check (Step 4) is replaced by a plan coverage check before the build. Close-scoped user rulings stop being filed as run-notes, and a coder's skipped store note is no longer filed as a follow-up. Intent: `.claude/output/intent/2026-11-09-close-through-triage-intent.md`.

## 2. Goals

- Only an intent `not-met` or an S4+ finding from any close gate blocks finishing; every other close finding becomes a follow-up carrying its rule and report path (intent 1).
- Close findings are routed by `triage` from typed records, never sorted by the orchestrator (intent 2).
- A blocking finding is fixed in place from a triage-taken baseline and re-checked only by the gate that raised it, scoped to the fix; no remediation plan or second SDD run (intent 3).
- At most two close fix rounds, then escalation to the user, who chooses a ruling round or "defer the rest" (intent 4).
- An agent confirms spec coverage of the plan before any coder runs, and a brief can't be built from a spec-citing plan that skipped it (intent 5).
- A close ruling never reaches a coder or holds a task, and a coder's skipped store note is never filed (intent 6).
- `run-state` shows the close's rounds, rulings and deferrals after a compaction (intent 7).

## 3. Non-goals

- No change to the per-task loop's routing, its two-round cap, or the whole-change gate at `final`.
- No change to what each gate judges (design rubric, spec-blind intent judgment, mutation workflow and rigor budgets), only to how its result is recorded and routed.
- No migration of a close already in progress: it restarts as a new close (§7).
- `cannot_verify` is unchanged (run data shows it is no longer a problem).
- The completion report and the close batch's fix / file / ignore choice stay, except where §4 changes what "fix" does.

## 4. System behavior

**Starting the close.** After tests, lints and the whole-change gate, `ledger.py close-round --note "<work being closed>"` starts a close: it records the HEAD under review and refuses while the close owns an open question, disclosure or unrun task-note (as today), or when the store already holds a close this release started: an unfinished one resumes at triage, and a finished one reopens only by a promotion, so a new close needs a cleared store (a legacy entry, which carries a `round` field, never blocks). Added after review: two closes in one store would mix their records. The mutation-gate question is asked before the dispatch, as in 0.15.0, and its answer is logged on `--task close`.

**Dispatch.** Every applicable gate goes out in one message: each matching `*-design-reviewer`, `intent-reviewer`, and `mutation-tester` when the user chose it. Each writes its prose report and a typed record (§6), and runs `ledger.py check` on the record. The orchestrator never fixes or sorts while a gate is out.

**Triage at the close.** `ledger.py triage --task close` reads the close records and applies the close rule set:

| Finding | Tier |
|---|---|
| intent `not-met`, any severity | blocking |
| S4–S5 from any close gate | blocking |
| anything else (S1–S3, mutation survivors, design S3) | filed |

Blocking findings route as task findings do: local or class reach to a `patch` round, contract reach (or reach a coder raised) to a `holistic` round with one decision doc from the per-task `remediating-issues` variant. Filed findings become follow-ups once each (`from: close`), with the finding's rule, its sites, the raising record and its report path. There is no note tier: nothing below the line is sent to a coder.

**Can't-tell.** While any intent statement is `can't-tell`, triage prints a `clarify` step naming the intent reviewer and the access each statement needs; it starts no fix round and counts toward no cap. A statement the user settles (`resolve <id> --note "user ruling: ..."`) stops holding it. Blocking work and a clarify step can't both be pending: clarify comes first, so a late `not-met` joins the next fix round.

**Fixing.** A fix round's coder writes `close-<coder>.json` (its first close fix is cycle 2, like the first fix at `final`), works from the baseline triage printed, and its fix is committed with `ledger.py commit --task close`, which commits a finished fix without completing anything (the `final` fix path's behavior). Re-check is `raising`: only the gates whose blocking findings were sent re-check, given the round's `Fix baseline` and the settled ids, and they judge the fix diff and its consumers. The mutation tester re-checks only when it raised a sent finding, and mutates only the fix range. A new finding in a re-check is routed by the same table: below the line it is filed, S4+ blocks wherever it sits.

**Cap and exits.** After two `patch`/`holistic` rounds with blocking work open, triage escalates. The user, per item or for all:

- rules a fix: `append --type progress --task close --note "user ruling: ..."` starts a ruling round (as in tasks), re-checked by the raising gates;
- defers: `resolve <id> --note "user ruling: defer ..."` settles the finding and triage files it as a follow-up (a plain waiver still just drops it);
- after a ruling round that leaves blocking work open, the escalation recommends deferring.

**Done.** Triage prints `done` when no blocking work, held item or can't-tell remains. The close is finished at that entry; nothing else completes it.

**The close batch.** As today, `ledger.py report` groups open follow-ups by rule and the user picks fix / file / ignore. An item marked fix is promoted: a ruling note on `--task close` naming follow-up ids reopens those findings into a ruling round at `close`, worked in place and re-checked by the gates that raised them. Promoting after `done` reopens the close; its `done` comes again from triage.

**Plan coverage check.** As lean-plan's last step, when the plan cites a spec, the `spec-reviewer` runs in plan coverage mode with only the spec and the plan. Its report lists each spec requirement no task covers and each task doing work the spec doesn't ask for, with a verdict `PASS` or `GAPS`. The planner closes each gap (add or extend a task, or the user cuts it from the spec) and re-dispatches once; anything left goes to the user. The plan then carries a `Spec coverage:` line (§6). `task_brief.py --spec <spec>` refuses a plan without a valid line for that spec. A plan with no spec skips the check.

**Close rulings and skipped notes.** A ruling about the close is a progress note on `--task close`, never a run-note; run-notes remain only for rules coders must act on. When a coder lists a store note (an id starting `note#`) in `notes_skipped`, triage never files it as a follow-up; skipped reviewer findings are filed as before.

**`run-state`.** Its verdicts become `fresh`, `resume`, `closing`, `finished`, `foreign`, `ambiguous`. `closing`: every task complete and a close started but not `done`; its next action names the close's latest step. `finished`: the latest close reached `done`. The run's rounds section lists the close like a task (its triage kinds in order), and its rulings and deferrals appear with the notes.

## 5. Architecture

- **`triage.py`** gains the close rule set beside the task rule set: a pure function of the same shape that takes the close's findings (each with source role, severity, reach, and an intent verdict where present), can't-tell statements, rulings, waivers, deferrals and prior entries, and returns the step. The task rule set is untouched.
- **`ledger.py`** validates the three new record roles, adds `close` as a scope everywhere a scope is named (records, decisions, paths, triage, commit, progress, notes, `_scope_log`), files close deferrals with their report paths, honors `user ruling: defer`, and reads promotion rulings. Its close scope log is everything after the latest `close_round` entry.
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

**Triage entry at `close`.** Same shape as a task entry. New kind `clarify` (recheck `intent-reviewer`, no snapshot, no round). Finding tiers at close: `blocking` (sent, with `patch`/`holistic` routing), `filed`, `held`.

**Deferral and promotion.**
- `user ruling: defer` (case-insensitive prefix on a resolution note) settles a close finding and files it.
- A close follow-up note carries `finding` (the finding id), `source` (the raising record stem) and `report` (its report path) beside its text and rule.
- A promotion is a progress note on `--task close` starting `user ruling:` that names one or more close follow-up note ids; triage starts a ruling round sending those findings, resolves the follow-ups as promoted, and re-checks with their sources.

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
- Every close finding ends in exactly one of: fixed and re-checked, filed (once), deferred by ruling (filed once), waived by ruling, or held for the user.
- A filed or deferred close finding is never filed twice, including across re-checks that re-raise it.
- A close fix commits only the coder's footprint and never completes a scope.
- A store whose close began under an earlier release is not converted: `close-round` starts a new close after its entries, and the old entries are ignored by close triage.
- Snapshots, baselines and fix cycles at `close` follow the 0.15.0 rules (`fix_cycle`, history-aware open fix, one reuse per snapshot).
- Prose follows the repo rules: no hard-wrapped markdown, no project names, task numbers or run histories in plugin text.

## 8. Key decisions and tradeoffs

- **What blocks: intent + S4+.** Chosen over "every S3+" (today, which produced long remediation chains) and "intent only" (would ship a design-flagged correctness bug). Design S3 and mutation survivors are filed and can be promoted.
- **Sorting by typed records + triage,** over the orchestrator applying the rule to prose: the per-task loop already removed that judgment from the orchestrator, and records survive compaction.
- **Fix in place,** over a remediation plan per round: blocking items are now few, the `final` fix path already exists, and per-round plans re-dispatched every gate.
- **Re-check by the raising gates only, even after a holistic round:** re-running every gate is what made a second close round expensive. Fresh findings below S4 are filed anyway, so narrower re-checks lose nothing that blocks.
- **Cap and exits mirror tasks** (two rounds, ruling round, defer the rest) so the user learns one escalation model.
- **`close` is its own scope,** separate from `final`, so the whole-change gate's rounds and the close's rounds are counted apart.
- **Plan coverage before the build,** over a spec reviewer at the close or dropping the check: a missing requirement starts at planning, the check reads two documents instead of a whole change, and with it every link spec → plan → task → ask is checked by an agent. It reuses `spec-reviewer` (spec conformance is its job) instead of a new agent.
- **Enforcement at `task_brief.py --spec`:** deterministic and already the SDD entry point; inline execution relies on lean-plan's step.
- **No migration:** the only real-world closes ran outside the ledger's close commands; restarting a close is cheaper than converting one.

## 9. Acceptance criteria

- A close with one design S3, one mutation survivor, one intent not-met and one design S4 produces a fix round sending exactly the not-met and the S4, and files the other two once each with rule, source and report path.
- A close with only S1–S3 findings and no not-met reaches `done` on its first triage, with every finding filed.
- A can't-tell yields `clarify` (no snapshot, no round); after the re-check turns it into not-met, the next triage starts a fix round including it.
- A patch fix at `close` committed through `commit --task close` and re-checked clean by its raising gate reaches `done`; gates that raised nothing sent are not in the re-check set.
- Two fix rounds that leave blocking work open escalate; a ruling starts a ruling round; `user ruling: defer` on the rest reaches `done` with those findings filed.
- A promotion ruling naming a close follow-up starts a ruling round at `close` sending that finding.
- `check` refuses each malformed close record listed in §6.
- `task_brief.py --spec S` refuses a plan with no `Spec coverage:` line, one naming another spec, and one whose report is missing, and accepts a valid pass line and a valid user-ruling line.
- A coder's `notes_skipped` naming `note#run-note[...]` or `note#task-note[...]` files nothing; a skipped reviewer note is still filed.
- `run-state` reports `closing` mid-close with the close's latest step as the next action, `finished` after `done`, and lists the close's rounds.
- `path --task gate`, `path --task ruling` and `close-round --expect` fail with messages naming the replacement.
- The full suite passes; the verification skill no longer describes Step 4, round 2 as a re-dispatch of every gate, remediation plans per round, or the orchestrator's four-way sort.

## 10. Validation strategy

Unit tests on the close rule set in `triage.py` cover each tier and step kind, including the cap, ruling, defer, promotion and clarify paths. Store-level tests drive whole closes through `cmd_check` and `cmd_triage` as a coder and gates would, the way 0.15.0's task-loop tests do, so record validation and routing are exercised together. `store_state` tests cover the new verdicts on synthetic logs, including a store with legacy close entries. `task_brief` tests cover the coverage line. Drift tests keep the typed-record sections shared across the two design reviewers identical, and the docs are checked against the acceptance list by reading.
