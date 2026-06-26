# Remediate a bug

Use this when you have a known defect — a GitHub issue, a review finding, or a problem named in session — and more than one fix is plausible. For a trivial one-line fix with a single obvious solution, just fix it; this workflow is for bugs with a real fix-space.

## Steps

1. **Invoke the skill** with the bug:

    ```
    /remediating-issues
    ```

    or describe the bug and let it trigger.

2. **Confirm the framing.** The skill first checks the bug is *real and still open* (a stale or already-fixed issue is closed with evidence, not fixed again), then completes the root-cause phase of `systematic-debugging`. Answer any questions about reproduction.

3. **Review the defended choice.** The skill builds the fix through the [`coherent-change` engine](../explanation/the-pipeline.md#the-determined-change-engine): it researches the codebase, generates grounded candidate fixes, and presents a **defended choice** — the selected fix, a per-case correctness table, and a real rebuttal of each alternative. Approve it before any code changes.

4. **Let it close the bug.** Once the fix is built and self-reviewed, the skill runs the bug close in order:
    - `regression-test` — a test for the specific failure mode, proven to fail on the pre-fix code.
    - `verification-before-completion` — tests, lints, design review, requirements, and the spec-blind intent re-check.
    - `finishing-a-development-branch` — merge, PR, keep, or discard.

5. **Confirm the origin is recorded.** A GitHub issue is referenced in the commit and closed; a review finding is marked addressed.

## You have now

Fixed the bug with a defended, codebase-coherent fix; locked it in with a regression test that fails without the fix; and recorded the resolution against its source. The fix closes the bug across every sibling case its root cause reaches, not just the reported symptom.
