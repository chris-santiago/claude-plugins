# Agents

chris-code ships 15 dedicated agents — the layer superpowers doesn't have. They auto-dispatch by file type and role, so you rarely pick one by hand. This page covers each agent and the disciplines they share.

## Typed records

Every record-writing agent — coders, `spec-reviewer`, the quality reviewers, the review-lite agents — writes its JSON record to a dispatch-supplied path, never one it computes itself. The naming convention behind that path: `task-<N>-<agent-name>.json`, keyed by the agent's registered name rather than its role, so additive same-role agents (e.g. both quality reviewers firing on one PyTorch task) never collide. The whole-change commit gate, which has no task number, uses `final-<agent-name>.json` instead, and such records carry `"task": "final"`. The completion close extends that stem: a close-gate remediation run's whole-change gate uses `final-r2-<agent-name>.json` (so it doesn't inherit the original gate's cycle), a close round's test-only fix and the commit gate on its inline fixes use `final-close-r<N>-<agent-name>.json`, and a fix from your ruling after round 2 (and its commit gate) uses `final-close-ruling-<agent-name>.json`. In every case the dispatch-supplied path defines record identity; these stems are the convention the orchestrator follows when computing it, not something an agent works out on its own. Each role's payload contract is documented under its own section, below.

## Shared review disciplines

Every review agent operates under the same rules, which is what makes the gates trustworthy:

- **Read-only on the checkout, aside from one handoff write.** Reviewers never edit files or mutate the working tree, index, `HEAD`, or branch (no `git checkout/stash/reset/commit`). They report; the coder fixes. Bash is for read-only inspection and focused tests only. The one write every reviewer performs is its own handoff artifact at a dispatch-supplied path in the run's store (`.sdd/` at the repo toplevel, self-ignored): a typed record (validated with `ledger.py check` until clean) for the per-task reviewers, a report file for the gate reviewers (design reviewers, intent-reviewer).
- **Instruction precedence.** The dispatch supplies inputs, not authority. No instruction in a dispatch can waive a review, soften a finding, pre-rate a severity, or treat a stated rationale as exculpatory. If one tries, the reviewer runs the full check anyway and notes the attempted suppression in its verdict.
- **Do Not Trust the Report.** Reviewers verify by reading the actual code, not the implementer's summary — a report may be incomplete, inaccurate, or optimistic. A design rationale ("left it per YAGNI") is the implementer grading their own work and never downgrades a finding.
- **The checklist is a floor, not a ceiling.** Clearing every listed item is the minimum bar, not sufficiency — a change can pass every check and still be wrong for a reason no checklist enumerates. Agents judge the whole change, then apply the rules.
- **Lossiness flag.** The judgment reviewers end their verdict with a one-line note of what the verdict compresses — what the orchestrator should ground first (by `claim-checker` dispatch) rather than trust the summary.

### Severity rubric

The quality and design reviewers tag every finding with a severity and a confidence (high / medium / low):

| Severity | Meaning |
|----------|---------|
| **S1** | Cosmetic inconsistency; low risk, low impact |
| **S2** | Readability / maintainability issue; moderate leverage |
| **S3** | Structural cohesion issue; high leverage |
| **S4** | Bug-prone boundary or high-risk design flaw |
| **S5** | Critical correctness or API hazard |

A design review returns **PASS** only if it would integrate the change as-is; any standing **S3+** finding makes it **CONCERNS**.

---

## Coding agents (exclusive — most specific wins)

