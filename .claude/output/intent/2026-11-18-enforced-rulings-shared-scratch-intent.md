# Enforced inline rulings, one shared break-check copy and typed unverified items: intent ledger

Frozen 2026-11-18 from the brainstorming dialogue ("These are all serious. Especially ones not behaving as designed"); changes only by the user's explicit decision.

1. When triage marks a fix round as one the orchestrator could fix itself, that round does not move (no coder fix accepted, no inline fix started) until the user's answer for that round is on record, and that answer decides who fixes it ("Every round, enforced").
2. However many tasks and reviewers a run has, its break checks use one source copy and one build cache ("One per run, locked").
3. Two reviewers never run commands in that copy at the same time; the second waits or is told who holds it.
4. After a break is restored in the copy, the next test run builds the restored code, never a stale binary.
5. A break-check command that passes its time or memory limit is stopped and reported as stopped; it cannot take the machine down ("computer crashed overnight").
6. Every `cannot_verify` item is settled by what can actually settle it (a command's recorded result, a filed note, or `claim-checker`'s quoted lines), and none by the orchestrator's own note ("Type them, ledger routes").
7. A commit that includes a renamed file commits the deletion too; a Verify command naming a missing program fails the gate; an `n/a` tests-first entry with no test is accepted.
