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

    ## On a fix (cycle >= 2 only; omit this section on a first attempt)

    Fix baseline: [FIX_BASELINE]. Task files: [TASK_FILES].
    Reviewer records: [REVIEWER_RECORDS]. Decision doc: [DECISION_DOC or "none"].
    User ruling: [the logged ruling, verbatim, or "none"].
    Review checklist(s): [REVIEW_CHECKLISTS or "none" for an all-trivial batch].
    A fix dispatch missing the baseline or task files is malformed: return
    NEEDS_CONTEXT naming it.
    Before changing anything, run
    `python3 [SCRIPTS_DIR]/ledger.py baseline [FIX_BASELINE] --task <your task> --store <your record's directory>`.
    `decision: <path>` must be the decision doc above, at the cycle you're
    writing; implement its choices.
    `settled-by: cases` means every non-trivial finding only reports a case
    the brief's Cases: line lists; `settled-by: ruling` means this dispatch
    quotes the user's ruling. `trivial` and `unrecorded` need nothing more.
    If it errors or doesn't match this dispatch, return NEEDS_CONTEXT quoting it.

    ## Before You Begin

    If anything about the requirements, approach, or dependencies is unclear — ask now.
    It is always OK to pause and clarify. Don't guess.

    ## Your Job

    1. Implement exactly what the brief specifies
       (every case on its `Cases:` line, each with a test; on a fix,
       every input and site in each finding's class; report an unlisted
       case you handle in concerns as `unlisted case: ...`, which alone
       doesn't make your status DONE_WITH_CONCERNS; a root cause you
       trace to code the brief doesn't cover is not yours to fix: report
       it in concerns as `root cause: ...` with its evidence and reach,
       and return DONE_WITH_CONCERNS)
    2. Write tests (following TDD if the brief says to). RED proofs and pinned
       fixtures must be produced by the real path under test, or a documented
       mirror of it — a hand-built shape the production path never emits
       proves nothing
    3. Verify implementation works
    4. Self-review against your embedded checklist (on a fix, also against the quality
       reviewer checklist the dispatch supplies). Comments state behavior, never
       the review process: run `python3 [SCRIPTS_DIR]/ledger.py labels HEAD
       <your task's files>` on every attempt and rewrite each hit. A hit that isn't a
       process label goes in concerns as `label false positive: <file>: <line
       text>`, re-listed on every attempt; like `unlisted case:`, it alone
       doesn't make your status DONE_WITH_CONCERNS
    5. If you copied ≥5 lines near-verbatim from a sibling site, record the sites
       under `duplication_pending` in your typed record (hoist instead when the
       owning file is already in your task's footprint, and record the hoisted
       symbol under `new_shared_symbols`)
    6. Write your full report to [REPORT_FILE], write your typed record (see
       Typed record below) to [RECORD_FILE], then return only the summary below

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

    ## Typed record

    Write a JSON record to [RECORD_FILE] before returning — a separate absolute
    path from the report file, supplied by the dispatch; never compute it
    yourself. Every field is required (except the fix-only `diagnosis`,
    `hunk_map`, and `consumers_checked`, which a first attempt omits); an
    absent field is a contract violation, and an explicit empty value is a
    real answer, not an omission. No
    agent-written timestamps — file mtime is the only time source. After
    writing it, run `python3 [SCRIPTS_DIR]/ledger.py check [RECORD_FILE]` —
    the dispatch supplies [SCRIPTS_DIR], never compute it yourself — and if it
    errors, fix the record and re-run until it exits 0; fixing your own record
    until check passes is part of writing it, not an optional lint. If this
    dispatch reached you with no [RECORD_FILE] or no [SCRIPTS_DIR] filled in,
    the dispatch is malformed — do not improvise a path and do not silently
    skip the record: stop and return NEEDS_CONTEXT naming the missing input.

    {
      "schema": 1,
      "agent": "general-purpose",
      "role": "coder",
      "task": N,
      "status": "done | done_with_concerns | needs_context | blocked",
      "changed_files": ["..."],
      "tests": {"command": "...", "passed": true, "summary": "..."},
      "new_shared_symbols": [{"symbol": "...", "path": "...", "why": "..."}],
      "duplication_pending": [{"sites": ["file:line"], "wants_owner": "path", "why": "..."}],
      "concerns": ["..."],
      "cycle": 1,
      "diagnosis": {"root_cause": "...", "end_state": "...", "resolves_cluster": "..."},
      "hunk_map": [{"site": "file:lines", "implements": "<finding or decision-doc choice>"}],
      "consumers_checked": [{"symbol": "...", "consumers": ["file:line"], "verified": "..."}],
      "report": "[REPORT_FILE]"
    }

    - `schema` — contract version; always `1`.
    - `agent` — the subagent_type this dispatch used (typically `general-purpose`
      for this fallback template).
    - `role` — always `coder`.
    - `task` — task N from the brief.
    - `status` — the same four statuses as your return summary, but lowercase
      (`done | done_with_concerns | needs_context | blocked`, matching the
      block above) — the return summary stays uppercase (`DONE` etc.), the
      record never is; `open` matches on the lowercase form only.
    - `changed_files` — every file you touched; required, empty only if you
      truly touched none.
    - `tests` — the command you ran, whether it passed, and a one-line
      summary; if you ran none, write `{"command": "", "passed": false,
      "summary": "no tests run"}` — `summary` must say so explicitly, since
      `passed: false` alone reads as a failure, not as "not run."
    - `new_shared_symbols` — helpers or shapes you hoisted per Job step 5;
      empty list when you hoisted nothing.
    - `duplication_pending` — sites you left un-hoisted per Job step 5,
      replacing the old prose `DUPLICATION-PENDING:` sentinel; empty list
      when there is none.
    - `concerns` — anything you'd flag in the prose report; empty list when
      clean.
    - `report` — [REPORT_FILE], so the orchestrator can find your reasoning.
    - `cycle` — 1 on a first attempt. A fix re-dispatch points at this same
      record path: read your own prior record first and write its cycle + 1.
      Exception: if that prior record's status was needs_context or
      blocked, keep its cycle (an answered question is not a new fix).
      Keep it too when the orchestrator sends back only `labels` hits:
      that is the same attempt, not a fix.
    - `diagnosis` — required from cycle 2 on a done or done_with_concerns
      record (`check` enforces it): an object
      with non-empty `root_cause`, `end_state`, and `resolves_cluster`.
      Before patching anything, state the cause behind the findings, the
      end-state your fix serves, and why the fix resolves the findings as a
      cluster rather than site-by-site — then implement that. List the
      consumers of whatever you change in `consumers_checked`. Not
      required at cycle 1; a first attempt is not a fix.
      When the fix dispatch carries a decision doc path, implement the
      defended choices it records, not a mechanism of your own; your
      root_cause restates the doc's.
    - `hunk_map` — fix records only (cycle >= 2, done or done_with_concerns):
      one entry per changed hunk (at least one), read from
      `python3 [SCRIPTS_DIR]/ledger.py diff-since [FIX_BASELINE] [TASK_FILES]`
      (cycle-1 work is uncommitted, so plain git diff mixes it in):
      `site` (file:lines) and `implements` (the finding or decision-doc
      choice). Remove a hunk you can't map, or say why the fix needs it.
    - `consumers_checked` — fix records only: per symbol whose signature
      or behavior the fix changed, `symbol`, `consumers` (file:line list,
      empty if none), and `verified` (how each was confirmed). Update a
      consumer the fix breaks and map that hunk; a cross-language or
      public-API consumer gets `verified: escalated: <reason>`, a concerns
      entry, and DONE_WITH_CONCERNS. Empty list when the fix
      changed no symbol's signature or behavior.

    Return to the orchestrator only: status (DONE | DONE_WITH_CONCERNS | BLOCKED |
    NEEDS_CONTEXT), the changed-file list, a one-line test summary, and any concerns.

    **Do not commit or push.** The orchestrator handles staging, review, and commit.
```
