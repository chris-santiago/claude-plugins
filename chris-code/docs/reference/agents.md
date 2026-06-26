# Agents

chris-code ships 13 dedicated agents — the layer superpowers doesn't have. They are dispatched automatically by file type and role; you rarely pick one by hand. All review agents are read-only on the checkout.

## Coding agents (exclusive — most specific wins)

One coder per task. When several match the same extension, `scope.require_dependencies` picks the most specific.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-coder` | sonnet | `.py` | General Python implementation with review principles inlined |
| `pytorch-coder` | sonnet | `.py` (torch, lightning) | PyTorch/Lightning implementation, Lightning conventions first |
| `rust-coder` | sonnet | `.rs` | Rust implementation with review principles inlined |

Coders read the task's *intent* before the code and build toward the stated outcome; they escalate if a brief gives only *what* and *where* but no *why*.

## Quality review agents (additive — all matching fire)

Dispatched per task after spec compliance passes.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-quality-reviewer` | opus | `.py` | General Python principle adherence + bug detection |
| `pytorch-quality-reviewer` | opus | `.py` (torch, lightning) | Lightning conventions + silent training bugs + reproducibility |
| `rust-quality-reviewer` | opus | `.rs` | Rust principle adherence + bug detection |

## Commit gate agents (additive — all matching fire)

Dispatched before each commit and as a final full-diff pass at plan end.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-review-lite` | inherit | `.py` | Idiom checklist + linter → clean / block / escalate |
| `rust-review-lite` | inherit | `.rs` | Idiom checklist + clippy → clean / block / escalate |

## Senior review agents (additive — all matching fire)

The heavyweight, read-only gate in `verification-before-completion`. Produce a findings report; never edit code.

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `python-design-reviewer` | opus | `.py` | Senior Python cohesion / API-design findings → PASS / CONCERNS |
| `rust-design-reviewer` | opus | `.rs` | Senior Rust cohesion / API-design findings → PASS / CONCERNS |

## Conformance agents (language-agnostic, dispatched explicitly)

Not scope-matched — these review conformance and behavior, not language idioms. Together they are the **conformance pair**: one catches code that drifted from the spec, the other catches a spec that drifted from the original ask.

| Agent | Model | Reference axis | Role |
|-------|-------|----------------|------|
| `spec-reviewer` | opus | the spec/brief | Per-task code↔spec conformance; "Do Not Trust the Report" |
| `intent-reviewer` | opus | the intent ledger | **Spec-blind** behavior↔intent re-check at completion; reads the frozen ledger + the running system, never the spec |

## Campaign agent

| Agent | Model | Scope | Role |
|-------|-------|-------|------|
| `bug-hunter` | inherit | per dispatch | Adversarial edge-case test writer dispatched by `bug-hunt`; never fixes |

See [Scope dispatch & models](scope-dispatch.md) for how exclusive vs. additive vs. explicit dispatch works.