One coder per task. When several match the same extension, `scope.require_dependencies` picks the most specific (e.g. `pytorch-coder` over `python-coder` in a torch project).

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-coder` | sonnet | `.py`, `.ipynb` | General Python implementation |
| `pytorch-coder` | sonnet | `.py`, `.ipynb` (torch, lightning) | PyTorch/Lightning implementation |
| `rust-coder` | sonnet | `.rs` | Rust implementation |

Coders **internalize the review principles** so their code passes the lite-review gate on the first attempt — preserve behavior, clarity over cleverness, small reviewable steps, prefer deletion to invention, no speculative architecture. They follow `test-driven-development`, run the project's tests and linter, and self-review against the S3+ list before reporting. They implement and test every case the brief's `Cases:` line lists. A case they find that isn't listed is handled, tested, and reported as a `concerns` entry starting `unlisted case:`, a planning gap that doesn't on its own make the status `done_with_concerns`.

Crucially, a coder **reads the task's *intent* before the code** and builds toward the stated outcome, not just a passing diff. If a brief gives only *what* and *where* but no *why*, the coder **escalates for the intent** rather than guessing — one half of the loop that keeps intent flowing through dispatch (see [Context & dispatch](../explanation/context-and-dispatch.md)). Coders also escalate public-API changes, cross-language work, and changes to foundational invariants before implementing.

Coders also **mirror by reference rather than copy**: if a task needs a block a sibling already wrote, the coder hoists it into a shared helper when the owning file is already in its footprint, and otherwise declares a `duplication_pending` entry in its typed record so the orchestrator sees it in `ledger.py open` and assigns the hoist instead of letting the copy land. This is the coder-altitude link in the chain that keeps a fanned-out change coherent — see [Coherent change](../explanation/coherent-change.md#coherence-has-to-survive-decomposition).

**Fix mode.** A fix goes back to the original coder via `SendMessage` while it is reachable (a fresh dispatch at the same record path otherwise), with a `Fix baseline` tree and the task's file list. On a fix the coder covers every input and site in each finding's class, not just the cited line, and, when the batch has any non-trivial finding, also self-reviews the fix diff against the matching quality reviewer's contract, which the dispatch supplies as the checklist the fix will be judged by. A consumer the fix breaks is part of the fix; one it can't change itself (another language, or a public-API change) is marked `escalated` in `consumers_checked`, named in `concerns`, and returned as `done_with_concerns` so the orchestrator routes it.

**Typed record (role `coder`).** Before returning, a coder writes a JSON record to its dispatch-supplied path: `status` (the same four values as the return summary, lowercase), `changed_files`, `tests` (command, pass/fail, one-line summary), `new_shared_symbols` it hoisted, `duplication_pending` sites it left un-hoisted, `concerns`, `cycle` (self-derived: a fix re-dispatch points at the same record path, and the coder writes its prior record's cycle + 1), and the `report` path. From cycle 2 a `diagnosis` is required (`root_cause`, `end_state`, `resolves_cluster` — `check` enforces it): a fix states the cause it resolves before patching, and the re-reviewing agents judge it against that stated cause. A finished fix (`done` or `done_with_concerns`) also carries `hunk_map` (each hunk of the fix diff, read with `ledger.py diff-since <fix baseline> <task files>`, and the finding or choice it implements; at least one entry) and `consumers_checked` (each changed symbol's consumers and how each was verified), both enforced by `check`. It then runs `ledger.py check` against its own record and fixes until clean — the write-time gate lands with the agent that has the context, not at the orchestrator's later query.

---

## Quality review agents (additive — all matching fire)

Dispatched per task **alongside** the spec reviewer; the orchestrator triages both verdicts once. In a PyTorch project a `.py` file gets both `python-quality-reviewer` and `pytorch-quality-reviewer`; if they conflict, the more specific one wins.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-quality-reviewer` | opus | `.py`, `.ipynb` | General Python principle adherence + bug detection |
| `pytorch-quality-reviewer` | opus | `.py`, `.ipynb` (torch, lightning) | Lightning conventions + silent training bugs + reproducibility |
| `rust-quality-reviewer` | opus | `.rs` | Rust principle adherence + bug detection |

They verify the coder actually followed the principles it claims to internalize, catch bugs the coder missed, and validate test quality. Their verdict is **APPROVED** or **REVISE** (with a specific fix list). The PyTorch reviewer additionally flags any change to loss computation, gradient flow, or the data pipeline, even when the code is correct, so the orchestrator can confirm it was intentional.

**Typed record (role `quality-reviewer`).** Before returning, the reviewer writes `status` (`approved | issues`), `findings` (severity as the S1–S5 integer, file, line, claim), `lossiness` (what the verdict compresses), `cycle` (self-derived on a re-review), and `recurring` (the fix-failure signal — see the spec-reviewer's record, same semantics) to its dispatch-supplied record path, then runs `ledger.py check` against it. On a re-review it also judges the fix against the coder's stated `diagnosis`, not just the finding sites, checks `hunk_map` and `consumers_checked` against the fix diff, and lists the fix's regressions in `introduced_by_fix` (see the spec-reviewer's record).

---

## Commit gate agents (additive — all matching fire)

