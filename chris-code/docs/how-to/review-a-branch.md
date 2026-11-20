# Review a branch

Use this for an ad-hoc, senior-level review outside the automated per-task gates — when you're stuck, before a refactor, or you just want a fresh perspective on work in progress.

## Steps

1. **For a design and cohesion review**, invoke the language review skill:

    ```
    /python-review      # or /rust-review
    ```

    It recovers architectural intent, identifies drift, and proposes changes as end-states. It applies nothing itself: it routes what it proposes to `coherent-change`.

2. **For a quality and bug review of specific files**, ask for the quality reviewer that matches the language (`python-quality-reviewer`, `pytorch-quality-reviewer` or `rust-quality-reviewer`) on the files or diff you name. Outside a run it returns its review inline and writes nothing.

3. **Check each finding against the code** before acting on it. A stated rationale ("kept it simple deliberately") never downgrades a real finding, and a suggestion that looks wrong is verified, not obeyed.

4. **Apply the in-scope fixes.** Fix findings introduced by this work in this change; log only a genuinely separate, larger improvement as a follow-up.

## You have now

Gotten a senior-level read on the branch, separated real findings from noise, and applied the ones that belong to this change — without waiting for the full completion gate.

!!! note "Routine review is automatic"
    Inside the pipeline, every task is already reviewed by the spec and quality reviewers and checked by the commit gate, and the whole change at completion by the senior `*-design-reviewer` agents, the spec-blind intent re-check, and the mutation re-check if you choose it, run together as one close. This guide is for review *outside* that flow. See the [Agents reference](../reference/agents.md).
