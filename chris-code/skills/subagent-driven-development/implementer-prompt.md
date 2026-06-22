# Implementer Subagent Prompt Template

Use this template when dispatching an implementer subagent. Prefer dispatching a `*-coder` agent by scope match — use this generic template only as a fallback when no specialized coder agent matches.

All inputs are handed over as files (see the skill's **File Handoffs** section). Do **not** paste task text, prior-task summaries, or diffs into the dispatch — carry paths, plus the Constraints verbatim.

```
Agent tool:
  subagent_type: [matched *-coder agent, or "general-purpose"]
  model: [haiku|sonnet|opus per complexity]
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N: [task name]

    ## Where This Fits

    [One line: where this task sits in the plan and what depends on it.]

    ## Your Requirements

    Read this first — your task and the sections to read: [BRIEF_FILE]

    Spec: [SPEC_FILE]. Read the sections the brief references; that is where the
    requirements live. For a contract an earlier task built, read the file or
    spec § named there rather than guessing signatures: [DEPENDENCY_POINTERS]

    ## Global Constraints (from the plan, verbatim)

    [GLOBAL_CONSTRAINTS]

    ## Before You Begin

    If anything about the requirements, approach, or dependencies is unclear — ask now.
    It is always OK to pause and clarify. Don't guess.

    ## Your Job

    1. Implement exactly what the brief specifies
    2. Write tests (following TDD if the brief says to)
    3. Verify implementation works
    4. Self-review against your embedded checklist
    5. Write your full report to [REPORT_FILE], then return only the summary below

    Work from: [directory]

    ## Escalation

    It is always OK to stop and say "this is too hard for me."

    **STOP and escalate when:**
    - The task requires architectural decisions beyond your scope
    - You need context beyond what was provided
    - You feel uncertain about correctness
    - You've been reading files without making progress

    Report back with status BLOCKED or NEEDS_CONTEXT with specifics.

    ## Report Format

    Write the full report to [REPORT_FILE]:
    - What you implemented
    - What you tested and results
    - Files changed
    - Self-review findings (if any)
    - Concerns or issues

    Return to the orchestrator only: status (DONE | DONE_WITH_CONCERNS | BLOCKED |
    NEEDS_CONTEXT), the changed-file list, a one-line test summary, and any concerns.

    **Do not commit or push.** The orchestrator handles staging, review, and commit.
```
