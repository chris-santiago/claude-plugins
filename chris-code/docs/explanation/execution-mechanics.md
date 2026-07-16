# Execution mechanics

`subagent-driven-development` is where a plan becomes code, and most of its design exists to solve two problems that show up the moment you drive real work through subagents: the orchestrator's context fills with noise, and a controller that loses its place re-does finished work. These mechanics — several backported from superpowers v6.0.0 and adapted to chris-code's agent layer — are how it stays lean and recoverable.

## Staged parallelism

Tasks aren't dispatched flat-sequential (slow) or flat-parallel (collisions). Instead the orchestrator **maps each task's file footprint up front** — every source and test file it will touch — and groups tasks into stages where everything in a stage has zero file overlap. Within a stage, subagents run concurrently; between stages, it waits for all reviews to pass before starting the next.

The common serialization triggers are two tasks editing the same shared module or the same test file (`conftest.py`, `lib.rs`), or a later task depending on a type an earlier one introduces. When in doubt, it serializes — the cost of a conflict is higher than the cost of waiting. This is what lets chris-code treat parallelism as a feature rather than the footgun superpowers warns against.

## File handoffs

Anything pasted into a dispatch, and anything a subagent prints back, stays resident in the orchestrator's context for the rest of the session. So nothing is pasted. Artifacts are handed over as **files** under `.git/sdd/` (per-worktree, uncommitted):

- **The task brief** is a *reference sheet*, not a restatement of the spec. A script extracts the plan's task entry — its actions, its `Consumes:` pointers, its spec §-references — to a file. The dispatch then carries only pointers: where the task fits, the brief path, the spec path (the coder reads the referenced sections itself), the verbatim global constraints, and the report-file path.
- **Cross-task context** the coder can't recover by reading — a dependency contract (`built in Task 3 → path`), a conflict adjudication, a code entry point — is added to the brief as terse pointers, never as dereferenced spec content.
- **The implementer's report** is written to its own file; the subagent returns only status, the changed-file list, a one-line test summary, and concerns.
- **Reviewers** get file paths (brief, report, changed files) plus the verbatim constraints, and read the actual code. Diffs are never pasted.

The one thing pointers can't capture is **intent** — the observable outcome the task must produce. A fresh subagent doesn't inherit your conversation, so the brief states the *why* explicitly while everything else is referenced. See [Context & dispatch](context-and-dispatch.md).

## Pre-flight plan review

Before Task 1, the plan is scanned **once** for internal conflicts (tasks that contradict each other or the constraints) and plan-mandated defects (anything the plan asks for that a reviewer would flag — a test that asserts nothing, verbatim duplication, a swallowed error). Findings are raised as a single batched question with the offending plan text, asking which governs. A clean scan proceeds silently. This catches design problems before they're built, rather than per-task mid-run.

## Durable progress ledger

Conversation memory does not survive compaction, and a controller that loses its place can re-dispatch finished tasks. So progress is tracked in a **ledger**, not only in the live task list. When a task's reviews come back clean, it's appended to `.git/sdd/progress.md`. After compaction, the orchestrator rebuilds its task list from the ledger and trusts the ledger and `git log` over its own recollection — finished tasks are never re-run.

## Cross-task pattern ledger

Staged parallelism and file handoffs both work by keeping each coder's context small and disjoint — which is exactly what blinds a coder to what its siblings are doing. Four tasks that each need the same block of logic will each write it, and every per-task review passes, because no reviewer ever sees more than one diff. The orchestrator is the only actor that sees the whole task sequence, so preventing that duplication is its job alone.

The **pattern ledger** is how it holds that view. After each task, the orchestrator records any newly added multi-line shape a later same-family task will need — a shared helper, a call sequence, a dispatch block — appended to the same `.git/sdd/` ledger as progress, so it survives compaction. Before dispatching a later task, it carries the pointer into that task's brief: *call this symbol, don't re-inline it.* When a coder reports a `DUPLICATION-PENDING` flag (it copied a block because the file that should own the helper was outside its footprint), the orchestrator records it and assigns the hoist to the next task whose footprint covers that file, rather than letting the copy ride to the commit.

This is the execution-altitude link in a longer chain: `lean-plan` grounds against existing code and names a shape several tasks will share as a contract with an owner; the ledger carries that contract between tasks; the coder mirrors by reference. The chain exists because coherence established when a change is whole does not survive decomposition unless it is deliberately carried — see [Coherent change](coherent-change.md#coherence-has-to-survive-decomposition).

## Reviewer integrity

The gates are only as good as their independence, so several rules protect it:

- Reviewers are **read-only** and never mutate the tree.
- The orchestrator **never coaches a reviewer** to suppress, soften, or pre-rate a finding — no "don't flag X," no "at most Minor." If a dispatch contains that language, it's pre-judging to spare a review loop; the finding must be raised and adjudicated in the open.
- A reviewer's mandate is **never narrowed** to a subset of its remit ("just check for bugs," "only the parser"). Under-cueing the scope is as corrosive as suppressing a finding.
- **Plan-mandated defects are the user's call** — surfaced with the plan text, never silently fixed against the plan or silently shipped because the plan asked for it.

## Judging from compressed reports

The orchestrator decides what to integrate from *compressions* — a coder's report, a reviewer's verdict — one step removed from the evidence. It classifies each before acting: **fact-shaped** claims (did the suite pass?) it trusts; **judgment-shaped** verdicts (a cohesion call, a "cannot verify," a conflict) it does not integrate without **re-reading the actual code slice** the verdict judged. A verdict you haven't grounded in its evidence is an assertion laundered into a decision. When it can't ground something, it escalates with the evidence attached, not a paraphrase. This is the integrator-side half of "Do Not Trust the Report" — see [The assurance model](the-assurance-model.md#the-integrator-is-the-unguarded-seam).
