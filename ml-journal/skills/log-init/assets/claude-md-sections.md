## Journal — Consultation Before Planning

Before drafting any non-trivial plan, consult the journal:
1. `/log-list issue`: open (unresolved) issues, the active blockers
2. `/log-list decision` for the last 7 days: recent decisions that constrain the approach

When a plan step is informed by a journal entry, cite the short ID inline (e.g. `[→ issue 71af7634]`). A `decision` entry is a resolved constraint, so read the full entry (`/log-list` with its ID) before re-opening it.

## Journal — Committing

The word **"commit"** means the **ml-journal `/log-commit` skill** — not bare `git commit`, not any other commit helper. The skill stages files, synthesizes a commit message, creates the commit, and writes a `git` journal entry in one step. Never use a different commit path in this project.

## Journal — Proactive Logging

When `.project-log/journal.jsonl` exists, propose logging at natural pauses — not mid-investigation. Always ask first; full draft only after user confirms.

**Auto-propose these types:**

| Pattern | Type | When |
|---------|------|------|
| User confirms a direction | `decision` | After "I agree", "let's do X", "go with that" |
| Unexpected finding | `discovery` | When exploration changes understanding or approach |
| Bug/inconsistency found | `issue` | After identifying and explaining a problem |
| Bug fixed and verified | `resolution` | After fix confirmed working |
| Root cause understood | `lesson` | After explaining *why* something broke — ask "should I log this as a lesson?" |
| Results interpreted | `experiment` | When verdict is clear |
| Major phase or block of work completes | `summary` | After finishing an experiment version, resolving a cluster of issues, or wrapping a multi-step investigation |

**Do not auto-propose:** `/checkpoint`, `/resume`, `/log-commit`, `/research-note`, `/research-report`, read skills, `hypothesis`, `post_mortem`, `memo`.

**Rules:** One proposal per event. Don't re-propose if declined. Chain issue→resolution→lesson at completion, not as three interruptions.
