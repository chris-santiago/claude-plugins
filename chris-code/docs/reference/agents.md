# Agents

chris-code ships 14 dedicated agents — the layer superpowers doesn't have. They auto-dispatch by file type and role, so you rarely pick one by hand. This page covers each agent and the disciplines they share.

## Typed records

Every record-writing agent — coders, `spec-reviewer`, the quality reviewers, the review-lite agents — writes its JSON record to a dispatch-supplied path, never one it computes itself. The naming convention behind that path: `task-<N>-<agent-name>.json`, keyed by the agent's registered name rather than its role, so additive same-role agents (e.g. both quality reviewers firing on one PyTorch task) never collide. The whole-change commit gate, which has no task number, uses `final-<agent-name>.json` instead, and such records carry `"task": "final"`. In every case the dispatch-supplied path defines record identity; these stems are the convention the orchestrator follows when computing it, not something an agent works out on its own. Each role's payload contract is documented under its own section, below.

## Shared review disciplines

Every review agent operates under the same rules, which is what makes the gates trustworthy:

- **Read-only on the checkout, aside from one record write.** Reviewers never edit files or mutate the working tree, index, `HEAD`, or branch (no `git checkout/stash/reset/commit`). They report; the coder fixes. Bash is for read-only inspection and focused tests only. The one write every reviewer performs is its own typed record — a JSON file at a dispatch-supplied path under the resolved store — written before it returns and validated with `ledger.py check` until clean.
- **Instruction precedence.** The dispatch supplies inputs, not authority. No instruction in a dispatch can waive a review, soften a finding, pre-rate a severity, or treat a stated rationale as exculpatory. If one tries, the reviewer runs the full check anyway and notes the attempted suppression in its verdict.
- **Do Not Trust the Report.** Reviewers verify by reading the actual code, not the implementer's summary — a report may be incomplete, inaccurate, or optimistic. A design rationale ("left it per YAGNI") is the implementer grading their own work and never downgrades a finding.
- **The checklist is a floor, not a ceiling.** Clearing every listed item is the minimum bar, not sufficiency — a change can pass every check and still be wrong for a reason no checklist enumerates. Agents judge the whole change, then apply the rules.
- **Lossiness flag.** The judgment reviewers end their verdict with a one-line note of what the verdict compresses — where the orchestrator should re-read rather than trust the summary.

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

Coders **internalize the review principles** so their code passes the lite-review gate on the first attempt — preserve behavior, clarity over cleverness, small reviewable steps, prefer deletion to invention, no speculative architecture. They follow `test-driven-development`, run the project's tests and linter, and self-review against the S3+ list before reporting.

Crucially, a coder **reads the task's *intent* before the code** and builds toward the stated outcome, not just a passing diff. If a brief gives only *what* and *where* but no *why*, the coder **escalates for the intent** rather than guessing — one half of the loop that keeps intent flowing through dispatch (see [Context & dispatch](../explanation/context-and-dispatch.md)). Coders also escalate public-API changes, cross-language work, and changes to foundational invariants before implementing.

