# Changelog

All notable changes to **chris-code** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Versions are markers in `plugin.json`; the project is shared by cloning, not by tagged GitHub releases.

This history was reconstructed retroactively from git (development began 2026-05-20). chris-code is a superset of [obra/superpowers](https://github.com/obra/superpowers): forked from **v5.1.0**, then hardened with selective **v6.0.0** backports.

## [Unreleased]

## [0.14.4] - 2026-11-06

### Fixed
- **A deleted, renamed or binary file counts as changed.** Such a file has no new-side lines in the diff, so `changed_lines` recorded nothing and `check` refused any row citing it, even by its bare path. It now marks the whole file, and any site in it touches the diff: a deleted file, a binary change, a rename's old name, and its new name when the rename changed no line (an edited rename keeps its line marks). A test the fix "wrote first" in a file it deleted is still refused. The fix diff also detects renames whatever the user's `diff.renames` setting says, so a copy no longer shows up with no lines.
- **Only a note can be skipped, in every round.** 0.14.2 exempted skipped findings from listing their flagged sites as rows, but a holistic round never checked that a skipped finding was a note, so an S3+ could be skipped past its flagged sites and filed as a follow-up. `check` now refuses a skipped non-note in any round, and a finding the fix also sweeps keeps its flagged rows even if it's contested.
- **A mid-round waiver reaches the decision doc.** In a holistic round, `check` still asked the coder to contest a waived finding the decision escalates, and to map a fix choice whose findings were all waived. Both now drop out with the waiver.
- **The coders' protocol says how to cite a deletion:** by the new-file line beside the gap, or a deleted or renamed file by its bare path.

## [0.14.3] - 2026-11-06

### Fixed
- **A deleted line counts as changed.** `ledger.py`'s record of which lines a diff changed missed any deletion with code above and below it, because git's default diff surrounds it with context lines and only a deletion with none was counted. `check` then refused a fix whose sweep row or decision row claimed a hunk at a line it deleted, and a reviewer's `reopens` at a deleted site. A deletion that nothing replaces now marks the lines on each side of the gap it left, with or without context; an edited line still marks only itself.

## [0.14.2] - 2026-11-05

### Fixed
- **A finding the user waives after triage sent it drops out of the round.** `check` still counted it among the round's findings, so the coder had to cover it, and the only way to do that was to contest a finding nobody disputed. `check` now leaves out a finding with a `user ruling:` resolution, and the SDD skill tells the orchestrator to pass the waiver on to the coder.
- **Flagged sites are rows only for findings the fix fixes.** `check` asked for every site a reviewer flagged `recurring` or `introduced_by_fix` to appear as a sweep row, even for a finding the coder contested, raised to contract reach or skipped as a note. None of those has a hunk to show, so coders padded their sweeps with `already_correct` rows saying the site wasn't fixed. The rule now covers only the findings the fix fixes, and the coders' protocol says so.

## [0.14.1] - 2026-11-05

### Fixed
- **The superpowers comparison and the docs describe `claim-checker` as it works now.** Since 0.11.0 it only settles a spec reviewer's `cannot_verify` item, but the comparison deck, *The assurance model*, *Execution mechanics*, *Context and dispatch* and the agents reference still had it grounding any judgment-shaped finding, and the deck still told reviewers to flag their lossiness. They now say findings route by their tags through `triage` and contests, and `claim-checker` handles only `cannot_verify`. The deck also matches the README on the per-task commit gate (labels, lint and the task's verify command, scripted) and on review-lite, which runs over the whole change rather than before every commit.
- **The visual decks describe the 0.11 fix loop.** The overview and from-superpowers Marp decks and the intro deck with its speaker notes still showed the orchestrator's trivial/non-trivial triage, a decision doc for every non-trivial finding, recurrence forcing a new mechanism, and review-lite as a per-commit gate. They now show tagged findings routed by `triage` (notes, patch and holistic rounds, at most two), contests, the scripted commit gate, and review-lite over the whole change. The intro deck's agent-ratio, two-chains and dispatch figures are regenerated, and the Marp HTML and PDF exports are re-rendered.
- **The visual guide catches up with 0.14.0.** The published guide (`docs/slides/chris-code-guide.html`) now describes `claim-checker` as above, triage taking the fix baseline, and `ledger.py commit` as the one commit command. The copy under `assets/decks/` had fallen behind at 0.6.0 and is now identical to it.

## [0.14.0] - 2026-11-05 — SDD's mechanical rules move into the scripts

Several of SDD's rules were deterministic decisions the orchestrator carried out by reading prose: take a snapshot after triage and re-send it on a resume, recognize a stale store or a close-gate remediation run from the log, stage exactly the task's files, gate, commit and append the completion, and build a dozen record and report names by convention. Each was a place to slip. They are now commands, and the prose that described them is gone.

### Added
- **`ledger.py commit`.** One command takes a ready task from staging to a completed commit: the `ready` blockers, a check that the coder changed no file outside the task's recorded footprint, staging exactly that footprint, the gate, `git commit` of those files alone with the orchestrator's message verbatim, and the completion entry. It stops at the first failure and touches nothing before the commit; it never undoes one. Files another task staged stay staged and out of the commit. At `final`, a finished whole-change fix is committed for its re-check without completing the scope, and at `done` the command gates HEAD with the full suite and completes `final`. A file the gate's own commands rewrite (a formatter) is never committed ungated, the message is kept verbatim whatever git's cleanup setting, and paths with spaces or non-ASCII names are handled exactly.
- **`ledger.py path`.** Prints every record, report and brief path by scope (a task, the whole-change gate, a close round's fix, a ruled fix, or the close-round gates' reports), so no skill builds a name.
- **A verdict on the store.** `task_brief.py` records each plan it builds briefs from, and `run-state --plan` opens with `fresh`, `resume`, `remediation`, `finished`, `foreign` or `ambiguous` and the next action. The stale-store and remediation-recognition rules are now this table, in a new `store_state.py` of pure functions.

