# Review a branch

Use this for an ad-hoc, senior-level review outside the automated per-task gates — when you're stuck, before a refactor, or you just want a fresh perspective on work in progress.

## Steps

1. **Request the review:**

    ```
    /requesting-code-review
    ```

    It assembles the change (by default `git merge-base HEAD main`..`HEAD`) and dispatches a review.

2. **For a standalone refactor pass**, invoke the language review skill directly instead:

    ```
    /python-review      # or /rust-review
    ```

    These are hands-on: they recover architectural intent, identify drift, and propose small reviewable patches.

3. **Handle the feedback with rigor.** Run `receiving-code-review` on the findings. Verify each one against the actual code — do not reflexively obey or dismiss. A stated rationale ("kept it simple deliberately") never auto-downgrades a real finding.

4. **Apply the in-scope fixes.** Fix findings introduced by this work in this change; log only a genuinely separate, larger improvement as a follow-up.

## You have now

Gotten a senior-level read on the branch, separated real findings from noise, and applied the ones that belong to this change — without waiting for the full completion gate.

!!! note "Routine review is automatic"
    Inside the pipeline, every task is already reviewed by the spec, quality, and commit-lite gates, and the whole change by the senior `*-design-reviewer` agents at completion. This guide is for review *outside* that flow. See the [Agents reference](../reference/agents.md).
