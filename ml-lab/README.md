# Agent Definitions

This directory contains reference copies of the Claude Code agents and skills that power the ml-lab investigation workflow.

## Agents

| File | Role | Spawned by |
|------|------|------------|
| `ml-lab.md` | Orchestrator — runs the full 12-step investigation | User / calling agent |
| `ml-critic.md` | Adversarial critic — finds flaws the PoC hasn't tested (Stage A.1) | `ml-lab` (Step 3: 1× in debate Stage A; 3× in ensemble mode) |
| `ml-critic-r2.md` | R2 challenger — issues ACCEPT/CHALLENGE/PARTIAL verdicts on defender rebuttals (Stage B.1) | `ml-lab` (Step 3: debate Stage B only) |
| `ml-defender.md` | Design defender — 7-type structured rebuttal taxonomy; concedes, rebuts, or defers (Stage A.2 and B.2) | `ml-lab` (Step 3 — **debate mode only**) |
| `research-reviewer.md` | Deep peer reviewer — Opus-class structured review of REPORT.md | `ml-lab` (Step 10, Round 1) |
| `research-reviewer-lite.md` | Verification reviewer — Haiku-class follow-up review | `ml-lab` (Step 10, Rounds 2–3) |
| `readme-rewriter.md` | Outside-reader README rewriter — diagnoses and rewrites for external audiences | `ml-lab` (Step 13) |
| `intent-monitor.md` | Pre-registration drift monitor — evaluates git changes in an experiment directory against binding constraints in a source-of-truth document; emits a clean-pass line or structured conflict report | `intent-watch` skill (user-invoked) |

All agents except `ml-lab` are subagents dispatched via the Agent tool. In **debate mode** (the default), `ml-critic` (Stage A.1) and `ml-defender` (Stage A.2) run once, followed by a convergence loop of `ml-critic-r2` (Stage B.1) and `ml-defender` (Stage B.2) up to max_rounds=4. In **ensemble mode** (opt-in), `ml-defender` and `ml-critic-r2` are not dispatched — three independent `ml-critic` dispatches with union pooling.

For installation instructions, invocation guide, workflow diagram, and agent interaction overview, see the [root README](../README.md#install).

## Skills

Skills are user-invocable slash commands that live in `skills/<name>/SKILL.md`.

| Skill | Invocation | Applicable to |
|-------|-----------|---------------|
| `intent-watch` | `/intent-watch <experiment_dir> <source_of_truth>` | **Gate 1 (mandatory):** run once before Step 6 begins — must return a clean pass; any HIGH or CRITICAL conflict blocks the experiment. **Step 6 (active loop):** run `/loop 2m /intent-watch <experiment_dir> HYPOTHESIS.md` during scripting to catch pre-registration drift immediately. Not useful before `HYPOTHESIS.md` exists or after the experiment is complete. |
| `deep-dive` | `/deep-dive [experiment_path]` | After any investigation phase or full run is complete. Surveys scripts, results schemas, journal decisions, and existing docs to produce `DEEP_DIVE.md` — a comprehensive technical reference covering data construction, model architecture, scoring mechanics, statistical methods, per-test detail, quality gates, aggregation, and key design decisions with sources cited. Works with or without a project journal; degrades gracefully when artifacts are missing. |

## What these copies are

These are sanitized reference copies. Two changes were made from the originals before committing here:

1. **Memory path generalized** — the original references a hardcoded user home directory path for agent memory. The reference copy uses `~/.claude/agent-memory/ml-lab/` so it works for any installer.
2. **`memory: user` scope removed** — the original grants the agent access to the global user memory system. The reference copy removes this, scoping the agent to its own memory directory only. Add `memory: user` back to your local copy if you want cross-project memory access.