### Changed
- **Triage takes the fix baseline.** A fix step snapshots the working tree in the same step and prints `Fix baseline` and `Task files` for the dispatch. Re-running `triage` while that fix is unfinished reprints it instead of starting another round, which also closes a gap where a paused coder's rewritten record could cost the task a round.
- **`gate` stages the footprint itself**, and at `final` the footprint adds the files the whole-change fix's coder changed, plus any `stage --task final` adds. `commit` skips a gate only when it already passed on the same files, staged the same way, with the same commands.
- **Report names are uniform**: `<scope>-<agent>-report.md` for coders and reviewers, and `gate-<agent>-report.md` for the design, intent and mutation reports, which keep one path across close rounds. `clear` removes the new names and the old ones.
- **A remediation note's fields are checked** before `run-state` repeats them as instructions: the plan must be a plain `.md` path and the front-end a known skill.
- SDD, verification-before-completion, executing-plans and the reference docs call these commands instead of describing the steps.

## [0.13.0] - 2026-11-05 — Leaner contracts, verdicts by path

The biggest skills and agent contracts had grown by accretion: shared protocol text was copied across files and drifted, rules were restated in several places, and every per-task reviewer returned its full verdict into the orchestrator's context although triage reads only the typed record. This release cuts the words without dropping a rule, sends reviewer verdicts by path, retires a field nothing reads, and adds a test that keeps the shared copies identical.

### Changed
- **Shorter contracts, same rules.** SDD, verification, remediating-issues, coherent-change and the three coders are about 12% shorter with every rule kept. remediating-issues now points at coherent-change for the discipline they share instead of restating it.
- **Reviewers return one line.** The spec and quality reviewers write their verdict to a report path the dispatch supplies (`$STORE/task-N-<agent-name>-review.md`) and return only the verdict word and that path, as the design reviewers already did. Triage reads their typed records, so the verdict's prose no longer fills the orchestrator's context. Standalone, they still return the review inline.
- **Review-lite writes only its record inside a run.** Its markdown verdict file under `.claude/output/review-lite/` is now for the standalone pre-commit gate only, and a finding's `claim` carries the suggested fix.
- **The implementer prompt is a short dispatch.** It points a general-purpose agent at the file's *Protocol* section, the coders' own Workflow and Typed record made language-neutral, instead of pasting a separate, drifted copy into every dispatch.
- **SDD's ⚠️ handling is one section, and its Red Flags keep only the rules a long run's pressure pushes on.** claim-checker's contract now agrees with SDD that it gets no verdict text.

### Removed
- **`lossiness`.** Reviewers no longer write a lossiness line or field. Since 0.11.0 nothing consumed it.
- **Review-lite's `verdict_path`** record field.

### Added
- **A shared-protocol drift test.** The coders and the implementer Protocol, the quality reviewers, and the parts the spec reviewer and review-lite share are generated from one template; `test_shared_protocol.py` fails when an edit reaches some copies and not others.

## [0.12.0] - 2026-11-05 — Test rigor scales with the project

Every project got the same testing depth: plans listed esoteric boundaries, reviewers rated any missing boundary case S3, and the mutation tester gated on every covered survivor. On a large Python and Rust codebase that depth earns its cost. On a small app it meant fix rounds over inputs no caller produces, and mutation runs out of proportion to the code. Real runs also showed that the costly misses were tests that couldn't fail, not missing edge cases. This release resolves a rigor level per project and scales plans, tests, reviews and mutation to it, while holding the line on tests that can't fail at every level.

### Added
- **`rigor.py` and three levels.** `light`, `standard` and `heavy` resolve from the repo. Counted source lines set the base: under 5,000 is `light`, 5,000 to 30,000 is `standard`, and over 30,000 is `heavy`. Tests, vendored code, generated code and tracked symlinks don't count. A language binding raises the level to at least `standard`, and numeric or ML dependencies raise it one step, capped at `heavy`. A `Test rigor: <level>` line in the repo-root `CLAUDE.md` overrides the heuristic, and a value that isn't a level is an error. The level prints with its reasons, and nothing is stored.
- **`rigor.md`, the per-role table.** One reference defines what each level means for plan rows, coder tests, a reviewer's severity for a missing case, mutation breaks, mutation gating and the mutation model. Every consuming contract points to it, and a drift test checks they still do.
- **Task raises.** A plan task's `- Rigor: standard|heavy` line raises that task above the project level. `task_brief.py` refuses a line that would lower it or names no level.

