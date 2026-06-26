# Context & dispatch

chris-code leans heavily on subagents — coders, reviewers, explorers — each running in its own context. The reason is concrete: anything pasted into a dispatch, and anything a subagent prints back, stays resident in the orchestrator's context for the rest of the session. Offloading work to focused subagents keeps the main context window clean for coordination. But there's a real tension, and where you draw the line matters.

## When to dispatch, and when to stay

The rule of thumb: **dispatch when the task's context is recoverable from artifacts; stay in-session when the *why* lives only in the conversation.**

A fresh subagent reconstructs its understanding from what it can read — the brief, the spec, the repo. That works when the relevant context is *externalized* into those artifacts. It fails silently when the deciding context exists only in the back-and-forth you just had with the user and never made it to a file. Dispatching such a task hands the agent a confident-but-wrong reconstruction.

So the orchestrator has a standing obligation: **don't dispatch context you've only externalized in your head.** Either write the *why* into the brief, or keep the task in-session.

## The brief is the only channel for intent

A coder recovers *what* and *where* by reading — the files it touches, the spec sections it's pointed at, the repo's idioms. It cannot recover *why*: the observable outcome the change must produce. A fresh subagent does not inherit your conversation, so the brief is intent's only channel.

That makes intent a required element of every dispatch, not an optional nicety. The brief carries one or two lines on the outcome the task must produce (quoting the intent-ledger statement where one exists). Handing over only *what* and *where* lets a coder optimize the diff and ship the wrong thing correctly. The loop is two-sided: the orchestrator must supply the why, and the coder is told to **demand it** — to escalate rather than guess when a brief gives only *what* and *where*. If the orchestrator can't state the why, that's the signal the task isn't ready to dispatch.

## Pointer-based handoff

Briefs are reference sheets, not restatements of the spec. They carry pointers — "the contract built in Task 3 lives here," "section 5 governs this call," the landing symbol — and trust the coder to trace the chain by reading. The one thing pointers can't capture is intent, which is why intent is stated explicitly while everything else is referenced. This keeps the orchestrator's context lean and the dispatch honest: a fresh agent gets its brief, the interfaces it touches, the constraints, and the goal — nothing more.
