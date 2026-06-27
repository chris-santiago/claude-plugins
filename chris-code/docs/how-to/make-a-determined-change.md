# Make a determined change

Use this when the intended behavior is already settled and the only open question is *which implementation best fits the codebase* — a refactor, a migration, an API or consistency alignment, or implementing an already-specced behavior. If *what to build* is still live, start with [`brainstorming`](../tutorials/getting-started.md) instead.

## Steps

1. **Invoke the engine** with the determined change:

    ```
    /coherent-change
    ```

2. **Point at an exemplar.** State the change in one sentence and name the existing code or convention the implementation should mirror. The engine is built to *discover* the coherent implementation from existing code, not invent one.

3. **Review the defended choice.** The engine dispatches parallel `Explore` agents to inventory the affected paths, generates two to four grounded candidates (each cited to a concrete precedent), and presents the **defended choice**: the selected approach, a correctness table over *every* affected case, why it wins on reuse and idiom-fit, and a rebuttal of each alternative. This is the single approval checkpoint — approve the choice before any code changes.

4. **Confirm the execution route.** From the correctness table the engine sizes the change and recommends one of two routes — confirm it:
    - **Single coherent edit** → build inline (next step).
    - **Major / multi-task change** → planned execution. The defended choice is settled design, so it routes to `lean-spec` → `lean-plan` → `subagent-driven-development` instead of being built in one shot — and you're done in this skill.

5. **(Inline route) Let it build and self-gate.** The matched coder agent implements *only* the approved change; the engine then runs the `*-review-lite` gate on the staged diff and hands back a working, lite-reviewed change.

6. **(Inline route) Run the close yourself.** When you invoke `coherent-change` directly, *you* are the caller: lock in durable coverage, run `verification-before-completion`, then `finishing-a-development-branch`.

## You have now

Made a change that fits the codebase rather than bolting on logic it already has a pattern for — chosen against real alternatives, proven correct across every affected case, and lite-reviewed before hand-back. (Or, for a major change, handed a fully-defended design to planned execution.)

!!! note "Used as an engine"
    `remediating-issues` and `systematic-debugging` call `coherent-change` for you and own the close. See [The determined-change engine](../explanation/the-pipeline.md#the-determined-change-engine).
