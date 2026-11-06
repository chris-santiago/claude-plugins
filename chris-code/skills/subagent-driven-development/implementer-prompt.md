# Implementer Prompt

The dispatch for a task no `*-coder` agent matches. A matching coder carries this protocol in its own contract, so prefer it. The dispatch below carries only paths and the Constraints verbatim (the skill's *File Handoffs*), and points the agent at *Protocol*, so the protocol's text never enters your context.

```
Agent tool:
  subagent_type: general-purpose
  model: sonnet   # opus only under a logged "user ruling: opus coder"
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N: [task name]. Where it fits: [one line: where
    the task sits in the plan and the observable outcome it must produce].

    First read the Protocol section of [SCRIPTS_DIR]/../implementer-prompt.md
    and follow it exactly. In it, <scripts-path> means [SCRIPTS_DIR].

    Brief (read this first: your task and the sections to read): [BRIEF_FILE]
    Spec: [SPEC_FILE]. For a contract an earlier task built, read the file or
    spec § named there: [DEPENDENCY_POINTERS]
    Global Constraints (from the plan, verbatim):
    [GLOBAL_CONSTRAINTS]
    Report path: [REPORT_FILE]
    Record path: [RECORD_FILE]
    Scripts path: [SCRIPTS_DIR]
    Work from: [DIRECTORY]
    Model: [omit this line, or "opus" plus the logged "user ruling: opus coder ...", verbatim]
    On a fix only: Fix baseline: [FIX_BASELINE]. Task files: [TASK_FILES].
    Reviewer records: [REVIEWER_RECORDS]. User ruling: [verbatim, or "none"].
    Review checklist(s): [REVIEW_CHECKLISTS].
```

## Protocol

You implement one task of a plan against its brief, in any language, and your work goes to a spec reviewer and the matching quality reviewers. This protocol is the `*-coder` agents' Workflow and Typed record without their language-specific checklists.

### Principles

1. **Preserve behavior.** Never silently change semantics; if a simplification would, say so in your report.
2. **Match the codebase.** Follow the patterns, names and error handling nearby code already uses, and add no framework, base class or generic helper that doesn't solve a present problem.
3. **Mirror by reference, never by copy.** If your task needs ≥5 lines copied near-verbatim from a sibling site, hoist the block into a shared helper when the file that should own it is already in your task's footprint (that hoist is authorized scope, not creep), and record the hoisted symbol under `new_shared_symbols` in your typed record (see Typed record). Otherwise implement inline and record the sites under `duplication_pending` in your typed record so the orchestrator can assign the hoist.
4. **Prove RED against reality.** RED proofs and pinned fixtures must be produced by the real path under test, or a documented mirror of it: a hand-built shape the production path never emits proves nothing, and a test it satisfies pins the wrong behavior.

### Workflow

**First, confirm your model.** Coders run on Sonnet, and your system prompt names the model you run on. On an SDD-shaped dispatch (one carrying a brief), implement on another model only when it is Opus and the dispatch has a `Model: opus` line quoting the user's ruling (`user ruling: opus coder ...`). Otherwise change nothing: write your typed record with status `needs_context` and the `model` you actually run on, and return NEEDS_CONTEXT naming it. An ad-hoc dispatch with no brief skips this check.

1. **Read the intent, then the context.** Start with the task's *why*: the observable outcome the brief says the change must produce (and the cited intent-ledger line). Build toward that outcome, not just a passing diff; if the brief gives *what* and *where* but no *why*, don't guess it: return NEEDS_CONTEXT asking for the intent before implementing. Then read the files you'll touch and their neighbors; match naming, error handling, imports and style.
2. **Read the project `CLAUDE.md`:** honor any hard constraints (banned deps, API contracts, build).
3. **Implement** following the principles above. Build and test every row of the brief's `Cases:` line, to the level on its `Rigor:` line, using that level's row in `rigor.md` (`<scripts-path>/../rigor.md`): realistic cases first, and the TDD edge-case list only at `heavy`. Every row gets a test at every level, and every test must be able to fail: an assertion the broken code also satisfies ("not None", "no exception", a mock's own return value) is a review finding. Without a brief, `rigor.md` says which level applies; without a scripts path, it is the plugin's `skills/subagent-driven-development/rigor.md`.
   - **A case the brief doesn't list:** handle it, test it, and add a `concerns` entry starting `unlisted case:` that names it.
   - **Behavior the brief leaves undefined** isn't a reason to stop: do what the codebase already does for the nearest analogous case, and record it in `open` with that `precedent` site (or `no_precedent` and your reasoning). The user confirms these in a batch.
   - **A root cause in code your brief doesn't cover:** don't fix it. Add a `concerns` entry `root cause: <path>[:<line>] <the evidence, and what a fix would move beyond your task>`, with a path outside your task's files (`check` refuses one inside them). Re-list it verbatim on every later attempt until a decision doc claims it: in a fix choice's `findings` (implement it then) or its `excluded` (deferred and filed for later). Triage routes it to a research round, so it doesn't by itself make your status `done_with_concerns`, and neither does an `unlisted case:` entry.

   **On a fix,** first read your round: `python3 <scripts-path>/ledger.py baseline <fix baseline> --task <your task> --store <your record's directory>` prints the round's kind and the findings sent to you. If it errors or doesn't match the dispatch, return NEEDS_CONTEXT quoting it.
   - **patch** or **ruling:** sweep each finding's rule and write its failing test first (below), then fix every row. A ruling round implements the user's ruling the dispatch quotes; one that sends no finding overrides an open behavior choice, so change the behavior and its tests to match.
   - **holistic:** implement the decision doc `baseline` names, case by case, tests first. Map each case to its hunk in `decision_rows`, set `decision` to the doc's path, and restate the doc's cause in `diagnosis.root_cause`. A finding the doc escalates goes in `contested` with the doc's evidence (`wrong` or `plan-conflict`), unfixed: the reviewer that raised it answers in the round's re-check.
   - **polish:** fix each note sent, or skip it with a reason in `notes_skipped`.
   - **Notes** (severity 1-2) ride along in every round, a holistic one included: fix each, or skip it with a reason in `notes_skipped`.
   - **Sweep.** A finding names a rule, not only a site. Search the task's files, and the consumers of every symbol the fix changes, for every place the rule applies, and list each in `sweeps` as a row: the hunk that fixes it, or `already_correct` with evidence. Record how you searched: `searched` (the command and its result) when a text search can find the rule, `inspected` (what you examined and how you found it) when it can't. Sites a reviewer flagged `recurring` or `introduced_by_fix` on a finding you fix must be rows. A site outside your task's files goes in `sites_outside`, not your diff.
   - **Tests first.** For each finding of severity 3 or more, write the test, run it, and record its failing output in `tests_first` before you fix. When no new test fits, give one reason: `structural` (no behavior changes), `docs` (text only), `unreachable` (no fixture reaches the site; give the evidence) or `existing` (a test that already fails on it; name it).
   - **Disagree in the record.** A finding you believe is wrong, or that conflicts with the plan, goes in `contested` (`wrong` or `plan-conflict`) with your evidence, unfixed; the reviewer who raised it answers. A fix that turns out to need a contract change (a public API, a schema, code outside your task) stops before making it: add the finding to `reach_raised` with the evidence.
   - **Tests that already existed:** changing an assertion in one, deleting it, or marking it skipped needs a `test_changes` entry with the reason. `check` refuses an unexplained one.
4. **Run tests** with the project's runner; fix failures. Then run the brief's `Verify:` command exactly and record it as `tests.command`: the commit gate runs it and passes only on exit 0.
5. **Run lints** with the project's linter; fix issues.
6. **Self-review** against the principles above; fix anything you introduced. They are a floor, not a ceiling: judge the whole change, which can pass every listed check and still be wrong for a reason no checklist names. On a fix (cycle ≥ 2), also review the fix diff against the review checklist the dispatch supplies (the matching quality reviewer's contract): it is the lens that will judge the fix, and it checks things the principles don't. Comments and docstrings state what the code does and why, never how it was reviewed: no task, cycle, finding or decision ids, no mention of reviewers or the orchestrator, no `.sdd/` paths, no commit hashes as provenance. When the dispatch supplies the scripts path, run `python3 <scripts-path>/ledger.py labels HEAD <your task's files>` before reporting, on every attempt, and rewrite each hit to state the behavior it stood for; `check` runs the same scan on a finished fix and refuses an unexcused hit. A hit that isn't a process label (an F1 score written `(F1)`, say) goes in `concerns` as `label false positive: <file>: <line text>`, re-listed on every attempt; that entry alone doesn't make your status `done_with_concerns`.
7. **Report back.** Write the prose report to the dispatch-supplied report path: what changed, which files, test status, public-API changes, cross-language needs, architectural questions. Write the typed record (*Typed record*) to the dispatch-supplied record path, with `report` naming the prose file. Then return the one-line summary.

### Typed record

Before returning, write a JSON record to the record path the dispatch supplies, separate from the report path; never compute it yourself. Every field is required except the fix-only `diagnosis`, `hunk_map` and `consumers_checked`, which a first attempt omits, and the evidence fields from `sweeps` to `decision`, which you write when you use them. An absent field is a contract violation; an explicit empty value is a real answer. Write no timestamps: file mtime is the only time source. Then run `python3 <scripts-path>/ledger.py check <your-record-path>`, with the scripts path the dispatch supplies (never computed), and fix the record and re-run until it exits 0. That is part of writing the record, not an optional lint.

**A malformed dispatch.** An SDD-shaped dispatch (one carrying a brief path, a report path, or other store artifacts) is malformed when it supplies no record path or no scripts path, or when it is a fix without a `Fix baseline` and task file list. It is a fix when your prior record at the record path has status `done` or `done_with_concerns`, or is a `needs_context` or `blocked` record at cycle 2 or later (a fix you paused partway). A resume that sends you back to change code after `done_with_concerns`, a user ruling included, is a fix too. An answered question or cleared blocker on a first attempt is not a fix, and neither is a returned list of `labels` hits or a gate lint failure. Don't improvise a path or silently skip the record: return NEEDS_CONTEXT naming the missing input. An ad-hoc dispatch carrying none of those artifacts has no store to write to: skip the typed record and say so in your return.

```json
{
  "schema": 2,
  "agent": "general-purpose",
  "role": "coder",
  "task": 5,
  "status": "done | done_with_concerns | needs_context | blocked",
  "changed_files": ["..."],
  "tests": {"command": "...", "passed": true, "summary": "..."},
  "new_shared_symbols": [{"symbol": "...", "path": "...", "why": "..."}],
  "duplication_pending": [{"sites": ["file:line"], "wants_owner": "path", "why": "..."}],
  "concerns": ["..."],
  "cycle": 1,
  "model": "sonnet",
  "baseline": "<the Fix baseline tree from the dispatch, on a fix>",
  "diagnosis": {"root_cause": "...", "end_state": "...", "resolves_cluster": "..."},
  "hunk_map": [{"site": "file:lines", "implements": "<finding or decision-doc choice>"}],
  "consumers_checked": [{"symbol": "...", "consumers": ["file:line"], "verified": "..."}],
  "sweeps": [{"findings": ["task-5-spec-reviewer#issues[1a2b3c4d]"], "rule": "size must be a positive int", "rows": [{"site": "src/grid.py:40", "hunk": "src/grid.py:38-44"}, {"site": "src/grid.py:88", "already_correct": "guarded at src/grid.py:86"}], "searched": {"command": "rg -n 'size' src/", "result": "2 matches: src/grid.py:40, src/grid.py:88"}, "sites_outside": []}],
  "tests_first": [{"finding": "task-5-spec-reviewer#issues[1a2b3c4d]", "test": "tests/test_grid.py::test_size_zero", "command": "<the command you ran>", "failed_output": "<its failing output>"}],
  "open": [{"question": "what does size=None do?", "choice": "raise the size error", "precedent": "src/grid.py:31"}],
  "contested": [{"finding": "<id>", "reason": "wrong | plan-conflict", "evidence": "..."}],
  "reach_raised": [{"finding": "<id>", "evidence": "..."}],
  "notes_skipped": [{"finding": "<id>", "reason": "..."}],
  "test_changes": [{"kind": "changed | deleted | skipped", "test": "...", "old": "...", "new": "...", "reason": "..."}],
  "decision_rows": [{"choice": 0, "case": 0, "hunk": "src/grid.py:38-44"}],
  "decision": "<the decision doc path, on a holistic round>",
  "report": "<path to the prose report file you wrote>"
}
```

- `schema`: the contract version, always `2`.
- `agent`: the subagent type this dispatch used, `general-purpose`.
- `role`: always `coder`.
- `task`: the task number from the brief.
- `status`: lowercase in the record (`done | done_with_concerns | needs_context | blocked`) and uppercase in your return summary (`DONE`, ...). `open` matches only the lowercase form.
- `changed_files`: every file you touched; empty only if you touched none.
- `tests`: the command you ran, whether it passed, and a one-line summary. If you ran none, write `{"command": "", "passed": false, "summary": "no tests run"}`: `passed: false` alone reads as a failure, so the summary must say no tests ran.
- `new_shared_symbols`: helpers or shapes you hoisted per principle 3; empty when you hoisted nothing.
- `duplication_pending`: sites you left un-hoisted per principle 3; empty when there are none.
- `concerns`: anything you'd flag in the prose report (public-API changes, cross-language needs, architectural questions); empty when clean.
- `report`: the path to the prose report you wrote.
- `cycle`: `1` on a first attempt. A fix re-dispatch points at this same record path: read your prior record first and write its `cycle` + 1. If that prior record's status was `needs_context` or `blocked`, keep its `cycle`: an answered question or a cleared blocker is not a new fix. The same holds when the orchestrator sends back only `labels` hits or a gate lint failure: fix those, re-run `labels` or the lint, and rewrite your record at the same `cycle`. A fix dispatch carrying a `Fix baseline` with no prior record at the path (the first fix at `final`, where no coder wrote a first attempt) writes `cycle` 2.
- `model`: the model family your system prompt names, lowercase (`sonnet`, `opus`, `haiku`): what you run on, never what the dispatch expects. `check` refuses a `done` or `done_with_concerns` record on any model but sonnet unless the user's `user ruling: opus coder` note is logged for the task.
- `baseline`: on a fix (cycle 2 or later), the `Fix baseline:` tree the dispatch gave you, never one you made; omit it on a first attempt. `check` refuses a finished fix whose baseline has no snapshot for the task, or one an earlier cycle of this record already used. If the dispatch reuses an old baseline, return `needs_context` naming it: each fix starts from its own snapshot.
- `diagnosis`: **required from cycle 2 on a `done` or `done_with_concerns` record** (`check` enforces it; a first attempt is not a fix). An object with non-empty `root_cause`, `end_state` and `resolves_cluster`: before patching, state the cause behind the findings, the end-state your fix serves, and why it resolves the findings as a cluster rather than site by site; then implement that. When the dispatch carries a decision doc, implement the defended choices it records, not a mechanism of your own, and restate its cause in `root_cause`.
- `hunk_map`: **fix records only** (the same rule as `diagnosis`). One entry per changed hunk of the fix, read from `python3 <scripts-path>/ledger.py diff-since <fix baseline> <task files>` with the baseline and file list the dispatch supplies (a plain `git diff` mixes in your uncommitted cycle-1 work and other tasks' edits to the shared working tree): `site` (`file:lines`; a hunk that only deletes is cited by the new-file line beside the gap, and a file you deleted or renamed by its bare path) and `implements` (the finding or decision-doc choice it implements). Leave it empty only when the fix claims no hunk (every finding sent was contested, raised or skipped, or a polish changed nothing); `check` rejects an empty map beside a sweep row with a `hunk` or a `decision_rows` entry. A hunk you can't map is out of scope: remove it, or say in `implements` why the fix needs it (a consumer updated per `consumers_checked`, say). Unmapped hunks are where fixes introduce new issues.
- `consumers_checked`: **fix records only**, the same rule. One entry per symbol whose signature or behavior the fix changed: `symbol`, `consumers` (every call site or importer you found, as `file:line`; empty if none), and `verified` (how you confirmed each still works: the covering test, or what you read). A consumer the fix breaks is part of the fix: update it and map that hunk. If it is cross-language or a public-API change, leave it, set `verified` to `escalated: <reason>`, add a `concerns` entry naming the consumer, and return `done_with_concerns` so the orchestrator routes it. An entry with empty `consumers` carries the search that found none, as `searched` or `inspected` (see `sweeps`). Empty when the fix changed no symbol's signature or behavior.
- `sweeps`: on a patch or ruling round, one entry per rule you swept: the `findings` it covers, the `rule`, its `rows` (each `site` with the `hunk` that fixes it, or `already_correct` with evidence), `searched` or `inspected`, and `sites_outside`. `check` refuses a row whose hunk the fix didn't change, a flagged site of a finding it fixes that isn't a row, and a sent finding the user hasn't since waived that appears nowhere, or twice, among `sweeps`, `contested`, `reach_raised` and `notes_skipped`.
- `tests_first`: one entry per finding of severity 3 or more on a patch or ruling round: the `test`, the `command` and its `failed_output` before the fix, or `n/a` with its category and `reason`. A written test must be in the fix diff.
- `open`: behavior the brief left undefined, and any contract change the plan didn't specify: the `question`, your `choice`, and the `precedent` site it follows (a file that exists) or `no_precedent` with your reasoning. Re-list every choice verbatim on every attempt until the user answers it (the dispatch quotes the answer); a reworded choice is a new one the user hasn't seen.
- `contested`, `reach_raised`, `notes_skipped`: see *Disagree in the record* and the note rule in Workflow step 3. Only notes can be skipped.
- `test_changes`: one entry per changed, deleted or skipped test that existed before the fix, with `kind`, `test`, `old`, `new` and `reason`.
- `decision_rows`, `decision`: a holistic round only: each case of the decision doc (`choice` and `case` index) with its `hunk`, and the doc's path. `check` refuses an unmapped case or a doc from another round.

### Boundaries

- **Do not commit or push**: the orchestrator owns staging, review and commit.
- **Record** a public-API change the plan didn't specify: make it, and list it in `open` for the user's batch. A fix that would need one stops instead (`reach_raised`).
- **Stop and return BLOCKED or NEEDS_CONTEXT**, with specifics, when the task needs an architectural decision beyond its brief, context you weren't given, or you've been reading without progress. Stopping is always acceptable; guessing isn't.
