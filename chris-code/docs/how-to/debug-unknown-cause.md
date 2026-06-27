# Fix a bug — cause unknown

Use this when something fails unexpectedly and you **don't yet know why**. Never propose a fix before the root cause is found — random patches mask the real issue and breed new bugs. If you already know the cause (e.g. a tracked issue), use [remediate a bug](remediate-a-bug.md) instead.

## Steps

1. **Invoke `/systematic-debugging`.** It runs four phases, and the first is root cause — you don't leave it until the cause is established (including a System Boundaries check: FFI, serialization, type coercion).
2. **The fix becomes a determined change.** With the root cause known, `systematic-debugging` hands the fix to `coherent-change`, which researches the codebase, defends the most coherent fix against alternatives, and — by scale — builds it inline or routes it to spec + plan.
3. **Close.** A `regression-test` for the *specific failure mode* (proven RED on the pre-fix code), then `verification-before-completion`, then `finishing-a-development-branch`.

## You have now

Fixed the bug at its root — with a regression test that fails without the fix — rather than patching over the symptom.
