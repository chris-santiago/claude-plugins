# Intent ledger: orchestrator note store

Frozen 2026-10-30. Changes only by explicit user decision.

The ask, in the user's words: an orchestrator note store built into chris-code, because "this is priority and must be done well. it improves current implementation and unlocks task-runners"; "knowledge through files, authority at the orchestrator"; and the orchestrator must know to use it "vice an adhoc notes.md like ferrum did".

1. A note filed for a later task appears in that task's brief without anyone passing it by hand, and the task cannot be marked complete while a note aimed at it is undelivered, unless its waiver is logged with a reason.
2. A run-wide rule reaches every task briefed after it is filed and every task already in flight before that task completes; it can no longer drop out of later briefs.
3. An owed disclosure (changelog, spec or docs) blocks its owner task's completion, or the close, until it is resolved with where it landed; an owed question for the user blocks the same way until the user rules.
4. After a compaction or a pause, `ledger.py run-state` alone shows where the run stands (stages and file footprints, task states, notes owed, open questions, live agent handles, the latest checkpoint), with no free-form notes file.
5. The completion report lists every follow-up, unlisted case, orchestrator disposition and user ruling straight from the store; nothing is reconstructed from memory, and neither `clear` nor branch cleanup can destroy them without reporting them or the user's confirmation.
6. Two unfinished tasks in one stage cannot be recorded with overlapping files, and concurrent writers cannot corrupt the store.
7. The orchestrator uses the store instead of an ad-hoc notes file ("knowledge through files, authority at the orchestrator"): the store is the only path by which notes reach briefs, gates, resume and the report, and the skill says so.
8. (Added 2026-10-30 by the user's decision to fold in the fix-loop checks.) Every fix has its own snapshot, and a fix the reviewers flagged as recurring or fix-caused cannot be logged as trivial, so the two-fix cap reaches the user whoever drives the task.
