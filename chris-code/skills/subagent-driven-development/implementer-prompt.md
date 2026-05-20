# Implementer Subagent Prompt Template

Use this template when dispatching an implementer subagent. Prefer dispatching a `*-coder` agent by scope match — use this generic template only as a fallback when no specialized coder agent matches.

```
Agent tool:
  subagent_type: [matched *-coder agent, or "general-purpose"]
  model: [haiku|sonnet|opus per complexity]
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N: [task name]

    ## Task Description

    [FULL TEXT of task from plan — paste it here, don't make subagent read the file]

    ## Context

    [Scene-setting: where this fits, dependencies, architectural context]

    ## Before You Begin

    If anything about the requirements, approach, or dependencies is unclear — ask now.
    It is always OK to pause and clarify. Don't guess.

    ## Your Job

    1. Implement exactly what the task specifies
    2. Write tests (following TDD if task says to)
    3. Verify implementation works
    4. Self-review against your embedded checklist
    5. Report back

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

    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    - What you implemented
    - What you tested and results
    - Files changed
    - Self-review findings (if any)
    - Concerns or issues

    **Do not commit or push.** The orchestrator handles staging, review, and commit.
```
