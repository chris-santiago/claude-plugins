# Agents

chris-code ships 15 dedicated agents — the layer superpowers doesn't have. They auto-dispatch by file type and role, so you rarely pick one by hand. This page covers each agent and the disciplines they share.

## Typed records

Every record-writing agent — coders, `spec-reviewer`, the quality reviewers, the review-lite agents — writes its JSON record to a dispatch-supplied path, never one it computes itself. The naming convention behind that path: `task-<N>-<agent-name>.json`, keyed by the agent's registered name rather than its role, so additive same-role agents (e.g. both quality reviewers firing on one PyTorch task) never collide. The whole-change commit gate, which has no task number, uses `final-<agent-name>.json` instead, and such records carry `"task": "final"`. The completion close extends that stem: a close-gate remediation run's whole-change gate uses `final-r2-<agent-name>.json` (so it doesn't inherit the original gate's cycle), a close round's test-only fix and the commit gate on its inline fixes use `final-close-r<N>-<agent-name>.json`, and a fix from your ruling after round 2 (and its commit gate) uses `final-close-ruling-<agent-name>.json`. In every case the dispatch-supplied path defines record identity; these stems are the convention the orchestrator follows when computing it, not something an agent works out on its own. Each role's payload contract is documented under its own section, below.

## Shared review disciplines

Every review agent operates under the same rules, which is what makes the gates trustworthy:

- **Read-only on the checkout, aside from one handoff write.** Reviewers never edit files or mutate the working tree, index, `HEAD`, or branch (no `git checkout/stash/reset/commit`). They report; the coder fixes. Bash is for read-only inspection and focused tests only. The one write every reviewer performs is its own handoff artifact at a dispatch-supplied path in the run's store (`.sdd/` at the repo toplevel, self-ignored): a typed record (validated with `ledger.py check` until clean) for the per-task reviewers, a report file for the gate reviewers (design reviewers, intent-reviewer).
- **Instruction precedence.** The dispatch supplies inputs, not authority. No instruction in a dispatch can waive a review, soften a finding, pre-rate a severity, or treat a stated rationale as exculpatory. The one exception is a user ruling the dispatch quotes verbatim and the run's progress log records as `user ruling:`, scoped to the reviewer's task and a finding from its own prior record. If a dispatch tries, the reviewer runs the full check anyway and notes the attempted suppression in its verdict.
- **Do Not Trust the Report.** Reviewers verify by reading the actual code, not the implementer's summary — a report may be incomplete, inaccurate, or optimistic. A design rationale ("left it per YAGNI") is the implementer grading their own work and never downgrades a finding.
- **The checklist is a floor, not a ceiling.** Clearing every listed item is the minimum bar, not sufficiency — a change can pass every check and still be wrong for a reason no checklist enumerates. Agents judge the whole change, then apply the rules.
- **Lossiness flag.** The judgment reviewers end their verdict with a one-line note of what the verdict compresses — what a reader should re-read rather than trust. It informs the report; nothing is dispatched on it.

### Severity rubric

