# SDD Per-Task Review-Fix Loop Design Spec

Intent ledger: `.claude/output/intent/2026-11-04-sdd-per-task-loop-intent.md` (revised 2026-11-05).
Source review: `.claude/output/reviews/2026-11-04-sdd-route-map.md` (closes F1, F5, F8, F9 for this loop, F10, F15).
Evidence: a 66-task real run's store, classified fix cycle by fix cycle (2026-11-05). Figures below cite it as "the run".

Revised 2026-11-05 from the 2026-11-04 draft. Every mechanism kept here passed one of three tests: it prevents a failure observed in the run or reported by the user, it gives some actor a legal move in a reachable state, or it is the only enforcement of a guarantee still wanted. Mechanisms that passed none were cut.

## 1. Scope

SDD's per-task loop today routes reviewer findings by the orchestrator's trivial/non-trivial call. Trivial fixes trigger an uncapped full re-review, every non-trivial finding gets its own decision doc, and a two-fix counter with route flags decides when to stop. A per-task review-lite then runs its own fix loop. In the run this produced 2.39 fix cycles per task and 144 user rulings, and 45% of later findings were introduced by the previous fix, most of them by a decision doc's choice.

This redesign replaces that with:

- a script-computed triage over findings tagged by reviewers with severity and reach;
- at most two fix rounds per task, each either a patch or a task-wide holistic round, then one batched question per stage;
- fixes that list every site of a rule and write a failing test before the fix;
- a two-party contest for wrong findings;
- notes that never get a re-review;
- a scripted commit gate in place of per-task review-lite.

Upstream, lean-plan's `Cases:` lines must decide behavior as named rows, so fewer gaps reach review. The whole-change gate uses the same triage. executing-plans keeps a light path.

## 2. Goals

- A fix closes every instance of its finding's rule within the task, and the coder's record shows where.
- Serious and broad findings get one coherent task-wide change. Everything else gets a cheap patch.
- At most two fix rounds per task, then the user, once per stage, with a recommended answer for every item.
- Minor findings cost no review cycle, and none is dropped without the user deciding at close.
- Behavior a plan leaves undefined is decided coherently with the codebase and surfaced as a default.
- A wrong finding can be settled without spending a fix round.
- Routing is computed by `ledger.py` from records. The orchestrator declares nothing a script can compute.
- Telemetry ties each fix round to its coder model and outcome.

## 3. Non-goals

- The verification close round's triage. It keeps its own process for now.
- Scaling test depth and mutation effort by project size ("rigor level"). That is a separate change. This spec fixes only what a `Cases:` line must decide, not how deep it goes.
- coherent-change build mode's lite loop (F2), verification Steps 1-2 fixes (F4), inserted-task briefs (F7), worktree invocation (F6).
- review-lite's standalone behavior.
- Converting in-flight stores. Stores are per-run, and a schema-1 store is finished on the prior release or cleared.
- Gate re-execution of new tests against the pre-fix tree. "Failed first" rests on recorded output, which reviewers can spot-check.

## 4. System behavior

### 4.1 Tiers

Every reviewer finding carries `severity` (1-5), `reach`, `rule`, and `sites`. The tier comes from severity and reach alone:

| | reach `local` or `class` | reach `contract` |
|---|---|---|
| S1-S2 | note | defer |
| S3-S5 | patch | holistic |

- `local`: one site. `class`: the same rule at several sites in the scope's files. `contract`: the fix changes a public API, a schema, or a symbol with consumers outside the scope's files, or needs edits outside the scope. The scope is the task, or the whole change at `final`.
- A coder `root cause:` concern is a holistic item.
- A finding the coder raises to `contract` reach (`reach_raised`) is holistic from then on.
- `recurring` and `introduced_by_fix` never change a tier. They oblige the next fix to list the flagged sites (Section 4.3) and feed telemetry.
- A spec finding that names a listed `Cases:` row is S3 or higher.
- A finding a reviewer `holds` after a contest is held for the user (Section 4.5).

### 4.2 Rounds

`ledger.py triage` derives the next step from the records and the scope's prior triage entries. *Open work* is every S3+ finding and every `root cause:` concern that is not closed, waived, or held. A finding closes only when a re-check stops raising it, or by a logged user ruling. The orchestrator never assigns, changes, or drops a tier.

