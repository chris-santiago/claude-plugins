# Intent ledger: SDD per-task review-fix loop

Frozen 2026-11-04. Changes only by explicit user decision. Revised 2026-11-05 by the user's decision after a brainstorm grounded in a real run's store: statements 1, 3 and 4 amended, old 5 merged into 3, two statements added, and old 7 moved to the spec's removal table.

The ask, in the user's words: "WE NEED TO SIMPLIFY. We need to ask if something is ever going to be needed or an esoteric edge case. We need to triage reviewer issues better. We need to have coders check for OTHER cases of same issue, so they don't patch one only to get feedback on the same issue in another place. Think HOLISTIC"; "perhaps the number of cycles isn't important, but rather the severity of the issue ... IN WHICH CASE A COHERENT, HOLISTIC THOUGHT OUT CHANGE IS OF UTMOST IMPORTANCE"; and "I don't want to simplify just to simplify".

1. After a fix, a re-review rarely reports the same rule at another site in the task's code, because the fix lists every site of the rule and maps each to a change ("coders check for OTHER cases of same issue, so they don't patch one only to get feedback on the same issue in another place"). `stats` shows the recurring rate.
2. A finding that is both serious (S3+) and broad (it changes a contract, or code beyond the task) gets a coherent-change pass over the whole task instead of a patch, even on the first review ("a coherent, holistic thought out change is of utmost importance").
3. A minor finding never triggers the engine or a review cycle of its own ("a trivial finding like a doc string ... where engine would be wasted effort"). Nothing in the task's code is deferred without the user deciding: skipped notes, contract-reach nits, and sites outside the change reach the user in one batch at close, to fix, file, or ignore ("decision these at close (fix, file+defer, ignore, etc)").
4. No task goes through more than two fix rounds before the user rules. The user is asked at most once per stage, in one message where every item carries a recommendation, so a single reply can settle it ("i'm not sure i want to be interrupted 5 different times").
5. When a brief leaves behavior undefined, the coder's choice follows an existing pattern in the codebase, cites it, and reaches the user as a default in the stage's batch ("the coder must base 'reasonable behavior' on existing paradigms within the codebase (ie it should be coherent)").
6. A reviewer finding the coder shows to be wrong is settled by the reviewer or the user without a fix round spent on it, and a settled finding does not return unless the code changed.
7. `stats` shows, per task and round, which coder model made the fix and how many findings it closed and introduced ("do opus or sonnet coders introduce more errors with their fixes").

Relation to `2026-10-30-note-store-intent.md` statement 8: its two-fix cap is replaced by the bound in statement 4 here.
