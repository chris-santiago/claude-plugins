# Explanation

Understanding-oriented background. These pages cover *why* chris-code is shaped the way it is — the design decisions and trade-offs behind the pipeline and the gates.

- **[The pipeline](the-pipeline.md)** — why design comes before code, the split between design-open and determined work, and the shared change engine.
- **[The assurance model](the-assurance-model.md)** — what the review gates actually prove (and what they don't), and why intent is checked separately from conformance.
- **[Context & dispatch](context-and-dispatch.md)** — the balance between offloading work to subagents and keeping context in the session, and why the brief must carry intent.
- **[Execution mechanics](execution-mechanics.md)** — how `subagent-driven-development` stays lean and recoverable: staged parallelism, file handoffs, the progress ledger, reviewer integrity.
- **[Relationship to superpowers](vs-superpowers.md)** — what chris-code inherited from its parent project and where it diverged.

For *what* each piece is, see the [Reference](../reference/index.md); for *how* to use it, the [how-to guides](../how-to/index.md).