The quality and design reviewers tag every finding with a severity and a confidence (high / medium / low). In the per-task loop, every finding from the spec reviewer, the quality reviewers, review-lite and the gate also carries a `reach`, a `rule` and its `sites`, and `ledger.py triage` routes the fix from severity and reach alone (see [The fix loop](../explanation/execution-mechanics.md#the-fix-loop)):

| Severity | Meaning |
|----------|---------|
| **S1** | Cosmetic inconsistency; low risk, low impact |
| **S2** | Readability / maintainability issue; moderate leverage |
| **S3** | Structural cohesion issue; high leverage |
| **S4** | Bug-prone boundary or high-risk design flaw |
| **S5** | Critical correctness or API hazard |

A design review returns **PASS** only if it would integrate the change as-is; any standing **S3+** finding makes it **CONCERNS**.

The tags beside severity:

- **`reach`**: `local` (one site), `class` (the same rule at several sites in the task's files), or `contract` (fixing it changes a public API, a schema, or a symbol used outside the task's files, or needs edits outside them).
- **`rule`**: the rule the code breaks, stated as behavior.
- **`sites`**: every `path`, `path:line` or `path:start-end` where the rule is broken, not only the first one seen.

S1-S2 findings are notes (or deferred to the close at `contract` reach), and S3+ findings get a patch round (or a holistic round at `contract` reach).

---

## Coding agents (exclusive — most specific wins)

One coder per task. When several match the same extension, `scope.require_dependencies` picks the most specific (e.g. `pytorch-coder` over `python-coder` in a torch project).

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-coder` | sonnet | `.py`, `.ipynb` | General Python implementation |
| `pytorch-coder` | sonnet | `.py`, `.ipynb` (torch, lightning) | PyTorch/Lightning implementation |
| `rust-coder` | sonnet | `.rs` | Rust implementation |

Coders run on sonnet only. The orchestrator never raises a coder's model; the user can rule an opus coder for a task, and the stage's batched question offers one when a task escalates (see [Scope dispatch & models](scope-dispatch.md#model-selection)). A coder checks its own model before changing anything and returns `needs_context` when it runs above sonnet without that ruling.

Coders **internalize the review principles** so their code passes review on the first attempt — preserve behavior, clarity over cleverness, small reviewable steps, prefer deletion to invention, no speculative architecture. They follow `test-driven-development`, run the brief's `Verify:` command exactly (recorded as `tests.command`) and the project's linter, and self-review against the S3+ list before reporting. They implement and test every row the brief's `Cases:` line lists. When the brief leaves a behavior undefined they don't stop: they follow the nearest analogous case in the codebase and record an `open` entry (the question, the choice, and its `precedent` site, or `no precedent` with the reasoning), which the stage's batched question puts to you with the coder's choice as the default. A case they find that isn't listed is handled, tested, and reported as a `concerns` entry starting `unlisted case:`, a planning gap that doesn't on its own make the status `done_with_concerns`.

Crucially, a coder **reads the task's *intent* before the code** and builds toward the stated outcome, not just a passing diff. If a brief gives only *what* and *where* but no *why*, the coder **escalates for the intent** rather than guessing — one half of the loop that keeps intent flowing through dispatch (see [Context & dispatch](../explanation/context-and-dispatch.md)). Coders also escalate cross-language work and changes to foundational invariants before implementing. A public-API change the plan didn't specify is made and recorded as an open choice for the stage's batched question.

Coders also **mirror by reference rather than copy**: if a task needs a block a sibling already wrote, the coder hoists it into a shared helper when the owning file is already in its footprint, and otherwise declares a `duplication_pending` entry in its typed record so the orchestrator sees it in `ledger.py open` and assigns the hoist instead of letting the copy land. This is the coder-altitude link in the chain that keeps a fanned-out change coherent — see [Coherent change](../explanation/coherent-change.md#coherence-has-to-survive-decomposition).

**Fix mode.** A fix goes back to the original coder via `SendMessage` while it is reachable (a fresh dispatch at the same record path otherwise), with a `Fix baseline` tree and the task's file list. The coder first runs `ledger.py baseline` on it, which prints the round's kind (patch, holistic, ruling or polish), who re-checks it, its decision doc for a holistic round, and the findings sent, and returns `needs_context` if it errors or doesn't match the dispatch. Then, by round kind:

- **Patch or ruling.** For each finding the coder sweeps its rule: it searches the task's files and the consumers of every symbol the fix changes, and lists every site where the rule applies as a row mapped to the hunk that fixes it (or `already correct`, with evidence), recording the search it ran (`searched`) or what it inspected (`inspected`). For each S3+ finding it writes a failing test first and records the command and failing output, or an `n/a` with a category (`structural`, `docs`, `unreachable`, `existing`) and a reason. Notes in the dispatch are fixed or recorded in `notes_skipped` with a reason.
- **Holistic.** It implements the round's decision doc test-first, mapping every case in the doc to a hunk (`decision_rows`).
- **Any fix.** A finding it believes is wrong is recorded in `contested` (`wrong` or `plan-conflict`) with evidence instead of being fixed, and the raising reviewer answers it. A fix that turns out to need a contract change stops before making it and records `reach_raised`, so the next triage makes the task holistic. A site the rule reaches outside the task goes in `sites_outside`. An edit to an assertion in a pre-existing test, a deleted test, or an added skip marker needs a `test_changes` entry with the old and new text and the reason.

A consumer the fix breaks is part of the fix; one it can't change itself (another language) is marked `escalated` in `consumers_checked`, named in `concerns`, and returned as `done_with_concerns` so the orchestrator routes it. A coder that traces a problem to code its brief doesn't cover reports it as a `root cause: <path> <evidence>` concern, which triage routes to a holistic round. On any attempt, comments state behavior, never the review process: before reporting, the coder runs `ledger.py labels HEAD` on its files and rewrites each hit, listing a false positive in `concerns`. A hit the gate finds goes back as the same attempt, at the same `cycle`.

**Typed record (role `coder`).** Before returning, a coder writes a JSON record to its dispatch-supplied path: `status` (the same four values as the return summary, lowercase), `changed_files`, `tests` (command, pass/fail, one-line summary), `new_shared_symbols` it hoisted, `duplication_pending` sites it left un-hoisted, `concerns`, `model` (the model family it runs on; `check` refuses a finished record on any model but sonnet unless the user's opus ruling is logged for its task), `cycle` (self-derived: a fix re-dispatch points at the same record path, and the coder writes its prior record's cycle + 1), and the `report` path. From cycle 2 a `diagnosis` is required (`root_cause`, `end_state`, `resolves_cluster` — `check` enforces it): a fix states the cause it resolves before patching, and the re-reviewing agents judge it against that stated cause. A finished fix (`done` or `done_with_concerns`) also carries `hunk_map` (each hunk of the fix diff, read with `ledger.py diff-since <fix baseline> <task files>`, and the finding or choice it implements; empty only when the fix claims no hunk) `consumers_checked` (each changed symbol's consumers and how each was verified), and `baseline` (the `Fix baseline` tree its dispatch supplied), all enforced by `check`, which refuses a baseline with no fix-kind triage entry before its snapshot or one an earlier cycle of the record already used.

A fix also carries the round's evidence, each field optional and empty when unused: `sweeps` (per finding, the rule, the `rows` mapping each site to a hunk or to `already_correct`, and `searched` or `inspected` evidence, plus `sites_outside`), `tests_first` (per S3+ finding, the test, its command and its failing output, or an `n/a` with a category and reason), `decision_rows` (a holistic fix's cases mapped to hunks, beside its `decision` path), `open` (declared behavior choices), `contested`, `reach_raised`, `notes_skipped` and `test_changes`. On a finished fix, `check` requires every finding the round sent to appear in exactly one of `sweeps`, `contested`, `reach_raised` or (notes only) `notes_skipped`, every row's hunk to overlap the fix diff, every S3+ patch finding to have a `tests_first` entry, and every edited assertion, deleted test or added skip marker in a pre-existing test file to have a `test_changes` entry. It refuses a sweep with no search evidence, an `open` entry with no precedent or reason, and a `sites_outside` or `root cause:` path inside the task's own footprint. It then runs `ledger.py check` against its own record and fixes until clean — the write-time gate lands with the agent that has the context, not at the orchestrator's later query.

---

## Quality review agents (additive — all matching fire)

Dispatched per task **alongside** the spec reviewer; the orchestrator triages both verdicts once. Both rate a missing case by the brief's `Rigor:` level (`rigor.md`): below `heavy`, an esoteric case is S1-S2 and never starts a fix round, while a test that can't fail is S3 at every level. In a PyTorch project a `.py` file gets both `python-quality-reviewer` and `pytorch-quality-reviewer`; if they conflict, the more specific one wins.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-quality-reviewer` | opus | `.py`, `.ipynb` | General Python principle adherence + bug detection |
| `pytorch-quality-reviewer` | opus | `.py`, `.ipynb` (torch, lightning) | Lightning conventions + silent training bugs + reproducibility |
| `rust-quality-reviewer` | opus | `.rs` | Rust principle adherence + bug detection |

They verify the coder actually followed the principles it claims to internalize, catch bugs the coder missed, and validate test quality. They also check the project's CLAUDE.md constraints and public sentinel returns, the two checks a per-task review-lite pass used to carry. On a re-check they re-run recorded sweep commands, spot-check `inspected` lists, and judge tests-first `n/a` reasons and flagged test changes. They may search a changed symbol's consumers to tag reach. Their verdict is **APPROVED** or **REVISE** (with a specific fix list). The PyTorch reviewer additionally flags any change to loss computation, gradient flow, or the data pipeline, even when the code is correct, so the orchestrator can confirm it was intentional.

**Typed record (role `quality-reviewer`).** Before returning, the reviewer writes `status` (`approved | issues`, `issues` exactly when some finding is S3 or higher), `findings` (each with its severity as the S1–S5 integer, `reach`, `rule`, `sites` and claim, and `reopens` when it raises a settled finding again), `lossiness` (what the verdict compresses), `cycle` (self-derived on a re-review), and `recurring` (the fix-failure signal — see the spec-reviewer's record, same semantics) to its dispatch-supplied record path, then runs `ledger.py check` against it. On a re-check that was sent contests it also writes `contests`, one `concede` or `hold` answer with a reason per contest, and `check` refuses the record if one is missing. It judges the fix against the coder's stated `diagnosis`, not just the finding sites, against the fix diff rather than the coder's `hunk_map`, re-runs the coder's sweep searches and spot-checks its `inspected` lists, reads its `tests_first` and `test_changes`, and lists the fix's regressions in `introduced_by_fix` (see the spec-reviewer's record). Dispatched standalone, with no record path and no store artifacts, it skips the record and returns its review inline; a dispatch that carries store artifacts but lacks the record or scripts path is still refused as malformed.

---

## Review-lite agents (additive — all matching fire)

Dispatched as the whole-change gate at plan end, over the full `BASE..HEAD` diff, and usable standalone as a pre-commit guardrail. Inside the pipeline each task's commit is checked by the scripted `ledger.py gate` (labels, lint and the task's `Verify:` command) instead, so review-lite no longer runs per task.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-review-lite` | sonnet | `.py` | Trimmed idiom checklist + the project linter |
| `rust-review-lite` | sonnet | `.rs` | Trimmed idiom checklist + `cargo clippy -D warnings` |

These are fast, autonomous **regression guardrails**, not refactoring agents. They read `git diff --cached`, apply a diff-level idiom checklist, run the linter on the affected files, and return **clean / block / escalate**. At the whole-change gate its findings go through the same `ledger.py triage --task final` as a task's, with the same two-round bound. It tags each finding like the other reviewers, marking `contract` any symbol the diff shows as public (exported, no leading underscore, `pub`) and `local` or `class` otherwise, since it doesn't read neighbor files; the coder's `reach_raised` covers what it can't see. After a fix commits through `gate --task final`, it is re-dispatched at the same record path over a package of just the fix commit (after a patch) or the full diff (after a holistic round), and it reads its own prior record there and self-derives `cycle` as `prior + 1` (else `1`) — the dispatch carries no cycle counter. Standalone, at `cycle ≥ 3` with a block condition remaining (an S3+ finding or a failed linter) it escalates to break a stuck fix loop.

**Typed record (role `review-lite`).** Before returning, the agent writes `status` (`clean | block | escalate`), the self-derived `cycle`, `findings` (each with severity, `reach`, `rule` and `sites`), `linter` (ran, name, passed), and `verdict_path` (the existing markdown verdict file) to its dispatch-supplied record path, then runs `ledger.py check` against it. On a re-check at the whole-change gate it answers each contest with `concede` or `hold`, keeps a held finding byte-identical, and raises a settled finding again only with `reopens` and a site in lines changed since.

---

## Senior review agents (additive — all matching fire)

The heavyweight, read-only gate in `verification-before-completion`. They produce a **findings report** (architecture map, cohesion/drift findings, severity-tagged recommendations) and never edit code. The report is written to a dispatch-supplied path under the run store — the agent returns only `PASS | CONCERNS` plus the path, so the architecture analysis never lands in the orchestrator's context, a fix dispatch receives the findings by path, and a re-run reads its own prior report to judge whether findings were addressed. (An ad-hoc dispatch with no report path gets the report inline.)

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-design-reviewer` | opus | `.py`, `.ipynb` | Senior Python cohesion / API-design review → PASS / CONCERNS |
| `rust-design-reviewer` | opus | `.rs` | Senior Rust cohesion / API-design review → PASS / CONCERNS |

They recover architectural intent, then find the drift that debugging and deadline pressure introduce — modules doing too many things, utility/`helpers` dumping grounds, dict-shaped domain data crossing boundaries, hidden side effects in "pure-looking" helpers, mode-flag creep, public-API hazards. They are the read-only counterparts to the hands-on `python-review` / `rust-review` skills.

---

## Conformance agents (language-agnostic, dispatched explicitly)

Not scope-matched — these review conformance and behavior, not language idioms, so the skills dispatch them by name. Together they are the **conformance pair**: one catches code that drifted from the spec, the other catches a spec that drifted from the original ask.

| Agent | Model | Reference axis | Role |
|-------|-------|----------------|------|
| `spec-reviewer` | opus | the spec/brief | Per-task code↔spec conformance |
| `intent-reviewer` | opus | the intent ledger | **Spec-blind** behavior↔intent re-check at completion |

`spec-reviewer` verifies the implementer built what was requested — nothing more, nothing less — by reading the code line-by-line against the brief, and returns ✅ / ❌ / ⚠️ (cannot verify from diff). It also checks that every case on the brief's `Cases:` line has a test exercising the listed behavior: a listed case with no test is a `missing` issue, one implemented with different behavior is `misunderstood`. Each issue is tagged with its severity, reach, rule and every site of the rule within the task's changed files, not only the cited line, so the fix is held to the class. An issue that names a listed `Cases:` row (its `case` field) is S3 or higher. The reviewer doesn't raise a finding against a declared `open` choice for disagreeing with it, only when the choice contradicts an existing precedent. `intent-reviewer` is the only gate that **never reads the spec**: at completion it compares the *running system* to the frozen intent ledger and judges each statement `met` / `not-met` / `can't-tell`. Its independence comes precisely from that blindness — it catches the one failure every spec-anchored gate structurally cannot. See [The assurance model](../explanation/the-assurance-model.md).

**Typed record (role `spec-reviewer`).** Before returning, `spec-reviewer` writes `status` (`compliant | issues`, `issues` exactly when some issue is S3 or higher, so minor issues alone stay `compliant`), `issues` (kind `missing | extra | misunderstood | regression`, plus severity, reach, rule, sites, an optional `case` and `reopens`, and the claim; a `regression` is something the fix broke), `cannot_verify` (requirement, why, should_check — the typed form of the ⚠️ line), `cycle` (self-derived on a re-review, same pattern as review-lite), and `recurring` — the fix-failure signal: entries for findings whose class recurs at the same site as its prior cycle. `recurring` and `introduced_by_fix` (also on the quality reviewers' records) never change a finding's tier. They oblige the next fix to list the flagged sites as sweep rows, and they feed `stats`. `introduced_by_fix` lists problems the fix itself caused, on a line of the fix diff or in a consumer of a symbol it changed; each is also an ordinary finding. A re-check that was sent contests also carries `contests`, one `concede` or `hold` answer per contest, and `check` refuses a record that leaves one unanswered. A finding that was conceded, waived or ruled is settled, and the reviewer raises it again only with `reopens` and a site in lines changed since, which `check` verifies. It then runs `ledger.py check` against the record. `intent-reviewer` writes no typed record — it isn't one of the record-writing agents — but its prose re-check goes to a dispatch-supplied report path under the store (verdict word plus path returned), same as the design reviewers.

---

## Campaign agent

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `bug-hunter` | opus | per dispatch | Adversarial edge-case test writer dispatched by `bug-hunt`; never fixes |

Dispatched one-per-subsystem by the `bug-hunt` skill. Each instance writes edge-case tests (Python and/or Rust) for its subsystem, runs them, and reports failures as bugs — it writes tests, never fixes.

---

## Mutation gate agent

The mutation step of `verification-before-completion`, and a direct on-demand tool. One language-agnostic agent that uses **no external mutation-testing tool**.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `mutation-tester` | opus | any (source with tests) | Breaks changed code in an isolated worktree and runs the tests; gates on tests that don't detect the change |

**Inside an isolated worktree** (dispatched with the Agent tool's `isolation: "worktree"`) it deliberately breaks a piece of the changed code — flips a comparison, changes a boundary, drops a guard — runs the project's own tests, records whether any failed, and reverts the break before the next one. Nothing is installed and no framework is required, so it works in any language with a runnable suite, and it never touches the checkout you develop in. Two modes:

- **Closing-review mode** (Step 6 of the completion gate): scoped to the branch diff, or, in close round 2, to the `Range` it is handed (`<round-1 head>..HEAD`) so only the remediation's lines are mutated. It returns **CONCERNS** only when changed code is executed by a test yet no test fails when the code is broken — the precise signature of a trivial, non-discriminating test. Uncovered breaks (a *missing* test) and breaks it judges behavior-preserving (equivalent) are advisory or discarded, never blocking.
- **Rigor level** (closing-review only): the dispatch carries the project's rigor level, the plan path, and the files a plan task raised above it (`rigor.py --files`). Each file's level sets how many breaks it gets and which covered survivors gate: at `light`, a survivor gates when it changes behavior a `Cases:` row names (without a plan, when it sits in a function the change's tests call directly); at `standard`, when either holds. The rest are advisory. At `heavy` every covered survivor gates. A run where every file is `light` uses sonnet. The report states the level it applied to each file.
- **On-demand mode**: dispatched directly against a user-designated area, always advisory — a report of breaks the tests missed, no gating verdict.

Because it breaks committed state, the gate assumes the branch work is committed (the same assumption the diff-based design and intent gates make). A non-green baseline or a scope with nothing to mutate is a non-blocking skip.

## Grounding agent

Dispatched by `subagent-driven-development` to ground a judgment-shaped review finding, or to resolve a spec-reviewer `cannot_verify` item at repo scope, without the orchestrator reading the changed code itself. It writes no record — its inline answer is quotation, not a verdict, so it sits outside the typed-record roster deliberately.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `claim-checker` | haiku | any (read-only) | Answers one decidable claim and quotes the lines that settle it |

It returns `holds`, `does-not-hold`, or `not-decidable-by-reading`, always with 3 to 10 verbatim lines. Evidence is mandatory: a bare verdict word would be another laundering channel, which is the failure the agent exists to close. It forms no opinion about quality, correctness, or design, never suggests a fix, and never rates severity, so grounding informs how a finding is acted on without ever overturning it.

Its answer terminates the chain because it is quotation rather than conclusion, and raw evidence needs no grounding of its own. It is also the only agent whose read-only status is enforced rather than promised: its grant is `Read`, `Grep`, `Glob`, with no `Bash`, so unlike every other review agent it genuinely cannot write.

See [Scope dispatch & models](scope-dispatch.md) for how exclusive vs. additive vs. explicit dispatch resolves.