1. Open work and fewer than two fix rounds so far: a **holistic** round if any holistic item is open, else a **patch** round.
2. Open work after two fix rounds: **escalate**.
3. After escalation, a logged user ruling: a **ruling** round over the ruled findings. Waived findings are excluded. A ruling round that leaves open work escalates again.
4. No open work, and notes not yet sent to a coder, or a note filed for the task not yet delivered: one **polish** dispatch.
5. Otherwise: **done**.

Notes ride along in every fix round's dispatch. The coder fixes each note or records it in `notes_skipped`. Either way the note is handled and never re-reviewed.

Re-checks, which `triage` names in the entry's `recheck`:

| Step | Who re-checks | Over what |
|---|---|---|
| patch, ruling | the reviewers whose findings were sent; a gate finding re-runs the gate | the fix diff (`diff-since` the round's baseline) and consumers of every symbol it changed |
| holistic | every reviewer | the whole task |
| polish | none (the gate is its check) | n/a |

Each re-check dispatch carries the round's contests with their evidence, and the scope's settled findings (Section 4.5).

### 4.3 Fix rounds

**Patch round.** The original coder takes the whole batch.

- **Sweep with rows.** Per finding, the coder states the rule and searches the scope's files plus the consumers of every symbol the fix changes. It lists every site where the rule applies as a row, each mapped to the hunk that fixes it or marked `already correct` with evidence. A `recurring` or `introduced_by_fix` finding's flagged sites must appear as rows. A site outside the scope is recorded in `sites_outside` and routed as in Section 4.6.
- **Search evidence.** Each sweep records either `searched` (the command and its result) for a textual rule, or `inspected` (each symbol or file examined and how it was found) for a rule a text search can't express.
- **Tests first.** For each S3+ finding about behavior, the coder writes a test, runs it, and records the command and its failing output before the fix. A finding with no behavior to test (structure, duplication) gets `n/a` with a reason, which reviewers judge.
- **Contract discovered.** If a fix turns out to need a contract change, the coder stops before making it and records `reach_raised`. The task goes holistic at the next triage.

**Holistic round.** An opus research agent runs the remediating-issues per-task variant over the whole task: its diff, every reviewer record from every round, and the coder records. It may redo the task's implementation shape. It writes one decision doc that accounts for every open finding and `root cause:` concern. Each fix choice lists its rows (every affected site, every coupling the choice touches, and each named test with its expected result) and probes the premise it rests on. The original sonnet coder implements the doc test-first and maps every row to a hunk.

**Ruling round.** The coder implements the user's ruling with the same rows and tests-first obligations.

**Polish.** The coder fixes or skips the open notes, or applies a late note. The gate checks the result.

### 4.4 Open behavior choices

When the brief leaves a behavior undefined, the coder doesn't stop. It picks the behavior the codebase already uses for the nearest analogous case, implements it, and records an `open` entry: the question, the choice, and the `precedent` site, or `no precedent` with its reasoning.

- A reviewer doesn't raise a finding against a declared choice for disagreeing with it. A reviewer may raise a finding when the choice contradicts an existing precedent, since that is a coherence defect.
- Open choices join the stage's batch (Section 4.5) with the coder's choice as the default. `no precedent` items are flagged as design choices.
- Accepting costs nothing. Overriding is a ruling and costs one ruling round.

### 4.5 Contest, settlement, and the stage batch

**Contest.**

- The coder records `contested` with a reason (`wrong` or `plan-conflict`) and evidence instead of fixing.
- At re-check, the raising reviewer sees the evidence. It concedes by not raising the finding again, which closes it. Or it holds by re-raising it with `holds` naming the contested finding, which marks it held for the user.
- A contest never consumes a fix round by itself.

**Settled findings.**

- A finding is settled when it was conceded, waived, or ruled. Each triage entry lists the scope's settled findings and the tree they were settled against.
- A reviewer that raises a settled finding again must mark it `reopens`, and one of its sites must lie in lines changed since that tree. `check` refuses a `reopens` that fails this.
- An unmarked restatement can't be detected mechanically. The reviewer contract forbids it.

**Stage batch.**

- A task with open work after two rounds, a held finding, an unanswered open choice, or a contract change needing approval is parked. A parked task does not commit. The rest of the stage proceeds.
- Once no task in the stage has a dispatch in flight, the orchestrator sends one message covering every parked item:
  - each task's open findings (rule, sites), with the holistic decision's choice and rejected alternatives where one ran;
  - the round history;
  - every item's recommended answer.
- One reply settles the batch: "accept all", or overrides by item number. The user can:
  - rule a fix, on an opus coder if they say so;
  - waive a finding, optionally filing a follow-up;
  - uphold or dismiss a held finding;
  - accept or override an open choice;
  - approve a contract change.
- Each answer is logged as a `user ruling:` note on its item.

### 4.6 Deferral and the close batch

The close batch is assembled from these items:

- S1-S2 contract-reach findings;
- sites a sweep found outside the scope;
- notes a coder skipped.

`triage` files each one exactly once as a follow-up carrying its finding's rule. An outside site goes as a task-note when a later task's footprint covers it, otherwise as a follow-up.

A deferral can't point into the scope. A task's footprint is its latest `ledger.py stage` files; at `final` it is the union of every task's footprint. `check` refuses a `sites_outside` entry or `root cause:` path inside the footprint.

The completion report groups open follow-ups by rule and presents them as one batch. For each item the user picks fix, file, or ignore. The fix items go through remediating-issues' Batch Path as one change.

### 4.7 Commit path

1. **`ready`** runs before staging. It passes only when:
   - triage's last step is `done`;
   - nothing is held, parked, or an unanswered open choice;
   - no note is undelivered;
   - the task owns no open disclosure or question;
   - no escalation or `cannot_verify` is open;
   - no record in scope is malformed;
   - at `final`, no `duplication_pending` is open.

   A confirmed `cannot_verify` gap goes back to the spec reviewer with the claim-checker evidence, and the reviewer raises it as a tagged finding.
2. **`gate`** stages nothing itself. It reads the staged scope files and runs labels on their added lines, then lint, then the task's `Verify:` command. Each passes only on exit 0.
   - A labels or lint failure returns to the coder as the same attempt, with no round consumed.
   - A test failure becomes an S3 `local` gate finding over the scope's files and enters triage.
3. **Commit, then `complete`.** `complete` re-runs `ready` and requires a passing gate whose tree matches the committed blobs of the scope's files.

### 4.8 Whole-change gate (`final`)

review-lite is the only reviewer, and it tags its findings. Lite tags `contract` on a symbol the diff shows as public (exported, no leading underscore, `pub`), and `local` or `class` otherwise. The coder's reach raise covers what lite can't see. Triage, rounds, and the two-round bound apply with `final` as the scope. A fix goes through gate and commit, then lite re-reviews at its same record path: over a package of only the fix commit after a patch, or the full `BASE..HEAD` package after a holistic round. Close-gate remediation runs keep their `final-r2-*` names.

### 4.9 executing-plans (light path)

executing-plans is the path for small work, and lean-plan's offer says so. Per task it does the following:

- It builds the brief with `task_brief.py` and records the footprint with `ledger.py stage`.
- The orchestrator implements against the brief, with the same open-choice and tests-first rules.
- The matching quality reviewers review it.
- It allows at most two fix rounds, then the user. The bound is a prose rule, not enforced.
- It runs `gate`, then `ready --light`, commits, then `complete --light`.

It writes no triage entries, sweep rows, or coder records. `--light` skips the triage, held, and open-choice checks and is recorded on the completion entry, so `report` shows which tasks ran light. The whole-change review stays on review-lite.

### 4.10 Upstream: plan contract and pre-flight

- **`Cases:` decides behavior.** A task that introduces or changes behavior lists it as named rows, each with an input or situation and its expected result (`size=0 → ValueError("size must be positive")`), never as a principle ("validate sizes"). A behavior the planner can't decide is written as an `open:` row with the question.
- **`Verify:` is a command** where exit 0 means pass. A zero-matches check is written `! rg -q '<pattern>' <paths>`.
- **Pre-flight.** SDD's pre-flight scan, which already batches thin `Cases:` lines to the user, also batches every `open:` row. Answers are written into the plan before execution.
- **`task_brief.py`** refuses a task whose `Verify:` line has no backticked command, or whose `Cases:` still carries an unanswered `open:` row.

### 4.11 Agent obligations

- **Coders:**
  - Run the brief's `Verify:` command exactly before reporting any attempt, recorded as `tests.command`.
  - Read the round's kind, decision, findings, and contests from `baseline`.
  - Keep sweeps, tests-first, open choices, contests, and `test_changes`.
- **Spec reviewer:**
  - Tags each finding, with the S3 floor for a listed `Cases:` row.
  - Checks each `Cases:` row has a test with the listed result.
  - Doesn't raise findings against declared open choices except on a precedent conflict.
- **Quality reviewers:**
  - Tag each finding, and may search a changed symbol's consumers to tag reach.
  - Check CLAUDE.md constraints and public sentinel returns, the two checks per-task lite carried that they lacked.
  - Re-run recorded sweep commands and spot-check inspected lists.
  - Judge tests-first `n/a` reasons and flagged test changes.
- **review-lite:** tags at `final`, with the public-symbol reach rule.
- **remediating-issues per-task variant:**
  - Runs only in holistic rounds, task-wide, dispatched on opus.
  - Writes rows and a premise probe per fix choice.
  - Accounts for `root cause:` concerns.

## 5. Architecture

- **`ledger.py`** holds all routing:
  - computes triage and writes triage entries;
  - files deferrals;
  - runs the gate and writes gate records;
  - answers `ready`;
  - enforces record contracts in `check`.
- **The triage rules** are a pure module with no I/O, no subprocess, and no import of `ledger`. They take plain data and return plain data, so they're testable on their own and never load a second `ledger` with a different `RecordError`.
- **Reviewers** are the only source of severity and reach, except the coder's upward reach raise. They are the only actors who close a finding by not re-raising it.
- **Coders** fix, sweep, test first, declare open choices, and contest.
- **The orchestrator** runs `triage`, makes the dispatch it prints, re-dispatches exactly the `recheck` set, parks tasks, sends the stage batch, and logs rulings. It holds no routing judgment. Its one judgment is the recommendation on an escalated task.
- **`stats`, `run-state`, `read`, `report`** render triage entries and follow-ups. `history.jsonl` is unchanged.

## 6. Canonical interfaces / data contracts

`SCHEMA_VERSION` becomes 2. Loading or checking a schema-1 record fails with a message to finish that run on the prior release or `ledger.py clear` the store.

### 6.1 Finding (reviewer and gate records)

Existing fields stay. Added, all required except where noted:

```json
{"severity": 3, "reach": "local | class | contract", "rule": "size must be a positive int",
 "sites": ["src/a.py:40", "src/a.py:88-91", "src/b.py"],
 "case": "size=0 -> ValueError", "holds": "<contested finding id>", "reopens": "<settled finding id>"}
```

- `sites`: one or more of `path`, `path:line`, `path:start-end`. The path is relative to the repo toplevel, lines are at least 1, and start is at most end.
- `case` (optional, spec reviewer only): names a listed `Cases:` row and requires severity 3 or more.
- `holds` and `reopens` are optional. `holds` must name a finding contested in the latest coder record. `reopens` must name a settled finding and have a site in lines changed since its settlement tree.
- Spec findings stay in `issues`; quality, lite, and gate findings are in `findings`.
- Status matches findings: spec `issues`, or quality `issues`, exactly when some finding is S3+.
- Every `recurring` and `introduced_by_fix` entry's `site` equals one of some finding's `sites`.

### 6.2 Coder record

The existing fields and checks stay. Added fields, each optional and empty when unused:

```json
{"sweeps": [{"findings": ["<id>"], "rule": "...",
             "rows": [{"site": "src/a.py:40", "hunk": "src/a.py:38-44"},
                      {"site": "src/c.py:12", "already_correct": "guards size at :10"}],
             "searched": {"command": "rg -n 'size\\s*[<>=]' src/", "result": "4 matches: ..."},
             "inspected": [{"target": "callers of make_grid", "found_by": "consumers search"}],
             "sites_outside": ["lib/x.py:9"]}],
 "tests_first": [{"finding": "<id>", "test": "tests/test_a.py::test_size_zero",
                  "command": "pytest tests/test_a.py::test_size_zero", "failed_output": "..."},
                 {"finding": "<id>", "n/a": "structural: no behavior changes"}],
 "decision_rows": [{"choice": 0, "row": 2, "hunk": "src/a.py:38-44"}],
 "open": [{"question": "what does size=None do?", "choice": "ValueError",
           "precedent": "src/grid.py:31"}],
 "contested": [{"finding": "<id>", "reason": "wrong | plan-conflict", "evidence": "..."}],
 "reach_raised": [{"finding": "<id>", "evidence": "..."}],
 "notes_skipped": [{"finding": "<id>", "reason": "..."}],
 "test_changes": [{"test": "tests/test_a.py::test_scale", "old": "2", "new": "3", "reason": "..."}],
 "decision": "<path to this round's decision doc>"}
```

`check` enforces the following.

On any record:

- A sweep has `searched` (non-empty `command` and `result`) or a non-empty `inspected`.
- `open` entries carry `precedent` (an existing site) or `no_precedent` (a non-empty reason).
- A `root cause:` concern starts with a site token.
- `sites_outside` and `root cause:` paths lie outside the footprint (Section 4.6). A store record carrying either needs a recorded footprint.
- A `consumers_checked` entry with no consumers carries the same `searched` or `inspected` evidence as a sweep.

On a finished fix (cycle 2 or later, `done` or `done_with_concerns`, in a store):

- A triage entry of kind `patch`, `holistic`, `polish`, or `ruling` precedes the fix's baseline snapshot since the scope's previous snapshot.
- Every finding the entry sent appears in exactly one of `sweeps[].findings`, `contested`, `reach_raised`, or (notes only) `notes_skipped`.
- Every row's `hunk` overlaps the diff from the fix baseline. Every `recurring` and `introduced_by_fix` site of a sent finding appears as a row's `site`.
- Every S3+ finding sent in a patch or ruling round has a `tests_first` entry, and a named test appears in the fix diff.
- **Holistic:**
  - `decision` names `<scope>-decision-c<cycle>` for this cycle, and that doc passes `check`.
  - Every row of every fix choice in it has a `decision_rows` entry whose hunk overlaps the diff.
- Every modified (not added) line containing an assertion, in a test file that existed at the fix baseline, is covered by a `test_changes` entry. Test files are recognized by path convention (`tests/`, `test_*.py`, `*_test.py`, `*_test.rs`, `tests.rs`). Assertions are recognized by `assert`, `assert_eq!`, `assert_ne!`, `pytest.raises`, `expect`.
- `labels` on the changed files finds no hit beyond the record's `label false positive:` concerns.
- The model check exempts `agent: executing-plans`.

### 6.3 Decision doc (holistic only)

The existing fields stay. Each `fix` choice adds two required fields:

```json
{"rows": [{"site": "src/a.py:40", "coupling": "src/b.py:12 reads the padded value", "test": "tests/test_a.py::test_pad", "expect": "pad=1.5 → refused at to_spec()"}],
 "premise": "what the choice assumes, and the probe that confirmed it"}
```

A row needs a `site`, a `test`, and an `expect`. `coupling` is optional per row.

### 6.4 Gate record (`<scope>-gate.json`, role `gate`)

```json
{"schema": 2, "agent": "ledger", "role": "gate", "task": 3, "status": "pass | fail",
 "tree": "<staged tree id>", "files": ["..."],
 "commands": [{"kind": "labels | lint | test", "command": "...", "passed": true, "excerpt": "..."}],
 "findings": [], "recurring": [], "introduced_by_fix": []}
```

A failing test adds one S3 `local` finding whose `rule` names the command and whose `sites` are the scope's files. Labels and lint failures set `status: fail` without findings. `fail` is an open status.

### 6.5 Triage entry (`progress.jsonl`)

```json
{"type": "triage", "task": 3, "kind": "patch | holistic | polish | ruling | escalate | done",
 "round": 1, "recheck": "raising | all | gate | none", "tree": "<tree at triage>",
 "findings": [{"id": "<id>", "tier": "note | defer | patch | holistic | held", "rule": "..."}],
 "settled": ["<id>"], "filed": ["<id>"],
 "model": "sonnet", "closed": 2, "survived": 0, "introduced": 1}
```

- `round` counts fix rounds of kind `patch` or `holistic`. Ruling and polish rounds don't count toward the two-round bound.
- `model` is the model of the scope's coder record with the highest cycle.
- `survived` counts open findings flagged `recurring`, and `introduced` counts those flagged `introduced_by_fix`. `closed` is the previous entry's finding count minus `survived`.
- Routing reads tags and flags. It never compares finding ids, which are digests of finding text.

### 6.6 Commands

| Command | Contract |
|---|---|
| `triage --task N\|final` | Computes Sections 4.1-4.2, files deferrals (Section 4.6), and appends one triage entry. Prints the step, the `recheck` set, each finding's id, tier, and rule, the contests to forward, and the settled list. Refuses, writing nothing, while a record in scope is malformed or when the scope has no reviewer record. |
| `gate --task N\|final --test CMD [--lint CMD]` | Section 4.7 step 2. Refuses when the scope has no footprint or nothing staged in it. Exit 0 on pass, 1 on fail. |
| `ready --task N\|final [--light]` | Lists every blocker in Section 4.7 step 1. Exit 0 only with none. |
| `baseline TREE --task N\|final` | Prints the round's kind, `recheck`, decision path (holistic), findings, and contests. Errors with no fix-kind triage entry before that snapshot. |
| `complete [--light]` | As today, plus `ready` and the matching passing gate. |
| `resolve <id> --note "user ruling: ..."` | Also accepts open finding ids and open-choice ids, settling them as waived, ruled, or accepted. |
| `note --kind follow-up --rule TEXT` | `--rule` is optional; `report` groups follow-ups by it. |
| `snapshot --task N --label L` | Plain baseline: task, label, tree. |
| `run-state`, `read`, `stats`, `report` | Render triage entries in place of fix counts and routes. `stats` prints per round: kind, model, closed, survived, introduced. `report` shows the close batch grouped by rule. |
| `task_brief.py` | Also refuses a missing `Verify:` command or an unanswered `open:` row in `Cases:`. |

Removed: `fix-count`, and `snapshot --non-trivial`, `--decision`, `--settled-by`.

## 7. Invariants and constraints

- A task gets at most two fix rounds (patch or holistic). Any further fix requires a logged user ruling.
- A minor (S1-S2) finding never starts a round and is never re-reviewed.
- Nothing in a scope's own change is dropped without the user: every note is fixed or skipped with a reason, every skip and deferral reaches the close batch, and no deferral points inside the footprint.
- A parked task never commits.
- A sweep's "no other site" claim is reproducible or itemized.
- Every fix starts from its own snapshot, routed by the triage entry before it. A holistic fix implements this round's decision doc, which passed `check`.
- Every claimed row maps to a real hunk, and every edited assertion in a pre-existing test is justified.
- Every commit of task work is preceded by a passing gate on the staged files. `complete` checks exactly `ready` plus the gate match.
- Opus coders only by user ruling.
- Library functions raise `RecordError` or `RuntimeError`. Only `main()` exits. The standard library only.
- review-lite's standalone behavior is unchanged except for the finding tags.

## 8. Key decisions and tradeoffs

| Decision | Rationale | Rejected |
|---|---|---|
| Tier from severity × reach only; flags don't route | A local regression has a known site and a failing test: patch work. A wrong design shows up as broad reach. T42 recurred three cycles under decision docs, and T49 converged only when the rule became named rows. | Recurring or fix-caused S3+ forced holistic (2026-11-04 draft) |
| Holistic only for S3+ contract and `root cause:` | 45% of later findings were fix-caused, mostly by decision choices. The engine is the heavy route and a defect source, so it runs where breadth demands it. | Holistic after any patch with open work |
| Two fix rounds of either kind, then the user | Bounded by structure, not a counter with route flags. A holistic first round can still be followed by a patch for a new local bug. | "A patch never follows a fix round"; escalate after any holistic round |
| Task-wide decision doc with rows and a premise probe | T16 halted after 7 per-finding docs ("We need a coherent design!"). Four docs had wrong premises, each costing a cycle. "Named neither its coupling" was a recurring cause. | A doc per finding; a pre-build doc review (another correlated LLM pass) |
| Sweep rows mapped to hunks; tests first | 26% of later findings were the same rule at the next site or a decided item left unbuilt. Partial builds were claimed complete (T42, T43). The dominant test complaint was tests that can't fail. | Free-text sweeps; tests after the fix |
| Search evidence: command or inspected list | Many rules can't be grepped. A forced pattern proves nothing. | Command always required; free text |
| Re-check = raising reviewers over fix diff plus consumers | Only 7% of later findings were fresh re-reads, and the user reports real bugs concentrate in the fix and its callers | Every reviewer re-reads everything |
| Notes ride along, never re-reviewed; skips go to close | Trivial routes cost 17% of fix-round reviewer dispatches for about 4% of fix-round findings. The user wants minor debt decided once at close. | First-polish re-check rules (2026-11-04 draft) |
| Contest: reviewer concedes or holds; settled findings need new code to reopen | Contests were 2.5% of findings and settled cheaply. The real gaps were a re-raised excluded item (T40), a false completion claim (T43), and an unjustified test flip (T35). | Every contest parked for the user |
| Open choices follow precedent, defaulted in the batch | 61 of 144 rulings defined behavior the plan left open, and almost all picked the recommendation. A precedent keeps choices coherent. | Coder stops on every gap; provisional orchestrator rulings (35 reversals in the run) |
| Stage batch with a recommendation per item; parked tasks don't commit | One interruption per stage, and one reply when the user agrees. Not committing avoids re-entry on a committed task (F5). | One question per item; committing and re-opening on override |
| `Cases:` as named rows; `open:` rows answered at pre-flight | 127 of 682 first-review findings were plan gaps. Rows with expected results are what made T49 converge. | Leaving plan quality to the rigor change |
| Scripted gate replaces per-task review-lite | Lite re-reviewed what reviewers had approved. Its unique checks moved to the gate and quality reviewers. Gate failures caused 1% of rework. | Keeping per-task lite |
| Lite stays at `final` | Cross-task drift was invisible per task and was all 5 non-trivial `final` fixes | Spec and quality reviewers at `final` (no brief to judge against) |
| executing-plans stays light | It's the path for small work. The full loop would make it as heavy as SDD. | Adopting the full loop; retiring it |
| Sonnet coder in holistic rounds; opus by ruling | The run showed no clear model effect next to decision quality | Opus for holistic rounds |
| Schema bump, no converter | Stores are per-run | Migrating in-flight stores |

**Removals and why each is the obvious choice.** The user asked that "any removal should have a rationale that makes it almost obvious choice".

| Removed | Why |
|---|---|
| Orchestrator's trivial/non-trivial call | It came from the one actor that doesn't read the code, and it sent minor items down the heavy route. Reviewers now tag. |
| Route flags, their checks, and `_check_reroute` | They let the orchestrator declare a route the code then verified. Triage computes the route, so nothing is left to declare. |
| `fix-count`, the cap, the run-state counter | The two-round structure bounds rounds and can't be miscounted. |
| A decision doc per non-trivial finding | It cost a research dispatch on local fixes and produced incoherent designs (T16) |
| claim-checker on findings and coder concerns | Dispatched 0 times in the run. Contests now settle between coder and reviewer. It stays for `cannot_verify`. |
| Every reviewer re-reviewing after every fix | Re-reading unchanged code resampled it into fresh nits (F1) |
| Trivial fixes as an uncapped cycle | Notes ride along and are never re-reviewed |
| Per-task review-lite, its triage path, and its cycle-3 escalate | See the scripted-gate decision |
| The orchestrator's separate `labels` run | `check` and the gate run it and can't be skipped |

## 9. Acceptance criteria

- **Tiers:**
  - each matrix cell routes as in Section 4.1;
  - `recurring` and `introduced_by_fix` don't change a tier;
  - `root cause:` and reach-raised findings are holistic;
  - a held finding is excluded from open work and parks the task.
- **Rounds:**
  - the first triage yields patch, holistic, polish, or done as specified;
  - after one patch round, an open S3 local finding yields a second patch, and an open contract finding yields holistic;
  - after two fix rounds with open work, escalate;
  - a ruling yields a ruling round, and its failure escalates again;
  - a third patch or holistic round can't occur without a ruling;
  - a lone `root cause:` concern starts a holistic round.
- **Notes:**
  - notes never start a round alone except as one polish;
  - a polish has `recheck: none`;
  - every sent note is in `sweeps` or `notes_skipped`;
  - skipped notes, S1-S2 contract findings, and outside sites are filed once as follow-ups with their rule, and nothing else is.
- **Re-check set:** each step's entry names exactly the set in Section 4.2.
- **Contest and settlement:**
  - a contested finding not re-raised closes;
  - one re-raised with `holds` is held;
  - `reopens` with a site outside changed lines is refused;
  - `reopens` with a site in changed lines is accepted.
- **Open choices:**
  - an `open` entry without a precedent or reason is refused;
  - an unanswered open choice blocks `ready`;
  - an accepted choice unblocks it;
  - an overridden one yields a ruling round.
- **`check` refuses:**
  - a finding missing a tag;
  - an inconsistent status;
  - an unmatched flag site;
  - a `case` below S3;
  - a fix with no fix-kind triage entry before its snapshot;
  - a sent finding uncovered or covered twice;
  - a row whose hunk misses the diff;
  - a flagged site missing from the rows;
  - an S3+ patch finding without `tests_first`;
  - a holistic fix without this round's passing decision doc, or with an unmapped decision row;
  - a decision fix choice without rows or premise;
  - an unjustified modified assertion in a pre-existing test;
  - a sweep without search evidence;
  - a deferral inside the footprint;
  - unlisted label hits;
  - a dispatched opus coder without a ruling.
- **`gate`:**
  - each command passes only on exit 0, so `! rg -q ...` passes on zero matches;
  - a test failure yields one S3 finding;
  - labels and lint failures fail without findings;
  - the staged tree is recorded, and the real index is unchanged.
- **`ready` and `complete`:**
  - `ready` lists each blocker, including parked and open-choice blockers;
  - `complete` refuses without a matching passing gate;
  - `--light` skips exactly the triage, held, and open-choice checks and is recorded.
- **Plan contract:** `task_brief.py` refuses a missing `Verify:` command and an unanswered `open:` row.
- **Whole-change:** a fix commits only after `gate` passes. Lite re-reviews the fix commit after a patch, or the full package after a holistic round.
- **Removals:** removed commands and flags are rejected. Schema-1 records are refused with the migration message.
- **Telemetry:** triage entries carry round, model, closed, survived, and introduced, and `stats` prints them per task.
- **Intent:** every statement in the intent ledger holds.

## 10. Validation strategy

- **Scenario tests** over store fixtures replaying the round sequences the run showed:
  - patch → done;
  - patch → patch → escalate → ruling;
  - contract → holistic;
  - holistic → patch;
  - contest conceded, and contest held;
  - an open choice accepted, and one overridden;
  - a note skipped → close batch;
  - a refused and an accepted reopen;
  - a gate failure → patch;
  - a partial build caught by an unmapped row.
- **Record rules:** each `check` rule gets one accepting case and one refusing case, where the refusing case is the mistake an agent would realistically make. No type-permutation matrices.
- **Drift guards:** contract examples in every agent document parse and pass `validate_record`. A stale-reference guard fails on removed names.
- **Live run:** one real plan on the new loop, with `stats` compared to the run's baseline:
  - 2.39 fix cycles per task;
  - 144 rulings;
  - 45% fix-introduced later findings;
  - reviewer dispatches per task.

  The intent-reviewer checks the intent ledger against that run.

## Appendix: prose changes (no design content)

- **SDD:**
  - the per-task loop sections, the flowchart, and pre-flight's `open:` batching;
  - Red Flags and the example workflow.
- **executing-plans:** Section 4.9, and its description.
- **lean-plan:** the `Cases:` row rule, `open:` rows, the `Verify:` exit-0 rule, its offer wording for the light path, and Self-Review.
- **Coders and `implementer-prompt.md`:** sweeps with rows and evidence, tests first, open choices, contest, reach raise, `test_changes`, `decision_rows`, the `root cause:` path format, running `Verify:`, and reading the round from `baseline`.
- **Reviewers:** tags, `holds`, `reopens`, settled findings, the re-check scope, consumer search, the CLAUDE.md and sentinel checks, and the open-choice rule.
- **review-lite:** tags at `final`, and the public-symbol reach rule.
- **remediating-issues per-task variant:** task-wide, holistic only, opus, with rows and premise.
- **verification-before-completion:** the completion report's close batch.
- **Docs and release:** `execution-mechanics.md`, `reference/ledger.md`, `reference/agents.md`, `the-pipeline.md`, `getting-started.md`, the README, the slides, and the CHANGELOG.
