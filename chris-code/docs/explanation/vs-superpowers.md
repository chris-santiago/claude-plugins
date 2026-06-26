# Relationship to superpowers

chris-code branched from [obra/superpowers](https://github.com/obra/superpowers) **v5.1.0** and has since selectively backported mechanisms from **v6.0.0** (file handoffs, pre-flight plan review, a durable progress ledger, reviewer-integrity rules). If you know superpowers, you already know most of chris-code: the same brainstorm → plan → execute → review → finish pipeline, most of the same skill names, the same TDD and systematic-debugging discipline. This page covers what changed and why.

## Five shifts

1. **Lean artifacts over exhaustive ones.** superpowers' plans documented everything "as if the engineer has zero context," with full code in every step — which implementing agents discarded and rewrote. chris-code adopts *"contracts stay, choreography goes"*: specs capture invariants, plans capture what and where, code is written against the real repo.

2. **A real agent layer, dispatched by scope.** superpowers is skills-only, dispatching generic subagents steered by prompt templates. chris-code ships 13 dedicated agents that auto-dispatch by file extension and project dependencies — you describe the task, the routing is mechanical.

3. **Review is a uniform, multi-stage gate.** superpowers' two-stage review (spec, then quality) is kept and hardened: the reviewers are dedicated scope-dispatched agents, lint becomes its own mandatory gate, a commit-lite idiom check runs pre-commit, and a final full-diff pass catches cross-task drift. A later pass added the [assurance hardening](the-assurance-model.md) — the spec-blind intent re-check, the conformance pair, and honest accounting of what the gates prove.

4. **Parallelism is a feature, not a footgun.** superpowers lists parallel implementers as a Red Flag (they collide). chris-code maps each task's file footprint up front, groups non-overlapping tasks into stages, and runs each stage concurrently — safety by scheduling, not prohibition.

5. **Native tools first, with a hard gate.** Both prefer native worktree tools. Where superpowers falls back to a manual `git worktree` when none exists, chris-code stops and warns — a silent fallback once caused real damage.

## What stayed the same

`brainstorming`, `test-driven-development`, `systematic-debugging`, `finishing-a-development-branch`, and the session-start discovery skill carry over essentially unchanged (renames and diagram-format swaps aside). chris-code is a **true superset**: every superpowers skill is present, plus 11 new skills and a 13-agent layer.

A fuller side-by-side, including the receipts, lives in the repository's [`superpowers-comparison.md`](https://github.com/chris-santiago/claude-plugins/blob/main/chris-code/assets/decks/superpowers-comparison.md).