Coders also **mirror by reference rather than copy**: if a task needs a block a sibling already wrote, the coder hoists it into a shared helper when the owning file is already in its footprint, and otherwise declares a `duplication_pending` entry in its typed record so the orchestrator sees it in `ledger.py open` and assigns the hoist instead of letting the copy land. This is the coder-altitude link in the chain that keeps a fanned-out change coherent — see [Coherent change](../explanation/coherent-change.md#coherence-has-to-survive-decomposition).

**Typed record (role `coder`).** Before returning, a coder writes a JSON record to its dispatch-supplied path: `status` (the same four values as the return summary, lowercase), `changed_files`, `tests` (command, pass/fail, one-line summary), `new_shared_symbols` it hoisted, `duplication_pending` sites it left un-hoisted, `concerns`, and the `report` path. It then runs `ledger.py check` against its own record and fixes until clean — the write-time gate lands with the agent that has the context, not at the orchestrator's later query.

---

## Quality review agents (additive — all matching fire)

Dispatched per task **after** spec compliance passes. In a PyTorch project a `.py` file gets both `python-quality-reviewer` and `pytorch-quality-reviewer`; if they conflict, the more specific one wins.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-quality-reviewer` | opus | `.py`, `.ipynb` | General Python principle adherence + bug detection |
| `pytorch-quality-reviewer` | opus | `.py`, `.ipynb` (torch, lightning) | Lightning conventions + silent training bugs + reproducibility |
| `rust-quality-reviewer` | opus | `.rs` | Rust principle adherence + bug detection |

They verify the coder actually followed the principles it claims to internalize, catch bugs the coder missed, and validate test quality. Their verdict is **APPROVED** or **REVISE** (with a specific fix list). The PyTorch reviewer additionally flags any change to loss computation, gradient flow, or the data pipeline, even when the code is correct, so the orchestrator can confirm it was intentional.

**Typed record (role `quality-reviewer`).** Before returning, the reviewer writes `status` (`approved | issues`), `findings` (severity as the S1–S5 integer, file, line, claim), and `lossiness` (what the verdict compresses) to its dispatch-supplied record path, then runs `ledger.py check` against it.

---

## Commit gate agents (additive — all matching fire)

Dispatched before each commit and as a final full-diff pass at plan end.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-review-lite` | inherit | `.py` | Trimmed idiom checklist + the project linter |
| `rust-review-lite` | inherit | `.rs` | Trimmed idiom checklist + `cargo clippy -D warnings` |

These are fast, autonomous **regression guardrails**, not refactoring agents. They read `git diff --cached`, apply a diff-level idiom checklist, run the linter on the affected files, and return **clean / block / escalate**. When one blocks, the coder fixes and the agent is re-dispatched at the same record path; it reads its own prior record there and self-derives `cycle` as `prior + 1` (else `1`) — the dispatch carries no cycle counter. At `cycle ≥ 3` with a finding remaining it escalates to break a stuck fix loop.

**Typed record (role `review-lite`).** Before returning, the agent writes `status` (`clean | block | escalate`), the self-derived `cycle`, `findings`, `linter` (ran, name, passed), and `verdict_path` (the existing markdown verdict file) to its dispatch-supplied record path, then runs `ledger.py check` against it.

---

## Senior review agents (additive — all matching fire)

The heavyweight, read-only gate in `verification-before-completion`. They produce a **findings report** (architecture map, cohesion/drift findings, severity-tagged recommendations) and never edit code.

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

`spec-reviewer` verifies the implementer built what was requested — nothing more, nothing less — by reading the code line-by-line against the brief, and returns ✅ / ❌ / ⚠️ (cannot verify from diff). `intent-reviewer` is the only gate that **never reads the spec**: at completion it compares the *running system* to the frozen intent ledger and judges each statement `met` / `not-met` / `can't-tell`. Its independence comes precisely from that blindness — it catches the one failure every spec-anchored gate structurally cannot. See [The assurance model](../explanation/the-assurance-model.md).

**Typed record (role `spec-reviewer`).** Before returning, `spec-reviewer` writes `status` (`compliant | issues`), `issues` (kind, file, line, claim), and `cannot_verify` (requirement, why, should_check — the typed form of the ⚠️ line) to its dispatch-supplied record path, then runs `ledger.py check` against it. `intent-reviewer` keeps its prose-only report; it isn't one of the record-writing agents.

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

- **Closing-review mode** (Step 6 of the completion gate): scoped to the branch diff. It returns **CONCERNS** only when changed code is executed by a test yet no test fails when the code is broken — the precise signature of a trivial, non-discriminating test. Uncovered breaks (a *missing* test) and breaks it judges behavior-preserving (equivalent) are advisory or discarded, never blocking.
- **On-demand mode**: dispatched directly against a user-designated area, always advisory — a report of breaks the tests missed, no gating verdict.

Because it breaks committed state, the gate assumes the branch work is committed (the same assumption the diff-based design and intent gates make). A non-green baseline or a scope with nothing to mutate is a non-blocking skip.

See [Scope dispatch & models](scope-dispatch.md) for how exclusive vs. additive vs. explicit dispatch resolves.