### Changed
- **Briefs state the level.** Every brief opens with `Rigor: <level> (<reasons>)`, and the coder and every reviewer of the task apply it.
- **Reviewers rate missing cases by level.** Below `heavy`, a missing case no `Cases:` row names and no realistic caller hits is S1-S2, so it doesn't start a fix round. A test that can't fail is S3 at every level, and a missed `Cases:` row stays S3 or higher.
- **Mutation scales per file.** Verification resolves the project level and the files raised tasks touched (`rigor.py --files`), and passes them with the plan path. At `light` the tester makes at most two breaks per changed function and gates only on behavior a `Cases:` row names (or, without a plan, on functions the change's tests call directly), and it runs on sonnet when no file is raised above `light`. `heavy` keeps the previous behavior. The report states the level applied to each file.
- **Planning and TDD start realistic.** lean-plan resolves the level before writing rows and checks them against it in self-review. TDD's edge-case list is now the `heavy` list, preceded by "realistic first".

## [0.11.0] - 2026-11-05 — The per-task loop routes by severity and reach

SDD's per-task loop routed reviewer findings on the orchestrator's trivial/non-trivial call. Minor items went down the heavy route, every non-trivial finding got its own decision doc, and a two-fix counter with route flags decided when to stop. In a long real run that came to 2.39 fix cycles and about two user rulings per task, and 45% of later findings were introduced by the previous fix, most of them by a decision doc's choice. This release replaces the routing with a script-computed triage over findings the reviewers tag, holds each fix to the evidence its round requires, and moves plan gaps up front.

### Added
- **Tagged findings and `ledger.py triage`.** Every reviewer finding carries `severity`, `reach` (`local`, `class`, `contract`), `rule`, and `sites`. `triage` turns them into the task's next step: S1-S2 findings are notes, fixed or skipped by the coder and never re-reviewed; S1-S2 contract findings are deferred; S3+ local or class findings get a patch round; S3+ contract findings and a coder's `root cause:` concern get a holistic round, where an opus research agent writes one task-wide decision doc first. A task gets at most two patch or holistic rounds, then waits for the user. Re-checks go only to the reviewers triage names. Running `triage` again with nothing changed reprints the step.
- **Fix evidence in the coder record, enforced by `check`.** Sweeps list every site of a finding's rule as a row mapped to the hunk that fixes it, with the search behind them. S3+ findings get a failing test first (or a named reason it can't have one). A fix covers each finding it was sent exactly once, and its rows must touch lines it really changed. Edits, deletions, and skips of tests that already existed need a reason. A holistic fix maps every case of its decision doc to a hunk.
- **Contests.** A coder that believes a finding is wrong, or conflicts with the plan, contests it with evidence instead of fixing it. The reviewer that raised it answers `concede` or `hold`, and a held finding goes to the user. A finding a task's decision doc escalates goes through the same contest instead of waiting on the user directly. A settled finding can come back only with `reopens` and a site in code changed since.
- **Open behavior choices.** When a brief leaves behavior undefined, or the work needs a contract change the plan didn't specify, the coder follows the nearest precedent in the codebase and records the choice, which the user confirms or overrides. An override starts a ruling round that the spec reviewer re-checks.
- **The stage batch.** A task with open work after two rounds, a held contest, or an open choice parks without committing. Once the stage has nothing in flight, the user gets one message covering every parked item, each with a recommendation. A `root cause:` concern a decision doc excludes is deferred as a follow-up, and the user can waive one the task can't wait for.
- **`ledger.py gate` and `ledger.py ready`.** `gate` runs the process-label scan, lint, and the task's `Verify:` command on the staged task files, each passing only on exit 0, and records what it checked. `ready` lists everything that stops a commit. `complete` re-runs `ready` and refuses a commit that doesn't match the passing gate.
- **Decision docs give every case a site and a test**, list the couplings the choice touches (each also a case), and record the premise the choice rests on.
- **Follow-up rules and the close batch.** `note --kind follow-up --rule` groups follow-ups; `triage` files the loop's own deferrals with their rule. The completion report groups open follow-ups by rule for the user to fix, file, or ignore in one batch.
- **Round telemetry.** `stats` prints each round's kind, the coder model, and the findings it closed, saw survive, and saw a fix introduce; `run-state` shows each task's rounds and what is parked.

### Changed
- **Record schema 2.** Records from earlier releases are refused with a message: finish that run on the release that started it, or `ledger.py clear` the store.
- **Plans decide behavior as rows.** A `Cases:` row states its result (`size=0 → ValueError`); behavior the planner can't decide is an `open:` row the user answers before the build; a `Verify:` line is a command where exit 0 means pass. `task_brief.py` refuses a plan that breaks any of these, so a plan written for an earlier release may need its rows rewritten.
- **The per-task commit gate is scripted.** Per-task review-lite is gone; review-lite runs only at the whole-change gate, under the same triage. The quality reviewers took over its CLAUDE.md and public-sentinel checks.
- **executing-plans is the light path for small work:** briefs, quality reviewers, at most two fix rounds, and the same commit gate, with no triage loop (`ready --light`, `complete --light`).
- **`snapshot` takes only a task and a label**, and `baseline` prints the round a fix starts.

### Removed
- The orchestrator's trivial/non-trivial triage, the fix counter and its two-fix cap, the snapshot route flags and the reroute check, and a decision doc for every non-trivial finding. The round structure bounds fixes, and the reviewers' tags route them.
- `claim-checker` on reviewer findings and coder concerns. Contests settle between coder and reviewer; `claim-checker` stays for `cannot_verify` items.
- Re-review by every reviewer after every fix.

## [0.10.1] - 2026-11-03

### Changed
- **The quality reviewers run outside SDD.** `python-quality-reviewer`, `rust-quality-reviewer` and `pytorch-quality-reviewer` refused any dispatch without a record path and a scripts path, so a review dispatched on its own got a refusal instead of a verdict. A dispatch with no record path and no store artifacts now runs standalone: the reviewer reviews the files or diff it's given, skips the record, and returns its review inline. A dispatch that carries store artifacts but lacks either path is still refused as malformed.

## [0.10.0] - 2026-10-30 — Run notes in the store

A long SDD run's cross-task knowledge had no durable home, so an orchestrator improvised a free-form notes file. It grew without bound, nothing in it was ever marked done, and it dropped items: a standing test recipe fell out of later briefs twice, notes filed after their target's brief was built reached the coder only by luck, and changelog debts had no owner. The same run showed the fix cap never firing: fixes reused an earlier cycle's snapshot or skipped one, and fixes were logged as trivial right after reviewers flagged regressions, so `fix-count` stayed at two through seven cycles. This release moves that knowledge into typed ledger entries the briefs, gates and reports read, and makes the fix count rest on evidence.

### Added
- **Typed run notes.** `ledger.py note` files seven kinds: a task-note for one later task, a run-note for every task, a disclosure owed to the docs, a question for the user, a follow-up, a disposition (a call the orchestrator made alone), and a checkpoint. Ids are content-derived, and a duplicate is refused. `resolve` closes a note with a reason: a disclosure says where it landed, a question takes `user ruling: ...`.
- **Delivery tracking.** `task_brief.py` embeds a task's task-notes, the active run-notes and the disclosures it owes, and logs the delivery. `ledger.py notes --task N` lists what a task must receive; `--deliver` records a session delivering them (for `executing-plans`), and `--waive ID --reason` records one that doesn't apply.
- **`run-state` and `report`.** `run-state` shows where a run stands from the store alone: the stage map, task states, fix counts, notes owed, open disclosures and questions, agent handles, and the latest checkpoint. `report` lists what the completion report needs: rulings, follow-ups, the coders' unlisted cases, dispositions and waivers, and disclosures.
- **The stage map and agent handles.** `ledger.py stage` records each task's stage and footprint and refuses a path another unfinished task in the same stage claims. `ledger.py handle` records the agent behind a task's role, so the original coder can be continued after a compaction.
- **A run scope for rulings.** `append --type progress --task run` logs a ruling about the whole run.
- **A store lock.** Every command that writes the store holds an exclusive lock on `<store>/.lock` while it reads, checks and writes.
- **A ledger command reference** in the docs.

