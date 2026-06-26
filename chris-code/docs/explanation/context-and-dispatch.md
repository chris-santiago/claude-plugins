# Context & dispatch

chris-code leans heavily on subagents — coders, reviewers, explorers — each running in its own context. The original question behind the whole framework was a balance: *how much work should be tasked to agents to preserve the main context, versus kept in-session where it consumes context but loses nothing?* Where you draw that line is the difference between a clean, recoverable run and a pile of confident-but-wrong reconstructions.

## The tension, both ways

The cost of **dispatching** is fidelity: a fresh subagent doesn't inherit your conversation, so anything you understood but didn't write down is gone. The cost of **staying in-session** is context: every file you read and every result a step prints stays resident in the orchestrator's window for the rest of the session, crowding out the coordination work only the orchestrator can do.

Neither cost is free, so the choice has to be principled rather than habitual.

## The rule

**Dispatch when the task's context is recoverable from artifacts; stay in-session when the *why* lives only in the conversation.**

A fresh subagent reconstructs its understanding from what it can read — the brief, the spec, the repo. That works when the relevant context is *externalized* into those artifacts. It fails silently when the deciding context exists only in the back-and-forth you just had with the user and never made it to a file. So the orchestrator has a standing obligation: **don't dispatch context you've only externalized in your head.** Either write the *why* into the brief, or keep the task in-session.

## Why the lean spec is what makes dispatch safe

This is the quiet payoff of the [lean artifacts](the-pipeline.md#lean-artifacts) discipline. The spec is, in effect, the **context-serialization mechanism**: design front-loads the work of externalizing intent and contracts into a durable document, and *because* that's done, a task can be handed to a fresh agent without loss. Dispatch is lossless only to the degree the design captured what the agent needs. A workflow that skipped design and tried to dispatch would be handing agents reconstructions of context that was never written down — which is exactly the silent-failure case above.

## The brief is the only channel for intent

A coder recovers *what* and *where* by reading — the files it touches, the spec sections it's pointed at, the repo's idioms. It cannot recover *why*: the observable outcome the change must produce. A fresh subagent does not inherit your conversation, so the brief is intent's only channel.

That makes intent a **required element** of every dispatch, not an optional nicety. The brief carries one or two lines on the outcome the task must produce (quoting the intent-ledger statement where one exists). Handing over only *what* and *where* lets a coder optimize the diff and ship the wrong thing correctly. The loop is two-sided: the orchestrator must supply the why, and the coder is told to **demand it** — to escalate rather than guess when a brief gives only *what* and *where*. If the orchestrator can't state the why, that's the signal the task isn't ready to dispatch.

## Pointer-based handoff

Briefs are reference sheets, not restatements of the spec. They carry pointers — "the contract built in Task 3 lives here," "section 5 governs this call," the landing symbol — and trust the coder to trace the chain by reading. The one thing pointers can't capture is intent, which is why intent is stated explicitly while everything else is referenced. This keeps the orchestrator's context lean and the dispatch honest: a fresh agent gets its brief, the interfaces it touches, the constraints, and the goal — nothing more. The file-based machinery that implements this is described in [Execution mechanics](execution-mechanics.md).

## The integrator side

Dispatch has a return leg, too. Whatever a subagent hands back is a *compression*, and the orchestrator decides what to integrate from it — one step removed from the evidence. That seam has its own discipline (re-read the slice behind a judgment, escalate with evidence not a paraphrase), covered in [The assurance model](the-assurance-model.md#the-integrator-is-the-unguarded-seam).
