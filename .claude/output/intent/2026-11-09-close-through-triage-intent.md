# The close through triage: intent ledger

Frozen 2026-11-09 from the brainstorming dialogue; changes only by the user's explicit decision.

1. At the close, only an intent `not-met` or an S4+ finding from any gate blocks finishing the branch. Every other finding is filed as a follow-up with its report path (the user chose "Intent + correctness").
2. Close findings are sorted by `ledger.py triage` from the gates' typed records. The orchestrator never decides whether a close finding is trivial, test-only, separable or non-trivial ("Typed records + triage").
3. A blocking close finding is fixed in place by a coder and re-checked only by the gate that raised it, scoped to the fix. No new plan or SDD run starts ("In place, like a task fix").
4. After two fix rounds with blocking work still open, the close stops and asks the user, who can choose one more ruling round or "defer the rest", which files every open item as a follow-up and lets the close finish ("Same as tasks").
5. Before any coder runs, an agent confirms that every spec requirement is covered by a plan task, and a plan that cites a spec but skipped that check can't produce a task brief ("Plan coverage check").
6. A ruling about the close never reaches a coder or holds up a task, and a coder skipping a run-note never creates a follow-up ("fold item 1 into plan").
7. After a compaction, `run-state` shows where the close stands: its rounds, the user's rulings and what was deferred.