### Changed
- **Completion and the close wait on owed notes.** `append --type complete` refuses a task with an undelivered note or an open disclosure or question it owns. `close-round` refuses while any disclosure or question is open, or a task-note waits on a task that never completed.
- **`task_brief.py` no longer takes `--note`.** Cross-task notes reach a brief only through the store.
- **`clear` refuses to drop open follow-ups, disclosures or questions** unless `--discard-open` says the user confirmed the loss.
- **Each fix owns its snapshot.** A finished fix record carries `baseline`, the `Fix baseline:` tree from its dispatch. `check` refuses one with no snapshot for the task, or one an earlier cycle of the same record already used. Records written before this still load.
- **A flagged fix is non-trivial.** While a reviewer record of the task flags `recurring` or `introduced_by_fix`, `snapshot` refuses a trivial fix and one settled by the brief's `Cases:` line, so the fix goes through a decision or the user's ruling and counts toward the cap.
- **The skills use the store.** SDD gains a Run Notes section, records the stage map and handles, checkpoints before a pause, and never keeps cross-task state in a file of its own. `verification-before-completion` builds the completion report from `report` and settles close-owned questions and disclosures before a round. `executing-plans` takes each task's notes at its start. `finishing-a-development-branch` reports open follow-ups before removing the store. A blocked coder that needs more reasoning is offered to the user as an opus coder instead of being re-dispatched on a stronger model unasked.

## [0.9.1] - 2026-10-22

### Changed
- **The fix-cap escalation offers an opus coder.** Alongside the routes for the next fix (a fresh researched decision through `remediating-issues`, or a fix the user names), the briefing offers an opus coder with the reason the records give. It isn't a route: it combines with whichever route the user picks, and it's logged only when the user picks it. The user can still ask for one at any time.

## [0.9.0] - 2026-10-22 — Fixed models per role

An orchestrator choosing models per dispatch ran most coders on opus, on the table's "design judgment" row. Since 0.8.0 that judgment lives in the decision doc and the brief, so a coder implements choices already made. Each role now has a fixed model, and coders can't run above sonnet without the user's ruling.

### Changed
- **Models are pinned per role, with no orchestrator override.** Coders and the `*-review-lite` gates run on sonnet. The spec, quality, design and intent reviewers, `mutation-tester`, `bug-hunter` and the `remediating-issues` research agent run on opus. `claim-checker` stays on haiku. The lite gates and `bug-hunter` used to inherit the dispatch model. SDD's per-complexity model table is gone, and haiku is no longer a coder model.
- **An opus coder takes the user's ruling.** The user can rule an opus coder for a task, logged as `user ruling: opus coder ...`. The orchestrator then dispatches with `model: opus` and a `Model: opus` line quoting the ruling.

### Added
- **Coders check their own model first.** A coder reads its model from its system prompt. On anything but sonnet without the `Model: opus` line, it changes nothing and returns `needs_context`.
- **Coder records carry `model`.** `ledger.py check` requires it and refuses a `done` or `done_with_concerns` record on any model but sonnet, unless the opus ruling is logged for the task. Records written before this still load. `stats` shows each coder's model.

### Fixed
- **A task with an open escalation can't be completed.** An orchestrator could log the user's ruling as a progress note, which satisfies `--settled-by ruling` but leaves the escalation open, then complete the task anyway. The escalation then sat in `open` for the rest of the run. `ledger.py append --type complete` now refuses while any decision in the task's scope has an unresolved escalation, and it names the ids to `resolve` with the ruling. SDD's rule against completing such a task was already in prose; now it's enforced.

## [0.8.0] - 2026-10-09 — Decisions that were researched

An orchestrator could write a per-task decision doc itself instead of dispatching `remediating-issues`: little research, rejected options in one line each, and open questions left to the coder ("or equivalent"). SDD's instruction to dispatch the research agent was already explicit, but nothing enforced it, so this release moves the check out of the orchestrator's own prompt and into a script and a second agent.

### Added
- **Decision docs are typed records (role `decision`).** The `remediating-issues` per-task variant writes `task-N-decision-c<cycle>.json` and runs `ledger.py check` on it. Beyond its shape (each fix choice has a reframe, a cases table, a completeness line, and at least two candidates with exactly one chosen), `check` verifies it against the store and the repo:
  - it accounts for every finding on every reviewer record in its scope, with a choice or an exclusion and its reason. Scope comes from file names (`task-N-`, `final-`, `final-r2-`), and a record whose `task` disagrees with its name blocks the decision;
  - it reconciles with every decision doc written before it;
  - each candidate cites a `path:line` that exists in the repo, outside the store;
  - its file name matches its scope and `cycle`, and a malformed record in its scope blocks it.
- **`ledger.py findings <decision path>`** lists the finding ids that decision must account for, any malformed or misfiled record hiding findings, and the decision docs to reconcile with.
- **Escalations wait on the user in `open`.** Each `escalate` choice is an open item until `resolve` logs the ruling (`--note "user ruling: ..."`, required), and reviewers keep raising an escalated finding until then.
- **A root cause outside the brief has three routes.** A coder reports it as a `root cause:` concern, and SDD asks the user to choose: research it with `remediating-issues`, file it as a follow-up, or name the fix in a ruling. A bare "fix it" no longer sends the coder back. A decision record may claim a coder concern's id (`findings` lists them), and one written before any review lists no reviewer records, so the fix routes through a snapshot and re-review.
- **`ledger.py baseline <tree> --task N`** prints how a fix baseline was routed. Coders run it before fixing and return `needs_context` when it errors or doesn't match the dispatch.

