# Agents

chris-code ships 13 dedicated agents — the layer superpowers doesn't have. They auto-dispatch by file type and role, so you rarely pick one by hand. This page covers each agent and the disciplines they share.

## Shared review disciplines

Every review agent operates under the same rules, which is what makes the gates trustworthy:

- **Read-only on the checkout.** Reviewers never edit files or mutate the working tree, index, `HEAD`, or branch (no `git checkout/stash/reset/commit`). They report; the coder fixes. Bash is for read-only inspection and focused tests only.
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

Coders also **mirror by reference rather than copy**: if a task needs a block a sibling already wrote, the coder hoists it into a shared helper when the owning file is already in its footprint, and otherwise flags `DUPLICATION-PENDING` in its report so the orchestrator assigns the hoist instead of letting the copy land. This is the coder-altitude link in the chain that keeps a fanned-out change coherent — see [Coherent change](../explanation/coherent-change.md#coherence-has-to-survive-decomposition).

---

## Quality review agents (additive — all matching fire)

Dispatched per task **after** spec compliance passes. In a PyTorch project a `.py` file gets both `python-quality-reviewer` and `pytorch-quality-reviewer`; if they conflict, the more specific one wins.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-quality-reviewer` | opus | `.py`, `.ipynb` | General Python principle adherence + bug detection |
| `pytorch-quality-reviewer` | opus | `.py`, `.ipynb` (torch, lightning) | Lightning conventions + silent training bugs + reproducibility |
| `rust-quality-reviewer` | opus | `.rs` | Rust principle adherence + bug detection |

They verify the coder actually followed the principles it claims to internalize, catch bugs the coder missed, and validate test quality. Their verdict is **APPROVED** or **REVISE** (with a specific fix list). The PyTorch reviewer additionally flags any change to loss computation, gradient flow, or the data pipeline, even when the code is correct, so the orchestrator can confirm it was intentional.

---

## Commit gate agents (additive — all matching fire)

Dispatched before each commit and as a final full-diff pass at plan end.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-review-lite` | inherit | `.py` | Trimmed idiom checklist + the project linter |
| `rust-review-lite` | inherit | `.rs` | Trimmed idiom checklist + `cargo clippy -D warnings` |

These are fast, autonomous **regression guardrails**, not refactoring agents. They read `git diff --cached`, apply a diff-level idiom checklist, run the linter on the affected files, and return **clean / block / escalate**. When one blocks, the coder fixes and the agent is re-dispatched with an incrementing `cycle` counter; at `cycle ≥ 3` it escalates to break a stuck fix loop.

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

---

## Campaign agent

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `bug-hunter` | inherit | per dispatch | Adversarial edge-case test writer dispatched by `bug-hunt`; never fixes |

Dispatched one-per-subsystem by the `bug-hunt` skill. Each instance writes edge-case tests (Python and/or Rust) for its subsystem, runs them, and reports failures as bugs — it writes tests, never fixes.

See [Scope dispatch & models](scope-dispatch.md) for how exclusive vs. additive vs. explicit dispatch resolves.
