# SDD rules into scripts: intent ledger

Frozen 2026-11-05 from the brainstorming dialogue; changes only by the user's explicit decision.

1. When `triage` routes a fix, it prints the `Fix baseline` itself. The orchestrator never runs `snapshot` in an SDD run, and re-running `triage` gives back the baseline of a fix that's still open ("triage takes the snapshot itself and prints Fix baseline").
2. `run-state` says in one line whether the store is fresh, a resumable run, a close-gate remediation in progress, a finished run, another plan's store, or ambiguous, and what to do next ("run-state classifies the store… It then says what to do").
3. One `ledger.py commit` command takes a ready task through staging exactly its files, the gate, a commit with the orchestrator's message, and `complete`. A blocked task or a failing gate produces no commit ("One ledger.py commit --task N --message … command").
4. The orchestrator gets every record and report path from the script, and no skill tells it to build a name like `final-r2-*` by hand ("Scripts print record paths").
5. The prose rules these replace are gone from SDD, verification and executing-plans ("Move deterministic rules into the scripts").
6. The work is built tests first, and the full suite passes ("tests first").