### Changed
- **A non-trivial fix names its route.** `snapshot --non-trivial` now takes `--decision <record>` (which must pass `check` for this task, have a fix choice, and not be unchanged since it routed an earlier fix) or `--settled-by cases|ruling` (a ruling must be logged first). A decision the coder refused can be rewritten and route the same fix again; `fix-count` counts it once. It logs the decision's digest, so `baseline` confirms the doc is the one that passed without re-deriving coverage that later records would make stale. `stats` lists every fix's route.
- **SDD tells the orchestrator to dispatch the research agent and never write the decision doc itself**, with a matching red flag. The dispatch has the agent invoke the skill with the Skill tool.
- **Record envelopes validate `task`** (a positive integer or `"final"`), and reviewer `issues`/`findings` lists are validated when present, so a malformed finding can't drop out of a decision's coverage.

## [0.7.0] - 2026-10-08 — Comments that state behavior

On 0.6.0, one fix regressed and the 0.6.0 machinery caught and diagnosed it as designed, but most extra fix cycles came from something else: coders copying the run's own vocabulary (task and finding ids, cycle numbers, decision docs, commit hashes) into code comments, which a plan constraint forbade and the coders' own self-check greps kept missing. The run's records also couldn't show any of this directly, since each cycle overwrites the last verdict.

### Added
- **`ledger.py labels <tree> [paths]`.** Lists review-process labels on the lines added since a tree and exits 1 if any are found. Specific patterns (decision-doc and reviewer vocabulary, `.sdd/` paths, record field names, "fix baseline", `T1's`) count on any added line. Process words (`cycle 2`, `task 3`, `orchestrator`), short ids like `(A1)` or `#157 F1`, and commit hashes count only in comments and docstrings, since they are ordinary in code. Prose files are skipped (`CMakeLists.txt` is scanned). A path that matches nothing, or any error, exits 2, so neither a typo nor a failure reads as a pass.
- **The no-process-labels rule.** Coders keep comments to behavior, run `labels` before reporting, and list a false positive in `concerns`. SDD runs `labels` whenever a coder returns, before review (and before review-lite reruns after a commit-gate fix), and sends hits back as the same attempt (no fix cycle), so a leaked label never costs a review cycle. `executing-plans` runs it before each commit, and `verification-before-completion` before its close-round and ruling commits.
- **Check history and `ledger.py stats`.** A passing `check` on a record in a store appends a summary line to the store's `history.jsonl`, and `clear` removes it with the rest of the run. `stats` prints each task's verdicts cycle by cycle and the records that flagged `introduced_by_fix` or `recurring`.

### Changed
- **Escalation counts non-trivial fixes, not cycles.** SDD counted cycle 3 by the reviewers' own `cycle`, which a reviewer re-dispatched within one cycle advances, so a spec reviewer could reach cycle 3 after one fix. A coder's cycle doesn't work either, since trivial fixes advance it. The orchestrator now flags each non-trivial fix's baseline (`snapshot --non-trivial`), and the new `ledger.py fix-count` counts them; a third non-trivial fix escalates instead.
- **A finding closes only by re-review or by the user.** An orchestrator could accept code untested by its own ruling after a reviewer asked for a test. When a decision doc concludes a finding can't or shouldn't be fixed as asked, SDD now escalates it to the user with the evidence: waiving a requested test is the user's call. The finding is held out of triage and the fix count until the user rules. The ruling is logged as a `user ruling:` progress note, and reviewers given a logged waiver don't re-raise what it waives.

### Fixed
- **Docs, README, decks and the guide caught up with 0.5.0 and 0.6.0.** They still showed spec review before quality review, the completion gate as six steps that stop the line, and "cycle 3 always escalates". They now describe parallel review with one triage, the close round and its two-round cap, the escalation rule, fix mode, `Cases:` lines, the remediating-issues variants, the full `ledger.py` subcommand list, and all 15 agents including `claim-checker`. The Marp decks' HTML and PDF exports are re-rendered, and three slides that ran off the page now fit.

## [0.6.0] - 2026-10-07 — Fixes that don't regress

Coder fixes were introducing new issues: a fix ran the build workflow in a cold agent, aimed only at clearing the listed findings, and was self-checked with a narrower list than the reviewer's. And coders fixed only the cited case, so sibling cases (`size=None`, negative sizes) surfaced one review cycle at a time.

### Added
- **Fix mode for coders.** From cycle 2, a finished fix's record must carry `hunk_map` (every changed hunk and the finding or decision-doc choice it implements; at least one entry) and `consumers_checked` (every changed symbol's consumers and how each was verified; a consumer the fix breaks is part of the fix). `ledger.py check` enforces both alongside `diagnosis`, and coder records now require `cycle`, since every fix-mode check keys off it. A non-trivial fix is also self-reviewed against the matching quality reviewers' contracts, the lens that will judge it.
- **Fixes go back to the original coder.** SDD continues the implementing agent with `SendMessage` while it's reachable, so the fixer keeps its context; a fresh dispatch at the same record path is the fallback.
- **Fix baselines: `ledger.py snapshot` and `diff-since`.** Coders never commit before review passes, so a fix's edits share the working tree with the uncommitted cycle-1 work. Before each fix, SDD snapshots the working tree as a git tree, through a throwaway index so the real index and working tree are untouched. The coder and re-reviewers run `diff-since <tree> <task files>` to see the fix alone, limited to the task's own files because the other tasks in an SDD stage edit the same working tree. It keeps git's same-second ("racily clean") check working, ignores the user's diff config, leaves no orphan files in split-index repos, refuses an option-shaped tree id, survives non-UTF-8 content, and warns about submodules and about paths that match nothing.
- **`introduced_by_fix` on spec and quality reviewer records.** Problems the fix itself caused, on lines of the fix diff or in a consumer of a symbol it changed; each is also an ordinary finding (spec issues gain a `regression` kind). Like `recurring`, a non-empty list marks a failed fix: those findings are always non-trivial, their decision doc must explain the regression, and they join the cycle-3 escalation briefing. Validated when present and tolerated when absent, so stores from before 0.6.0 survive a mid-run upgrade.
- **Planned case coverage.**
  - `lean-plan` tasks carry a `Cases:` line: every case the task's rule covers, with its intended behavior; for a refactor, what it preserves and the tests that cover it; or `n/a — <reason>`. `task_brief.py` refuses a task without one, or with a placeholder (`none`, `TBD`, a bare `n/a`, punctuation only), or with `n/a` for a refactor (exit 3). Bulleted, numbered, checkbox, bold, and indented sub-list forms all count. Plans written before 0.6.0 have no `Cases:` lines; SDD's pre-flight review proposes them and writes the approved lines into the plan.
  - The spec reviewer files a `missing` issue for a listed case with no test, and `misunderstood` for one implemented with different behavior.
  - Spec and quality reviewers name each finding's rule and its whole class within the task's changed files; the fix is held to the class.
  - Coders implement and test every listed case. A case they handle that wasn't listed is reported as `unlisted case:` in `concerns`; SDD carries it into later briefs for the same kind of rule and lists it in the completion report. The plan is never edited mid-run.
  - A finding that only reports a case the `Cases:` line already lists goes straight to the coder, without a decision doc.