Dispatched before each commit and as a final full-diff pass at plan end.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-review-lite` | inherit | `.py` | Trimmed idiom checklist + the project linter |
| `rust-review-lite` | inherit | `.rs` | Trimmed idiom checklist + `cargo clippy -D warnings` |

These are fast, autonomous **regression guardrails**, not refactoring agents. They read `git diff --cached`, apply a diff-level idiom checklist, run the linter on the affected files, and return **clean / block / escalate**. When one blocks, the coder fixes and the agent is re-dispatched at the same record path; it reads its own prior record there and self-derives `cycle` as `prior + 1` (else `1`) — the dispatch carries no cycle counter. At `cycle ≥ 3` with a block condition remaining (an S3+ finding or a failed linter) it escalates to break a stuck fix loop.

**Typed record (role `review-lite`).** Before returning, the agent writes `status` (`clean | block | escalate`), the self-derived `cycle`, `findings`, `linter` (ran, name, passed), and `verdict_path` (the existing markdown verdict file) to its dispatch-supplied record path, then runs `ledger.py check` against it.

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

`spec-reviewer` verifies the implementer built what was requested — nothing more, nothing less — by reading the code line-by-line against the brief, and returns ✅ / ❌ / ⚠️ (cannot verify from diff). It also checks that every case on the brief's `Cases:` line has a test exercising the listed behavior: a listed case with no test is a `missing` issue, one implemented with different behavior is `misunderstood`. Each issue names its rule and the whole class it covers within the task's changed files, not only the cited line, so the fix is held to the class. `intent-reviewer` is the only gate that **never reads the spec**: at completion it compares the *running system* to the frozen intent ledger and judges each statement `met` / `not-met` / `can't-tell`. Its independence comes precisely from that blindness — it catches the one failure every spec-anchored gate structurally cannot. See [The assurance model](../explanation/the-assurance-model.md).

**Typed record (role `spec-reviewer`).** Before returning, `spec-reviewer` writes `status` (`compliant | issues`), `issues` (kind `missing | extra | misunderstood | regression`, file, line, claim; a `regression` is something the fix broke), `cannot_verify` (requirement, why, should_check — the typed form of the ⚠️ line), `cycle` (self-derived on a re-review, same pattern as review-lite), and `recurring` — the fix-failure signal: entries for findings whose class recurs at the same site as its prior cycle. A non-empty `recurring` (also on the quality reviewers' records) tells the orchestrator patching has failed: the next fix dispatch must carry a defended mechanism choice. `introduced_by_fix` (also on the quality reviewers' records) lists problems the fix itself caused, on a line of the fix diff or in a consumer of a symbol it changed; each is also an ordinary finding, and a non-empty list marks a failed fix. It is validated when present and tolerated when absent, so records from before 0.6.0 still pass. It then runs `ledger.py check` against the record. `intent-reviewer` writes no typed record — it isn't one of the record-writing agents — but its prose re-check goes to a dispatch-supplied report path under the store (verdict word plus path returned), same as the design reviewers.

---

## Campaign agent

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `bug-hunter` | inherit | per dispatch | Adversarial edge-case test writer dispatched by `bug-hunt`; never fixes |

Dispatched one-per-subsystem by the `bug-hunt` skill. Each instance writes edge-case tests (Python and/or Rust) for its subsystem, runs them, and reports failures as bugs — it writes tests, never fixes.

---

## Mutation gate agent

The mutation step of `verification-before-completion`, and a direct on-demand tool. One language-agnostic agent that uses **no external mutation-testing tool**.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `mutation-tester` | opus | any (source with tests) | Breaks changed code in an isolated worktree and runs the tests; gates on tests that don't detect the change |

**Inside an isolated worktree** (dispatched with the Agent tool's `isolation: "worktree"`) it deliberately breaks a piece of the changed code — flips a comparison, changes a boundary, drops a guard — runs the project's own tests, records whether any failed, and reverts the break before the next one. Nothing is installed and no framework is required, so it works in any language with a runnable suite, and it never touches the checkout you develop in. Two modes:

- **Closing-review mode** (Step 6 of the completion gate): scoped to the branch diff, or, in close round 2, to the `Range` it is handed (`<round-1 head>..HEAD`) so only the remediation's lines are mutated. It returns **CONCERNS** only when changed code is executed by a test yet no test fails when the code is broken — the precise signature of a trivial, non-discriminating test. Uncovered breaks (a *missing* test) and breaks it judges behavior-preserving (equivalent) are advisory or discarded, never blocking.
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
