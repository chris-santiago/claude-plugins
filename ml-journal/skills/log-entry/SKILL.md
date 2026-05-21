---
name: log-entry
description: Log a typed entry to the project journal. Use when the user says "log this", "record this", "log this issue / decision / discovery / experiment / hypothesis / resolution / post mortem / summary", or any phrasing indicating something from the conversation should be captured. Infers entry type from context. Handles all entry types except checkpoint (use /checkpoint) and git commits (use /journal-commit).
---

## Step 0: Check journal exists

Run `git rev-parse --show-toplevel` to find repo root.

Check that `<repo-root>/.project-log/journal.jsonl` exists. If not, tell the user to run `/journal-init` first and stop.

## Step 1: Infer entry type

Determine type from conversation context using these heuristics:

| Signal | Type |
|---|---|
| "we found that", "turns out", "discovered", "realized" | `discovery` |
| "we learned", "lesson", "takeaway", "going forward we should", "next time" | `lesson` |
| "broken", "failing", "bug", "error", "problem" | `issue` |
| "we decided", "going with", "chose", "agreed on" | `decision` |
| "hypothesis", "we think", "expecting", "if we do X then Y" | `hypothesis` |
| "the experiment showed", "result was", "it worked / didn't work" | `experiment` |
| "fixed", "resolved", "solved" | `resolution` |
| "what went wrong", "post mortem", "retrospective" | `post_mortem` |
| "end of session", "wrapping up", "summary of today" | `summary` |
| "note this", "remember", "memo", "jot this down", "quick note", "don't forget" | `memo` |

State the inferred type before proceeding. If genuinely ambiguous, ask the user.

## Step 2: Extract field values

Extract relevant field values from the conversation. Do not invent details not present in the conversation.

**Field extraction by type:**

`issue` — description (what is wrong), severity (low/moderate/high/critical — infer from impact), tags (comma-separated topics), context (what was happening when discovered)

`resolution` — description (what was done), linked_issue_id (if there is a prior issue entry this resolves — ask or search recent entries), approach (how it was fixed), evidence (what confirmed the fix worked — test output, metric, observation)

`decision` — description (what was decided), rationale (why), alternatives (what else was considered), implications (downstream effects or constraints this decision creates — optional), linked_issue_id (if this decision directly addresses an open issue — optional), linked_id (if this supersedes or is related to a prior decision — optional)

`lesson` — description (the lesson), context (what situation surfaced it), applies_to (what area/component/workflow it affects), linked_id (any related entry — optional)

`discovery` — description (what was learned), implications (what this means for the work), source (how it was found — experiment, reading, debugging, etc.), linked_issue_id (if this discovery resolves or complicates an open issue — optional)

`hypothesis` — description (the hypothesis), expected_result (what you expect to happen), metric (how you'll measure it), linked_issue_id (if this hypothesis was raised to address an open issue — optional)

`experiment` — description (what was run), verdict (confirmed/refuted/inconclusive), metric (what was measured), result (what the numbers showed), linked_hypothesis_id (if applicable), linked_issue_id (if this experiment addresses an open issue — optional)

`post_mortem` — description (brief summary), what_failed (the failure), root_cause (why it happened), contributing_factors (what made it worse), lessons (what to do differently), linked_issue_id (**required** — create an issue entry first if one does not already exist), severity (low/minor/moderate/high/critical — infer from impact), scope (active = affected current results; future = gap for next run), remediation (specific actionable fix — name files, fields, scripts, plan sections; vague fixes are not fixes), detail (long-form investigation narrative with evidence, code references, tables, subsections — the full body that would have appeared in a POST_MORTEM.md entry)

`summary` — description (session overview), key_decisions (list of decisions made), open_threads (list of unresolved items)

`memo` — description (the note), detail (long-form body content — use when the note is more than a sentence), context (situational background — optional), tags (comma-separated topics — optional), linked_issue_id (if this memo is linked to an open issue — optional), linked_id (if linked to another entry — optional)

## Step 3: Confirm or run

**Confirm before logging** (show draft, ask `► Log this? (y/n)`):
- `decision`, `post_mortem`, `experiment`, `summary`, `discovery`, `hypothesis`

**Log directly** (no confirmation):
- `issue`, `resolution`, `lesson`, `memo`

Note: `git` entries are handled exclusively by `/journal-commit` (which always confirms). Do not pass `git` type through this skill.

Show proposed entry as a readable block before confirming, e.g.:
```
Type:        decision
Description: Use last hidden state pooling instead of mean pooling
Rationale:   Mean pooling destroys temporal ordering; last state captures sequence summary
Alternatives: Mean pooling, attention pooling
```

## Step 4: Construct and run command

Build the `journal_log.py` invocation with appropriate flags for the type and extracted fields. List fields (tags, key_decisions, open_threads) should be passed as comma-separated strings.

```bash
python3 <repo-root>/.project-log/journal_log.py \
  --type <type> \
  --description "..." \
  [--field "value"] ...
```

## Step 5: Surface result

Show the confirmation line from `journal_log.py` output (e.g., `Logged [issue] a3f2b1c0 at 2025-06-01 14:32Z`).

For `resolution` entries: note whether it was linked to a prior issue.
For `experiment` entries: note the verdict prominently.