- **Escalated consumers get routed.** A fix that breaks a consumer the coder can't change (another language, or a public-API change) returns `done_with_concerns`; SDD dispatches that language's coder for it, with its own record and report paths, and adds its quality reviewer to the re-review.

### Changed
- **Close round 2 re-runs only what the remediation could have changed:** the design reviewers at their same report paths, mutation over the remediation range (`mutation-tester` accepts a `Range`), and the intent re-check only when the remediation changed behavior. Every review-lite gate and coder dispatch in the close has its own record and report paths.
- **SDD:** triage is split into triage, routing, fix baseline, and checklist; the orchestrator's staging and commit step is explicit; a task's plan entry ends at a heading of its own or higher level, and code fences follow CommonMark (``` or ~~~), so the last task no longer absorbs the plan's trailing sections.
- **Agent contracts** list every input they use; quality reviewers may check consumers of symbols a fix changed; review-lite names both of its writes and records an empty-diff verdict; the store is described as what it is (`.sdd/` in the working tree, self-ignored).

### Fixed
- **`executing-plans` skipped the completion close.** It went from its final review straight to `finishing-a-development-branch`, whose prerequisite is `verification-before-completion`; it now runs it first. It also logs a task complete only after its commit, checks for a stale store before resuming, and gives its quality reviewers record paths.

## [0.5.0] - 2026-10-04 — Batched, coherent remediation

Review findings stop cascading: SDD's per-task loop and the completion close batch their verdicts, triage once, and route non-trivial fixes through the coherence engine, with the close capped at two rounds.

### Changed
- **Batched, coherent remediation in SDD and the completion close.** (`executing-plans` keeps its simpler inline loop; only its final gate was aligned.) Fix rounds were cascading: findings fixed one gate at a time as point patches, outside the coherence engine, each fix surfacing new findings on its own surface.
  - **Per task (SDD):** the spec reviewer and quality reviewers now run in parallel (spec-first ordering removed), and every verdict accumulates before one triage. Trivial findings (no behavior change, one site, no contract) go straight to the coder. Non-trivial ones first go through `remediating-issues`' new **per-task variant**: decision-only, with one decision doc of defended choices and no approval checkpoint. The coder fixes against that doc. A recurring finding's doc must replace the failed mechanism. Escalation is now counted by the reviewers' own cycle: a task gets at most two non-trivial fix attempts, a re-review at cycle ≥ 3 with a non-trivial finding still open goes to the user, and trivial-only leftovers never escalate. Re-reviewers also get the decision doc, so they judge the fix against the defended choice instead of re-litigating it.
  - **Completion close:** `verification-before-completion` runs its design, intent, and mutation gates as one **close round**, dispatched together and triaged once. Non-trivial findings go through `remediating-issues`' new **close-gate variant** (decision doc with the usual approval checkpoint, then `lean-plan`, then SDD on the same store; the only batch that skips `lean-spec`). Round 2 re-checks at the same report paths. A new finding on code the remediation never touched is logged as a follow-up, and anything non-trivial left after round 2 goes to the user.
  - **`ledger.py close-round --expect N`** records each round, and the HEAD it reviewed, as a typed progress entry and refuses a third, so the two-round cap and round 2's remediation range survive compaction. `--expect` fails when the store disagrees (for example, a fresh close finding an earlier run's rounds), so a stale store can't silently start a new run at round 2.
  - **`ledger.py clear`** now also removes the run's handoff files (briefs, reports, per-task decision docs, gate reports, review packages). Gate reviewers read their report path as their prior verdict, so a surviving report would anchor an unrelated run on stale findings.

### Fixed
- **Gate reviewers join the file-handoff system**: the design reviewers and `intent-reviewer` — the last agents returning full reports inline into the orchestrator's context — now write their report to a dispatch-supplied path under the run store and return only `PASS | CONCERNS` plus the path (read-only on the checkout otherwise; a re-run reads its own prior report; an ad-hoc dispatch with no path still gets the report inline). `verification-before-completion` supplies the paths via `ledger.py store-dir`. Surfaced by a live session hitting the design reviewer's inability to persist its cycle-2 verdict.
- **The missing-record-path backstop no longer overreaches ad-hoc dispatches**: coders skip the typed record (noting its absence) when a dispatch carries no store artifacts at all, and the review-lites return their verdict as a standalone pre-commit gate; the refusal now fires only on an SDD-shaped dispatch that omits the record or scripts path. The unconditional 0.4.0 form would have made plugin coders and review-lites refuse every legitimate non-SDD dispatch (e.g. a project agent delegating a fix, or the plain pre-commit gate).
- **Script calls go through `$SDD_SCRIPTS`.** Skills ran SDD's scripts by repo-relative path (`scripts/ledger.py`), which resolves against the user's project rather than the plugin install path; it only worked inside this repo by coincidence. SDD pins `SDD_SCRIPTS` from its skill-load base directory, and skills that run without SDD derive it from their own. `tests/test_scripts_path.py` guards against a bare call returning.
- **The review-lite loop-breaker no longer escalates trivia.** It fired at cycle 3 on any remaining finding, S1 included. It now needs a surviving block condition (an S3+ finding or a failed linter).
- **A coder stopping mid-fix no longer has to invent a diagnosis.** `diagnosis` is required from cycle 2 only on a `done`/`done_with_concerns` record, and a re-dispatch after `needs_context`/`blocked` keeps the prior cycle.
- **`executing-plans`' whole-change gate matches SDD's**: explicit package outfile, record path, and scripts path.
- **Stale review ordering** in the decks, slides, README, and how-to (spec then quality) now shows the parallel review; `remediating-issues` no longer mis-cites its own stage 4 as the approval checkpoint.

### Added
- **Diagnosis-first fix loop** (data-driven, from a 25-round wave analysis): coders self-derive `cycle` like review-lite (fix re-dispatch at the same record path), and from cycle 2 their record must carry a `diagnosis` (`root_cause`, `end_state`, `resolves_cluster` — `check` enforces it); re-reviewing agents judge the fix against the stated cause. Spec- and quality-reviewers gain a `recurring` field (same finding class at the same site across cycles) — the typed fix-failure signal; when it fires, the next fix dispatch must carry a **defended mechanism choice**. Cycle ≥3 still always escalates to the user, but a recurring-mechanism signature that persisted through a defended fix arrives briefed with a `coherent-change` defended choice.
- **Fixture-reality principle** in all coder and quality-reviewer contracts: RED proofs and pinned fixtures must be produced by the real path under test (or a documented mirror) — a hand-built shape the production path never emits pins the wrong behavior. Three same-shaped failures in one wave earned the contract line.
- **Reviewer accumulation rule**: never dispatch a fix while any reviewer for the same task is still out — one fix dispatch carrying every reviewer's record path.
- **The fix loop is now taught, not just wired**: a "The fix loop" section in execution-mechanics, a README bullet, a guide callout, and an intro-deck line with companion notes — accumulation, diagnosis-first, recurrence-not-new-findings as the failure signal, and the cycle-3 briefing rule.

## [0.4.0] - 2026-08-28 — Typed handoffs & grounded integration

The typed handoff layer: agents hand reasoning to each other as files and decisions to the orchestrator as validated JSON records, the store moves out of `.git/`, and judgment-shaped verdicts are grounded by a dedicated quoting agent instead of orchestrator re-reads.

### Added
- **`claim-checker` agent** (haiku, read-only, non-judging): settles one decidable factual claim about code by quoting the lines that answer it (`holds` / `does-not-hold` / `not-decidable-by-reading`, evidence mandatory). `subagent-driven-development` now grounds judgment-shaped verdicts and spec-reviewer `cannot_verify` items **by dispatch, not by reading** — the orchestrator formulates a decidable claim and the checker does the looking, so grounding stops costing the context the file handoffs protect. Agent count: 15.
- **Typed handoff layer** in `subagent-driven-development`: the nine per-task-loop agents write JSON records validated against a shared contract (`scripts/ledger.py` — `check` as the agent's own write-time gate, `open`/`resolve` with content-derived ids, `shapes`, typed completion), and `scripts/task_brief.py` gates briefs on an intent statement and validates `Consumes:` pointers. Backed by a stdlib-only test suite under `chris-code/tests/`.
- `coherent-change` **batch mode** — a set of end-state-framed changes (audit / review findings) runs as one consolidated research pass → a defended choice per change → **one** `lean-spec` → **one** `lean-plan` → SDD. `coherent-change` is now the universal *application* engine.
- A **workflow catalog** in the docs (the How-to landing) — a graph, *when to use it*, and *how to invoke* for every canonical route — plus new recipes: build a feature, debug an unknown cause, remediate in batch.

### Changed
- **A malformed `progress.jsonl` line now raises** instead of being skipped with a stderr warning — the log feeds `resolve`'s already-resolved gate, so a silently dropped resolution line would silently re-open an item. This was the one place the loud-failure rule bent.
- **Findings hand over by path, never by paraphrase**: when a review comes back `issues`/`block`/`escalate`, the fix dispatch carries the reviewer's record path instead of the orchestrator restating the findings — restating is where a finding quietly loses its severity, `file:line`, or reasoning.
- **The SDD store moved out of `.git/`**: `ledger.py store-dir` now resolves to `.sdd/` at the repo toplevel (per-worktree via `--show-toplevel`) and seeds a `.gitignore` containing `*` inside it, so the store ignores itself with no edit to the repo's ignore rules. `review-package`'s default outfile now routes through `store-dir` instead of deriving its own path. A session in flight against the old location keeps reading it via `--store "$(git rev-parse --git-path sdd)"`.
- `coherent-change` now **sizes the change at the approval checkpoint** and recommends an execution route: a single coherent edit builds inline (as before); a major / multi-task change routes the defended choice to planned execution (`lean-spec` → `lean-plan` → `subagent-driven-development`) instead of being built in one shot. Closes the gap where a directly-invoked major change had no path into the planned-execution workflow.
- **Discovery skills now route to remediation.** `code-archaeology`, `bug-hunt`, and `technical-review` terminate at their artifact and **offer** batch remediation (bug-type → `remediating-issues`, structural → `coherent-change` batch) or defer — closing the previously-manual discovery→remediation seam.
- **`python-review` / `rust-review` no longer apply patches.** They stay interactive discovery and route their proposed end-states through `coherent-change`, which finds the method and runs the close.
- **`remediating-issues`' Batch Path** is now a bug-framed caller of `coherent-change` batch mode (one consolidated spec → plan), not per-issue fan-out.
- **Docs, guide, and intro deck teach the two-chain flow**: markdown artifacts (brief → report → verdict) are the reasoning chain between agents, JSON records the decision chain to the orchestrator — new guide section, new deck slide with a `two_chains` figure, and a "two chains" paragraph in execution-mechanics.

### Fixed
- **A dispatch that omits the record path is now refused, not silently accommodated**: the first live trial produced no typed records because the orchestrator's dispatch stopped at the report instruction and the coder, told never to compute paths, silently skipped its record. The Report-file bullet now names dispatch elements 6–7, and every record-writing contract stops and asks (`NEEDS_CONTEXT` / refusal) when the record or scripts path is missing.
- **Stale grounding prose retired**: execution-mechanics, the assurance model, context-and-dispatch, the README's integrator-grounding bullet, and the deck companion all said the orchestrator "re-reads the actual code slice" — updated to the ground-by-dispatch (`claim-checker`) model; `scope-dispatch.md` gains the claim-checker row; the guide's pre-existing stale 13-agent counts fixed.

## [0.3.0] - 2026-06-26 — Rigor hardening & documentation

Made the structure honest about what it proves, added the missing intent axis, and gave the framework a full documentation site.

### Added
- **Intent integrity.** A frozen **intent ledger** (≤7 observable acceptance statements, assistant-drafted during `brainstorming`) and a spec-blind **intent re-check** as `verification-before-completion` Step 5.
- **The conformance pair** as registered agents: a new spec-blind `intent-reviewer`, and `spec-reviewer` promoted from a dispatch prompt template to a language-agnostic registered agent.
- **"Brief carries intent, coder demands it"** — the dispatch loop that states a task's *why* explicitly and has coders escalate when it's missing.
- A **Zensical (Diátaxis) documentation site** under `chris-code/docs/`, built fully on-the-fly via `uvx` (no `pyproject.toml`), with a GitHub Pages workflow. A `CHANGELOG.md` (this file).

### Changed
- **Gate honesty** — reframed "more stages" as raising *recall*, not proof, across the decks and `verification-before-completion`; checklists are a floor, not a ceiling.
- **Integrator grounding** — the orchestrator re-reads the actual code slice behind a judgment-shaped verdict instead of trusting the summary; reviewers emit a lossiness flag.
- Reconciled the README and docs against source (13 agents, 25 skills); added a determined-change engine section to the README; relocated the visual decks to `chris-code/assets/decks/`.

### Fixed
- Design-reviewer lane formatting on both visual decks.
- Removed a session-internal "fork path parked" reference that leaked decision context into a durable skill.

### Removed
- The forking guardrail note (G-1), reverted once forking proved version-dependent and unreliable; its rationale is retained as future-extension material, not shipped guidance.

## [0.2.0] - 2026-06-24 — superpowers v6.0.0 backport & the change engine

Backported v6.0.0's execution mechanics, added the read-only senior review gate, and introduced the determined-change engine.

### Added
- **The determined-change engine** `coherent-change` (research → defend the most coherent implementation → implement → lite-review, producing a defended choice) and its bug specialization `remediating-issues`.
- **Senior read-only design-reviewer agents** (`python-design-reviewer`, `rust-design-reviewer`) for the verification gate, registered in the manifest.
- **Execution mechanics (v6.0.0 backports)** in `subagent-driven-development`: file handoffs, pre-flight plan review, a durable progress ledger, and reviewer-integrity rules, with `task-brief` / `review-package` / `progress` scripts (`task-brief` and `progress` since renamed to `task_brief.py` and `ledger.py`).
- The visual decks (overview, from-superpowers).

### Changed
- `coherent-change` adopts **build-and-handback** — the engine builds and lite-reviews; callers own the heavyweight close.
- Reframed document length as **word-efficiency** under "contracts stay, choreography goes"; replaced word budgets with the efficiency framing.
- Added instruction-precedence / anti-suppression clauses to review agents; PASS-with-findings treated as **not-clean** (in-scope findings fixed in-change).
- Reframed the SDD task brief as a reference sheet, not a restatement of the spec.
- Reconciled v5.1.0 provenance with the v6.0.0 backport; corrected the superpowers comparison against the v5.1.0 baseline.

### Fixed
- The prove-RED recipe now runs **before** staging — `git stash pop` restores the working tree but not the index, which silently dropped the fix from the commit.
- The final-gate `review-lite` no-op, and the reconnected cycle backstop.

## [0.1.0] - 2026-06-08 — Foundation

The initial chris-code workflow, forked and generalized from superpowers v5.1.0.

### Added
- The chris-code **plugin manifest** and the `using-chris-code` session-start meta-skill (generalized from an earlier project-specific "ferrum" agent/skill set).
- **The agent layer**: coder agents `python-coder`, `pytorch-coder`, `rust-coder` (exclusive, most-specific-wins dispatch); `python/pytorch/rust-quality-reviewer` (additive); `python/rust-review-lite` commit gates; `bug-hunter` — with `.ipynb` support for the Python agents.
- New-over-superpowers skills: `lean-spec`, `lean-plan`, `technical-review`, `regression-test`, and the `bug-hunt` / `test-sweep` / `code-archaeology` / `release` campaigns.
- A top-level repository README with three install methods, and a chris-code README with the workflow graph and skill/agent reference.

### Changed
- **Overhauled `subagent-driven-development`** with staged parallelism by file footprint, specialized per-task agents, and a final full-diff review.
- Adapted the inherited superpowers skills — `brainstorming` (spec-readiness check), `test-driven-development`, `systematic-debugging` (boundary checks), `using-git-worktrees` (hard gate on fallback), `receiving-code-review`, `requesting-code-review`, `writing-skills` — and converted all DOT graphs to Mermaid.
- Made `verification-before-completion` concrete and unified scope dispatch across the plugin (exclusive vs. additive).

### Fixed
- A Mermaid parse error and the `pytorch-coder` dependency tiebreaker.

### Removed
- superpowers-specific language and project-specific ("Ferrum") terms throughout the skills.

[Unreleased]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.7.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.6.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.5.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.4.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.3.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.2.0]: https://github.com/chris-santiago/claude-plugins/commits/main
[0.1.0]: https://github.com/chris-santiago/claude-plugins/commits/main
