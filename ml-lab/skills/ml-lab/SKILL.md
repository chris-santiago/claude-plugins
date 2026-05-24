---
name: ml-lab
description: Start a structured ML hypothesis investigation — adversarial critique, empirical testing, peer review, and coherence audit
---

This skill guides you through a rigorous ML hypothesis investigation workflow (12 core steps plus optional Steps 11 and 13). Drive the user's ML hypothesis from minimal proof-of-concept through multi-round adversarial debate (default) or ensemble critique, empirical resolution, production re-evaluation, peer review, and coherence verification — producing a concrete artifact at each step.

All steps run in this session. Dispatch subagents via the Agent tool only for: Steps 3–5 (`ml-critic` and `ml-critic-r2` in debate mode; `ml-critic` only in ensemble mode; `ml-defender` in debate mode only), Steps 8 and 11 (`report-writer`), Step 10 (`research-reviewer` and `research-reviewer-lite`), and Step 13 (`readme-rewriter`). Steps 11 and 13 are optional and only run on explicit user confirmation.

---

## Before You Begin

Ask the user for four things before writing any code:

**1. The hypothesis:**
> "State your hypothesis as a specific, falsifiable claim. Name the mechanism, the signal, and the expected observable. Example: 'X trained on Y will produce Z, which creates detectable signal W.'"

Do not proceed until you have a hypothesis in this form. If the user's hypothesis is vague, help them sharpen it first.

**2. The primary evaluation metric(s):**
Based on the hypothesis, suggest two or three candidate metrics with a brief rationale for each. Then ask the user to confirm or override. Examples of how to reason about this:
- Binary classification tasks → AUC-ROC, average precision
- Precision-critical deployments → precision@K, FPR at fixed TPR
- Ranking or scoring tasks → NDCG, Spearman rank correlation
- Clustering or representation quality → silhouette score, Davies–Bouldin index
- Regression targets → RMSE, MAE, R²

**3. Report mode:**
Ask: *"Do you want a full report or just conclusions?"*

- **Full report** (`full_report`) — runs Steps 1–10 and 12: PoC → debate → experiments → conclusions → production re-evaluation → report (`REPORT.md`) → peer review loop → coherence audit. Optional Steps 11 (technical report) and 13 (README rewrite) follow on user confirmation. Default if the user doesn't specify.
- **Conclusions only** (`conclusions_only`) — runs Steps 1–7 and Step 9 only. Stops after `CONCLUSIONS.md` and `REPORT_ADDENDUM.md`. Skips Step 8 (report writing), Step 10 (peer review), and Step 12 (coherence audit). Optional Step 13 (README rewrite) still available on user confirmation.

Record the mode as `report_mode` and carry it through the investigation. Do not ask again.

**4. Review mode:**
Ask: *"Review mode: debate (structured multi-round critic-defender — default) or ensemble (3 independent critics — high-recall sweep)?"*

- **Debate** (`debate`) — **Default.** Runs the structured 4-stage multi-round protocol: ml-critic R1 → ml-defender R1 → ml-critic-r2 (challenge) → ml-defender R2 → `derive_verdict()`. Produces a deterministic, structured verdict (`defense_wins` / `empirical_test_agreed` / `critique_wins`) with per-finding severity adjustments and rebuttal justifications. The protocol is calibrated to correctly handle clean designs (defense_wins), ambiguous designs (ETA), and designs with undeniable flaws (critique_wins). For go/no-go decisions on a hypothesis, this is the recommended path.
- **Ensemble** (`ensemble`) — runs 3 independent `ml-critic` dispatches on the same PoC with no cross-visibility between them. Issues are pooled by union and tier-weighted by assessor support count (3/3 > 2/3 > 1/3); 1/3 minority findings require explicit user confirmation before entering experiment design. Use when you want a comprehensive finding sweep and will triage issues manually. No structured verdict output — the orchestrator aggregates findings but does not produce defense_wins / ETA / critique_wins.

Record the mode as `review_mode` and carry it through the investigation. Do not ask again.

**5. Write `HYPOTHESIS.md`:**
Once the hypothesis and metrics are agreed, write `HYPOTHESIS.md`. This is the canonical source of truth for the entire investigation. Structure:

```markdown
## Hypothesis — Cycle 1

**Claim:** [the falsifiable claim]
**Mechanism:** [how/why this is expected to work]
**Signal:** [the observable signal the model exploits]
**Expected observable:** [what a successful test looks like]

## Evaluation Metrics

**Primary:** [metric(s) with rationale]
**Domain:** [short domain name for file naming]
```

If the hypothesis is revised during a macro-iteration, append a new section (`## Hypothesis — Cycle N`) documenting what changed and why. Previous versions are preserved — the revision history is part of the record.

---

## Investigation Log

Maintain `INVESTIGATION_LOG.jsonl` throughout the investigation. This is an append-only audit trail of every action — file reads, file writes, subagent dispatches, code executions, user gates, decisions, debate rounds, corrections, audit checks. If in doubt whether to log an action, log it.

**Format:** JSONL via `log_entry.py`. **Never write log entries manually.** Schema compliance and seq monotonicity are enforced by the script — manual `echo` writes skip validation and produce inconsistent logs.

**Setup (do this once, immediately after writing HYPOTHESIS.md):** Create `log_entry.py` in the investigation directory:

```python
# log_entry.py
# /// script
# requires-python = ">=3.10"
# ///
"""
Structured INVESTIGATION_LOG.jsonl entry writer.
Enforces schema compliance, validates cat, auto-increments seq, auto-generates ts.
Usage: uv run log_entry.py --step 3 --cat subagent --action dispatch_critic --detail "..." [--artifact X] [--duration_s Y] [--meta '{"k":"v"}']
NEVER write log entries manually. Always use this script.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_CATS = {'gate', 'write', 'read', 'subagent', 'exec', 'decision', 'debate', 'review', 'audit', 'workflow'}

parser = argparse.ArgumentParser()
parser.add_argument('--step', required=True)
parser.add_argument('--cat', required=True, choices=sorted(ALLOWED_CATS))
parser.add_argument('--action', required=True)
parser.add_argument('--detail', required=True)
parser.add_argument('--artifact', default=None)
parser.add_argument('--duration_s', type=float, default=None)
parser.add_argument('--meta', default='{}')
args = parser.parse_args()

try:
    meta = json.loads(args.meta)
except json.JSONDecodeError as e:
    print(f"ERROR: --meta must be valid JSON: {e}", file=sys.stderr)
    sys.exit(1)

log_file = Path('INVESTIGATION_LOG.jsonl')
seq = 1
if log_file.exists():
    lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    if lines:
        try:
            seq = json.loads(lines[-1]).get('seq', 0) + 1
        except Exception:
            seq = len(lines) + 1

entry = {
    'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'step': args.step, 'seq': seq, 'cat': args.cat,
    'action': args.action, 'detail': args.detail,
    'artifact': args.artifact, 'duration_s': args.duration_s, 'meta': meta,
}
with open(log_file, 'a') as f:
    f.write(json.dumps(entry) + '\n')
print(f"[seq={seq}] {args.cat}/{args.action}: {args.detail}")
```

All log entries are written as:
```bash
uv run log_entry.py --step 3 --cat subagent --action dispatch_critic \
  --detail "Initial critique mode — reading HYPOTHESIS.md, churn_poc.py, README.md" \
  --artifact CRITIQUE.md --meta '{"critique_points": 7}'
```

**Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `ts` | ISO 8601 | yes | Timestamp via `date -u +%Y-%m-%dT%H:%M:%SZ` |
| `step` | string | yes | Current step: `"pre"`, `"1"`–`"13"`, `"final"`. Substeps: `"5.R2"` (debate round 2), `"6-7.I2"` (micro-iter 2), `"C2"` (macro cycle 2) |
| `seq` | integer | yes | Monotonically increasing from 1 |
| `cat` | string | yes | Category code from table below |
| `action` | string | yes | Descriptive verb_noun name |
| `detail` | string | yes | One-sentence description of what happened |
| `artifact` | string/null | no | Filename produced or consumed |
| `duration_s` | number/null | no | Seconds elapsed for exec/subagent actions |
| `meta` | object | no | Structured extras (counts, metrics, verdicts) |

**Category codes:**

| `cat` | Scope |
|---|---|
| `gate` | User prompts, approvals, confirmations, declines |
| `write` | File creation or modification |
| `read` | File reads for analysis |
| `subagent` | Dispatching subagents and receiving results |
| `exec` | Running scripts, interpreting output |
| `decision` | Routing choices, verdicts, resolution classifications |
| `debate` | Round tracking, point resolutions |
| `review` | Peer review triage, remediation, convergence |
| `audit` | Coherence audit checks and corrections |
| `workflow` | Step transitions, iterations, corrections, start/end |

**Logging rhythm:**

- **Step boundaries:** Log `workflow` / `step_start` entering a step, `step_end` exiting.
- **File I/O:** Log `read` before analyzing a file, `write` after producing or modifying an artifact.
- **Subagents:** Log `subagent` / `dispatch_*` before the Agent tool call, `receive_*` after. Summarize the subagent's output in `detail`; capture structured counts in `meta` (e.g., `{"critique_points": 7, "major": 3}`).
- **Code execution:** Log `exec` / `run_*` before running a script, then log outcome with key metrics in `meta`.
- **Gates:** Log `gate` when presenting a gate and again when the user responds.
- **Decisions:** Log `decision` at every routing choice (macro-iteration outcome, force-resolution, recommendation stability).
- **Debate:** Log `debate` for round starts, point resolutions, and convergence.
- **Corrections:** Log `workflow` / `correction_received` immediately when the user corrects something.

**First and last entries:** The first entry (`cat: workflow`, `action: investigation_start`) is written immediately after `HYPOTHESIS.md`. The last (`cat: workflow`, `action: investigation_complete`) is written at the end of the investigation.

**Sequence recovery:** `log_entry.py` auto-increments by reading the last line of the log. No manual tracking required. If the file is empty or missing, seq starts at 1 automatically.

**Examples:**
```bash
uv run log_entry.py --step pre --cat workflow --action investigation_start \
  --detail "Hypothesis agreed, HYPOTHESIS.md written, beginning investigation" \
  --artifact HYPOTHESIS.md --meta '{"report_mode":"full_report","review_mode":"ensemble"}'

uv run log_entry.py --step 5 --cat gate --action gate_experiment_plan_approved \
  --detail "User approved experiment plan with 4 empirical tests" \
  --meta '{"empirical_tests":4,"conceded_points":2}'
```

---

## Step 1 — Build the Minimal Proof-of-Concept

**Goal:** Produce the simplest possible end-to-end script that tests the hypothesis. It should run in one command and produce a number.

**What to build:**
- Synthetic data generation with controlled ground truth
- The proposed model or signal, implemented simply
- The agreed primary metric(s), computed on the synthetic evaluation set
- At least one visualization showing the mechanism, not just the score

**Before writing any code:** Identify any reference implementation this PoC must match. If one exists, record its configuration explicitly. Framework and library defaults are never a safe assumption — they are the most common source of silent divergence from a reference. Any parameter not explicitly set is a potential source of failure.

**Rules:**
- No production code. No database connections. No external APIs.
- Use PEP 723 inline script metadata (`# /// script`) for dependency management so the script runs with `uv run script.py` without setup.
- Hardcode reasonable defaults. Configurability is not the goal.
- Write a comment block at the top listing what the PoC is deliberately leaving out.

**Artifact:** A single runnable Python script named after the hypothesis domain (e.g., `churn_prediction_poc.py`).

---

## Step 2 — Clarify Intent and Review the Code

**Goal:** Verify that you understand the *intent* of every design choice — not just what the code does, but why.

**What to do:**
1. Read the script. For every non-obvious design choice, write down what you believe the intent is.
2. Flag anything that looks like an error.
3. For each flagged item, ask: "Could this be intentional given the production scenario the PoC is simulating?" If yes, state why before proposing a fix.
4. Present your interpretation and flags to the user before changing anything.

**Most dangerous mistake:** Flagging intentional behavior as a bug. A "data leakage" finding that turns out to be intentional by the evaluation design is not a data leakage finding — it is a misunderstanding of the hypothesis.

**Artifact:** `README.md` with:
- One-paragraph hypothesis statement
- Quickstart command
- Brief pipeline description (data → model → score → evaluate → visualize)
- What the output looks like
- Known limitations / explicit scope exclusions

---

## Steps 3–5 — Review

These steps generate the critique of the PoC and produce the empirical test list. The structure depends on `review_mode`.

---

### If `review_mode == ensemble`

#### Step 3 — Ensemble Critique (3× independent dispatches)

Dispatch `ml-critic` **three times** via the Agent tool, each in **initial critique mode** (Mode 1). Each dispatch is independent — do not include output from prior dispatches in any subsequent dispatch prompt.

For each dispatch (Assessor A, B, C):
- Instruct ml-critic to read `HYPOTHESIS.md`, `[domain]_poc.py`, and `README.md`
- The dispatch prompt is identical for all three — no variation in framing or emphasis
- Each produces its own artifact: `CRITIQUE_1.md` (Assessor A), `CRITIQUE_2.md` (Assessor B), `CRITIQUE_3.md` (Assessor C)

Log `subagent`/`dispatch_critic_ensemble` before the first dispatch with `meta` containing `{"review_mode": "ensemble", "assessor_count": 3}`. Log `subagent`/`receive_critic_1`, `receive_critic_2`, `receive_critic_3` after each individual return.

**Steps 4 and 5 are skipped in ensemble mode.** Do not dispatch `ml-defender`. Do not initialize `DEBATE.md`.

#### Step 3A — Aggregate Ensemble Findings → ENSEMBLE_REVIEW.md

After receiving all three critiques, **you** (the orchestrator) perform the aggregation directly. This is not a subagent dispatch.

**Deduplication procedure:**

1. Read `CRITIQUE_1.md`, `CRITIQUE_2.md`, and `CRITIQUE_3.md` in full.
2. For each issue raised in any critique, identify its **root cause** — the underlying assumption or design choice being questioned.
3. Cluster issues across the three critiques by root cause. Two issues from different assessors target the same root cause if addressing one would resolve the other. Use the same grouping principle ml-critic Mode 1 uses: organize by root cause, not severity.
4. For each cluster, record which assessors (A, B, C) raised it. An assessor is credited if any of their numbered issues targets this root cause, even if the phrasing differs.
5. Tag each cluster with its assessor support count and detection redundancy tier. These tiers carry real precision signal. v7 data (H5 FAIL, n=432) shows minority-flagged issues carry a −0.080 precision penalty vs consensus issues (CI [−0.108, −0.052]); v7 supersedes v6's parity finding (CI [−0.028, +0.068]). The gap is driven by composition: 3/3 issues are 55% planted_match (high precision by definition), while 1/3 issues are 66% valid_novel with 15% spurious noise — minority findings include more genuine edge-case concerns alongside real noise. Weight tiers accordingly:
   - `3/3` → `high redundancy` — all three assessors independently flagged this root cause; treat as established concern
   - `2/3` → `medium redundancy` — two of three assessors flagged this root cause; standard recommendation
   - `1/3` → `minority finding` — one assessor flagged this; the 1/3 pool contains genuine novel findings but also ~15% spurious noise; require explicit user confirmation before this issue enters experiment design
6. Synthesize the strongest formulation for each cluster — combine the clearest claim statement, the most specific failure mechanism, and the most actionable evidence criteria from across the assessors who raised it.

**Write `ENSEMBLE_REVIEW.md`:**

```markdown
# Ensemble Review

**Review mode:** ensemble_3x (3 independent critics, union pooling)
**Assessors:** A (CRITIQUE_1.md), B (CRITIQUE_2.md), C (CRITIQUE_3.md)

## Aggregated Issues

### Issue 1 — [Root cause title]
**Assessor support:** 3/3 (high redundancy)
**Assessors:** A (Issue #N), B (Issue #N), C (Issue #N)
**The specific claim being made:** [synthesized from the strongest formulation]
**Why that claim might be wrong:** [synthesized — include any distinct mechanisms raised by different assessors]
**What would constitute evidence:** [synthesized]

---

### Issue 2 — [Root cause title]
**Assessor support:** 2/3 (medium redundancy)
**Assessors:** A (Issue #N), B (Issue #N)
[same structure]

---

### Issue N — [Root cause title]
**Assessor support:** 1/3 (minority finding)
**Assessor:** C (Issue #N)
[same structure]

---

## Issues by Detection Tier

| Tier | Count | Issues |
|------|-------|--------|
| High redundancy (3/3) | N | #1, #3, ... |
| Medium redundancy (2/3) | N | #2, ... |
| Minority finding (1/3) | N | #4, ... |

> **Minority findings note:** 1/3-flagged issues include genuine novel concerns alongside ~15% spurious noise. Each must be explicitly confirmed by the user before entering experiment design.
```

Log `write`/`write_ensemble_review` with `meta` containing `{"total_issues": N, "high_redundancy": N, "medium_redundancy": N, "minority_finding": N}`.

---

### If `review_mode == debate`

The structured multi-round debate protocol runs in two phases:
- **Stage A** (runs once): ml-critic R1 → ml-defender R1
- **Stage B** (repeatable, up to `max_rounds`): ml-critic-r2 → ml-defender R2 → derive_verdict() → convergence check

Defaults: `min_rounds = 2`, `max_rounds = 4`.

**Carry `original_severity` from Stage A through all Stage B rounds** — it is required for `derive_verdict()`.

#### Stage A.1 — Adversarial Critique (ml-critic R1)

Dispatch the `ml-critic` subagent via the Agent tool in **initial critique mode** (Mode 1). Instruct it to read `HYPOTHESIS.md`, `[domain]_poc.py`, and `README.md`.

Receive structured JSON output: `findings` array (`finding_id`, `severity`, `severity_label`, `suppressed`, `claim`, `failure_mechanism`, `evidence_test`, `flaw_category`); top-level `summary` and `no_material_findings`.

**Short-circuit:** If `no_material_findings: true`, skip Stage A.2 and all Stage B rounds. The case verdict is `defense_wins`. Log and proceed to Gate 1.

Filter findings: remove all entries where `suppressed: true` (NIT findings). Pass only non-suppressed findings (FATAL, MATERIAL, MINOR) to Stage A.2.

Log `subagent`/`receive_critic_r1` with `meta` containing `{"no_material_findings": <bool>, "fatal_count": N, "material_count": N, "minor_count": N, "nit_suppressed": N}`.

#### Stage A.2 — Initial Defense (ml-defender R1)

Dispatch the `ml-defender` subagent in **initial defense mode** (Mode 1). Pass `HYPOTHESIS.md`, `[domain]_poc.py`, `README.md`, and the non-suppressed findings JSON from Stage A.1.

Receive structured JSON output: `pass_1_analysis`, `rebuttals` array (`finding_id`, `original_severity`, `rebuttal_type`, `severity_adjustment`, `adjusted_severity`, `justification`), `overall_verdict`, `verdict_rationale`.

Log `subagent`/`receive_defender_r1` with `meta` containing `{"overall_verdict": "<verdict>", "concede_count": N, "defer_count": N, "rebut_count": N}`.

#### Stage B — Challenge-Response Loop (repeatable, up to `max_rounds`)

Initialize loop state: `round = 0`, `prev_verdict = null`, `prev_finding_states = {}`.

Repeat the following until a stopping condition is met:

1. Increment `round`.
2. Determine `is_final_round`: set to `true` if `round == max_rounds`, otherwise `false`.

##### Stage B.1 — R2 Challenge (ml-critic-r2)

Dispatch the `ml-critic-r2` subagent via the Agent tool. Pass the original non-suppressed findings from Stage A.1 and the **current defender rebuttal state** (Stage A.2 rebuttals on round 1; the previous Stage B.2 rebuttals on subsequent rounds).

Receive structured JSON output: `challenges` array (`finding_id`, `challenge_verdict` ACCEPT/CHALLENGE/PARTIAL, `updated_severity`, `reasoning`).

**Validation:** `challenge_verdict` must not be `DEFER` — that is a defender action. If any challenge arrives with `challenge_verdict: DEFER`, coerce it to `CHALLENGE` and note in the log.

Log `subagent`/`receive_critic_r2` with `meta` containing `{"round": N, "accept_count": N, "challenge_count": N, "partial_count": N}`.

##### Stage B.2 — R2 Defense (ml-defender R2)

Dispatch the `ml-defender` subagent in **structured R2 response mode** (Mode 2). Pass original findings from Stage A.1, the current defender rebuttal state, and R2 challenges from Stage B.1. Explicitly state in the dispatch: *"This is a structured R2 response (Mode 2), not an open-ended debate round."*

**Round framing:** Include `is_final_round` in the dispatch:
- `is_final_round = false` → "Produce your current position — the debate may continue if points remain unresolved."
- `is_final_round = true` → current language: "produce your **final** rebuttal."

Receive structured JSON output: `pass_2_analysis`, `rebuttals` array (`finding_id`, `original_severity`, `rebuttal_type`, `severity_adjustment`, `adjusted_severity`, `justification`, `r2_challenge_response`), `overall_verdict`, `verdict_rationale`.

Log `subagent`/`receive_defender_r2` with `meta` containing `{"round": N, "is_final_round": <bool>, "overall_verdict": "<verdict>", "concede_count": N, "defer_count": N, "maintained_count": N, "strengthened_count": N}`.

##### Stage B.3 — derive_verdict()

**Run the deterministic script** — do not compute the verdict manually. Pipe the Stage B.2 defender JSON to `derive_verdict.py`:

```bash
# From repo root:
echo '<stage_b2_defender_json>' | uv run plugins/ml-lab/skills/ml-lab/scripts/derive_verdict.py
# Or with an absolute path if cwd is uncertain:
echo '<stage_b2_defender_json>' | uv run "$(git rev-parse --show-toplevel)/plugins/ml-lab/skills/ml-lab/scripts/derive_verdict.py"
```

Use the script's stdout as the verdict. The script is the authoritative implementation; the rules table below is documentation only.

**Reference rules** (implemented in `derive_verdict.py`):

| Condition | Point verdict |
|---|---|
| `adj_sev ≤ 3` (any rebuttal type) | `defense_wins` |
| `CONCEDE` + `adj_sev > 3` | `critique_wins` |
| `DEFER` + `adj_sev > 3` | `empirical_test_agreed` |
| `REBUT*` + `adj_sev ≥ 7` | `empirical_test_agreed` (high residual) |
| `REBUT*` + `orig_sev ≥ 7` + `adj_sev 4–6` | `empirical_test_agreed` (FATAL not fully cleared) |
| `REBUT*` + `orig_sev < 7` + `adj_sev ≤ 6` | `defense_wins` |

Constitutional overrides (after main rules): `CONCEDE + adj_sev ≥ 7` → `critique_wins`; `DEFER + adj_sev ≤ 3` → `defense_wins`.

Case-level aggregation: `critique_wins` beats `empirical_test_agreed` beats `defense_wins`. Empty rebuttals → `defense_wins`.

> **DO NOT implement the FATAL DEFER backstop** (`DEFER + orig_sev ≥ 7 + adj_sev ≥ 6 → critique_wins`). It was reverted after catastrophically over-blocking ETA and defense_wins cases in benchmark testing. The correct mechanism is question 4 in the defender prompts.

Log `decision`/`derive_verdict` with `meta` containing `{"round": N, "case_verdict": "<verdict>", "critique_wins_points": N, "eta_points": N, "defense_wins_points": N}`.

##### B.1 Early-Exit Check

**Before dispatching Stage B.2:** If all B.1 challenge verdicts are `ACCEPT` and `round >= min_rounds`, skip B.2 entirely. Run `derive_verdict.py` on the current B.2 state (unchanged from the previous round), log `debate_convergence` with `stop_reason: converged`, and stop. Rationale: if the critic accepted every rebuttal, the defender will trivially MAINTAIN all positions — running B.2 and B.3 adds no information.

##### Convergence Check

After Stage B.3, evaluate stopping conditions before dispatching the next round:

| Stopping condition | Action |
|---|---|
| `round >= min_rounds` AND `case_verdict == prev_verdict` AND no finding changed `rebuttal_type` or `adj_sev` vs. `prev_finding_states` | **Stop — converged** |
| All findings have `adj_sev ≤ 3` or produced `defense_wins` / `critique_wins` | **Stop — fully resolved** *(no `min_rounds` guard — when every finding is already at a terminal state, additional rounds yield no new information and waste API calls)* |
| No finding changed `rebuttal_type` or `adj_sev` since previous round (and `round >= min_rounds`) | **Stop — no movement** |
| `round == max_rounds` | **Stop — cap reached; force-resolve** |

**Force-resolution at cap:** If `max_rounds` reached with residual DEFERs, `derive_verdict()` already applies to the final state as-is — residual DEFERs yield `empirical_test_agreed` per the standard rules. No special handling required; log the final verdict and stop.

Update loop state: `prev_verdict = case_verdict`, `prev_finding_states = {finding_id: (rebuttal_type, adj_sev) for each finding}`.

Log `decision`/`debate_convergence` with `meta` containing `{"rounds_completed": N, "stop_reason": "<converged|fully_resolved|no_movement|max_rounds>", "case_verdict": "<verdict>"}`.

---

**Always include the trivial baseline** regardless of review mode. Non-negotiable. A model that cannot outperform a two-line baseline is not a model.

### Gate 1 — Experiment Plan

**Pre-flight extraction depends on `review_mode`:**

**If `review_mode == ensemble`:**

1. Read `ENSEMBLE_REVIEW.md`.
2. Extract all issues ordered by detection tier (high redundancy → medium redundancy → minority finding).
3. Map all issues to the pre-flight checklist as PENDING. Add a note to minority-finding items: `(minority finding — user must explicitly confirm inclusion before this enters experiment design)`.
4. For each issue that cannot be verified by inspection, propose an empirical test specification:
   - The experimental condition
   - What result confirms the concern
   - What result refutes it
   - What result is ambiguous
   These are orchestrator-proposed tests; the user validates them at Gate 1.
5. Checklist format: `| # | Source | Confidence | Item | Verification Method | Status (PENDING/CLOSED) |`

**If `review_mode == debate`:**

1. From `derive_verdict()` output: extract every finding with point_verdict `critique_wins` — each is a known gap that must be addressed or documented before the experiment runs.
2. From the final Stage B round rebuttals: extract every finding with `rebuttal_type: CONCEDE` — these are conceded flaws that must be addressed in experiment design.
3. From the final Stage B round rebuttals: extract every finding with `rebuttal_type: DEFER` — these are open empirical questions; each must have a proposed test with pre-specified verdicts in the experiment plan.
4. Compile all extracted items into a pre-flight checklist: `| # | Source | Finding ID | Point Verdict | Item | Verification Method | Status (PENDING/CLOSED) |`

This checklist is dynamically constructed from the actual review output — it must not be pre-written before the review runs.

---

Log `gate`/`experiment_plan_preflight_constructed` with `meta` containing `{"checklist_item_count": N, "review_mode": "<mode>"}`.

Write a structured plan covering:
- **Ensemble summary** [ensemble only]: N issues found across 3 assessors (high redundancy: N, medium redundancy: N, minority finding: N). Recommended action: proceed to experiment / defer pending user review of minority findings / flag for redesign — based on the tier distribution.
- **Pre-flight checklist:** all items with verification method and status (format depends on review_mode, as above)
- **Empirical tests:** each test with its pre-specified verdicts [ensemble: orchestrator-proposed; debate: debate-extracted]
- **High-redundancy issues** [ensemble] / **Conceded critique points** [debate]: how each will be addressed in the experiment design
- **Experimental conditions:** all conditions to be run, including the trivial baseline
- **Subpopulations / stratifications:** segmented analyses identified in the review

Present this plan to the user. **Do not begin Step 6 until:**
1. Every pre-flight checklist item is marked CLOSED (verified or explicitly deferred with documented rationale).
2. The user explicitly approves the experiment plan.
3. Run `/intent-watch <experiment_dir> HYPOTHESIS.md` — it must return a clean pass. If any HIGH or CRITICAL conflict is reported, resolve it before proceeding. This is the pre-registration boundary: HYPOTHESIS.md is now locked, and any drift discovered here means the planning phase produced an inconsistency that must be corrected, not carried forward.

**Artifacts (ensemble mode):** `CRITIQUE_1.md`, `CRITIQUE_2.md`, `CRITIQUE_3.md`, `ENSEMBLE_REVIEW.md`
**Artifacts (debate mode):** Structured JSON from Stage A and each Stage B round; `derive_verdict()` output per round; convergence log (`rounds_completed`, `stop_reason`); pre-flight checklist

---

## Step 6 — Design and Run the Experiment

**Goal:** Translate every agreed empirical test into a concrete experimental condition with a pre-specified verdict. Incorporate conceded critique points into the experiment design — concessions identify known problems that the experiment must address, not just the formally agreed tests.

**For each test, write down before running:**
- What result would mean the critique was right
- What result would mean the defense was right
- What result would be ambiguous

**Implementation requirements:**
- Bootstrap confidence intervals (N=1,000, percentile method) on all primary metric values
- Stratified analysis where the debate identified relevant subpopulations
- All models and baselines evaluated on identical data splits
- Use PEP 723 inline script metadata (`# /// script`) for dependency management
- Print a structured results summary at the end (not just raw numbers)

**Baseline verification rule:** Inspect the baseline scoring function line by line before reporting results. Common failure modes: silent API misuse that makes every input score identically, a default argument that bypasses intended behavior, or a trivially satisfied evaluation condition.
- If any condition produces near-perfect metrics (AP > 0.99, AUC > 0.999), investigate before reporting — this usually means the task is trivially easy or there is a data leak, not that the model is excellent

**Precondition verification rule:** Before interpreting any result, verify that the model satisfies the preconditions the hypothesis depends on. If the hypothesis claims a model is sensitive to a particular signal, confirm the model actually encodes that signal before treating outcome metrics as meaningful. A model can look healthy on aggregate metrics while being completely blind to the specific discriminative requirement the hypothesis targets. Failed preconditions halt result interpretation — do not report verdicts from an unverified model.

**Pre-registration drift monitoring:** Activate `/loop 2m /intent-watch <experiment_dir> HYPOTHESIS.md` during active scripting. This runs a passive background check on every cycle: if any script, config, or analysis file modifies a pre-registered threshold, condition, scoring dimension, or sample size target, the conflict is reported immediately. Any HIGH or CRITICAL finding suspends result interpretation until the conflict is resolved or documented as an intentional amendment (which requires re-opening Gate 1).

**Artifact:** A runnable Python script (`[domain]_experiment2.py`) implementing all agreed tests.

---

## Step 7 — Synthesize Conclusions

**Goal:** Write findings as verdicts against the pre-specified debate resolutions — not as a summary of what you ran.

**For each debate point requiring empirical resolution:**
- State what was agreed in the debate
- State what the evidence showed
- State which side was right (or if neither — this happens)

**Special attention to surprises:** If the experiment produced a result neither side predicted, mark it explicitly and explain why the debate failed to anticipate it.

**Generate figures at this step.** These are the canonical figures for the entire investigation. Produce two kinds:

**Per-finding figures** — one figure per empirical test, each illustrating exactly one finding. Prefer distributions and uncertainty over point estimates. Prefer stratified views when subpopulations were identified in the debate. Include side-by-side comparisons against the trivial baseline.

**Summary figure** — one figure comparing all findings side-by-side: the trivial baseline, all tested conditions, and their confidence intervals on the primary metric.

Save all figures as PNG files. Use descriptive filenames (e.g., `finding_01_temporal_signal.png`, `summary_all_conditions.png`).

**Artifact:** `CONCLUSIONS.md` with a debate scorecard table (point, topic, verdict, evidence) and figures referenced inline.

---

## Steps 6–7 Are an Iterative Cycle

Do not proceed to Step 8 until:
1. All pre-specified verdicts from the current debate are resolved
2. No evaluation design flaw has been identified that would change a material finding
3. The recommendation is stable

**Common triggers for another iteration:**
- Evaluation design flaw discovered (suspicious performance, missing population)
- New hypothesis generated by results
- Baseline was broken
- New confound or population identified

Each iteration produces a new experiment script (e.g., `[domain]_experiment3.py`) and updates/extends `CONCLUSIONS.md` with clearly labeled sections per experiment.

---

## Macro-Iteration: Where Do the Results Send Us?

After Steps 6–7 stabilize, evaluate whether the investigation is complete or needs another cycle. There are three possible outcomes:

**Outcome A — Proceed.** The findings align with debate predictions (whether the hypothesis was confirmed or refuted), all verdicts are resolved, and the recommendation is stable. In `full_report` mode, proceed to Step 8. In `conclusions_only` mode, proceed directly to Step 9 (production re-evaluation) and then wrap up.

**Outcome B — Return to Adversarial Review (Step 3).** The hypothesis is still sound, but the experiments revealed something the critique/defense cycle didn't anticipate.

Triggers:
- **Surprise findings** — results neither the ml-critic nor the ml-defender predicted.
- **Recommendation instability across experiments** — the recommendation changed between iterations.
- **New failure mode surfaced** — the experiments revealed a failure pattern that wasn't part of the original critique.

**Outcome C — Return to Hypothesis (before Step 1).** The experiments revealed that the hypothesis itself is wrong or incomplete — the mechanism, signal, or expected observable needs to be reformulated.

Triggers:
- **Mechanism falsified** — the proposed mechanism doesn't work as theorized.
- **Wrong observable** — the metric is moving, but it's measuring something other than what the hypothesis claims.
- **Confound is the actual signal** — a confound explains the results better than the hypothesized mechanism.
- **New hypothesis generated** — the experiment suggests a different mechanism that cannot be tested by the current PoC.

**What NOT to re-run:**
- If the experiment simply needs a design fix (broken baseline, missing stratification), that's a micro-iteration within Steps 6–7 — not a macro-iteration.
- If the findings are unsurprising and align with debate predictions, proceed to Step 8 even if the results are disappointing.

### Macro-Iteration Procedure

**For both Outcome B and C:**
1. Write a structured plan covering:
   - **Trigger:** the specific finding or falsification that requires re-opening (quote the result)
   - **Recommended path:** Outcome B (return to adversarial review) or Outcome C (return to hypothesis), with the reason this path is correct
   - **Next cycle scope:** what the next cycle will test or reformulate that the current cycle could not
   - **Artifact updates:** which files will be updated and how (e.g., new section in `CONCLUSIONS.md`, revised `HYPOTHESIS.md`, new experiment script)

   Present this plan to the user. **Do not re-enter the loop until the user approves.**

2. Update `CONCLUSIONS.md` with a section marking the end of the current cycle and the reason for re-opening.

**If Outcome B (return to review):**

**If `review_mode == ensemble`:**
3. Dispatch `ml-critic` **three times** in **evidence-informed re-critique mode** (Mode 3), each independently. Provide each dispatch with the original artifacts plus `CONCLUSIONS.md`, experiment figures, and `ENSEMBLE_REVIEW.md`. In the dispatch prompt, state: "There was no debate phase in this investigation. The prior cycle's review findings are in ENSEMBLE_REVIEW.md. Re-examine all issues — including those with low assessor support — in light of the experimental evidence."
4. Each critic appends its output to the corresponding `CRITIQUE_N.md` under `## Critique — Cycle N`.
5. Re-run Step 3A aggregation on the new cycle's outputs. Append new findings to `ENSEMBLE_REVIEW.md` under `## Ensemble Review — Cycle N`.
6. Extract the new empirical test list using ensemble pre-flight logic. The trivial baseline must still be included.
7. Present the ensemble review summary and new test list to the user before re-entering Steps 6–7.

**If `review_mode == debate`:**
3. Dispatch `ml-critic` in **evidence-informed re-critique mode** (Mode 3) with the original artifacts plus `CONCLUSIONS.md` and experiment figures. This produces a new critique informed by the experimental evidence.
4. Run the full debate protocol (Stage A + Stage B loop above) on the new critique — the same protocol as the first cycle, with fresh structured JSON outputs for this cycle.
5. Apply `derive_verdict()` to the final Stage B round output. Log the new case verdict.
6. Extract the new empirical test list (DEFER findings from the final Stage B round + any new CONCEDE findings). The trivial baseline must still be included.
7. Present the debate summary and new test list to the user before re-entering Steps 6–7.

**If Outcome C (return to hypothesis):**
3. Work with the user to reformulate the hypothesis. Append the revised hypothesis to `HYPOTHESIS.md` as `## Hypothesis — Cycle N`.
4. Evaluate whether the existing PoC still tests the revised hypothesis:
   - If yes: update `README.md` and proceed to Step 3.
   - If no: rebuild the PoC (Step 1) with the updated hypothesis.
5. Continue through Steps 3–7 as normal with the revised hypothesis.

**Cap:** Maximum 3 macro-iterations (the initial pass plus 2 re-openings). If the investigation has not converged after 3 cycles, proceed to Step 8 (`full_report` mode) or Step 9 (`conclusions_only` mode) with the best available evidence and flag the instability prominently. Unbounded iteration is not rigor — it is indecision.

---

## Step 8 — Write the Report

**Mode gate:** `full_report` mode only. Skip entirely in `conclusions_only` mode — proceed directly to Step 9.

**Goal:** Synthesize the full arc into a single document readable without reference to any intermediate files.

Dispatch the `report-writer` subagent (Mode 1) via the Agent tool. Provide:
- `CONCLUSIONS.md`, `stats_results.json`, `SENSITIVITY_ANALYSIS.md` (if exists), `HYPOTHESIS.md`
- Review artifacts depending on `review_mode`:
  - **ensemble:** `ENSEMBLE_REVIEW.md`, `CRITIQUE_1.md`, `CRITIQUE_2.md`, `CRITIQUE_3.md`
  - **debate:** Stage 1–4 structured JSON outputs; `derive_verdict()` point verdicts
- Any cross-vendor or external validation results available
- Experiment-specific context in the dispatch prompt: related work citations,
  condition or approach names, primary metric name, comparison structure,
  pre-registration document, and which `review_mode` was used

The report-writer produces a complete technical report with sections: Abstract, Related Work, Experimental Design, Results (with comparison tables, CIs, statistical tests, hypothesis verdicts), Failure Mode Analysis, Limitations (each: threat/evidence/mitigation), Artifacts.

**The self-contained test:** Someone who reads only the report should understand what was claimed, what was tested, what the evidence showed, and what should be built next — without consulting any other file.

**If the investigation went through multiple macro-iterations:** provide that context in the dispatch prompt. The report-writer will explain why each cycle was necessary without structuring the report as a discovery narrative.

**Artifact:** `REPORT.md`

---

## Step 9 — Re-Evaluate Under Production Constraints

**Goal:** Evaluate the experimental recommendation against production constraints the PoC deliberately excluded.

**Always check these four areas:**
1. **Retraining dynamics:** How often must the model be retrained? What drives the cadence — data drift, concept drift, or calendar schedule? What happens to existing state during retraining — is there a warm-start path? What is the cost of a retraining run (compute, data volume, human oversight)? What is the blast radius of a bad retrain, and how would you detect it before production?
2. **Update latency:** How quickly can the model respond to new information — batch or real-time? What is the gap between "event happens" and "model reflects it"? Are there edge cases where latency matters more (e.g., fraud detection during a burst of activity)?
3. **Operational complexity:** What infrastructure is required — what jobs run, on what cadence, gated on what conditions? What monitoring is needed and what metrics would you alert on? What is the on-call burden — can the existing team operate this? What are the dependencies, and what happens if an upstream system is down?
4. **Failure modes:** What happens when the model is wrong — what is the cost of a false positive vs. false negative? What happens when the model is stale or unavailable? What is the fallback — is there a simpler system that can take over? What happens at cold start (new users, new products, new markets with no training data)?

**The completeness test:** "Use this model in production" is not a recommendation. A recommendation names what runs, on what cadence, gated on what conditions, with what fallback.

Production constraints frequently invert the ranking of candidates. If the production re-evaluation changes the recommendation, write an addendum explaining the reversal.

**Artifact:** `REPORT_ADDENDUM.md` with production analysis, revised recommendation (if changed), deployment roadmap (shadow → canary → full rollout with rollback criteria), and open questions.

---

## Step 10 — Peer Review Loop

**Mode gate:** `full_report` mode only. Skip entirely in `conclusions_only` mode.

**User confirmation required.** Do not start this step automatically. After Step 9 completes, ask the user: *"The full investigation is complete. Do you want to run the peer review loop on REPORT.md? (Round 1 uses a deep Opus review; up to 2 additional Haiku verification rounds follow.)"* Only proceed if the user confirms.

**Goal:** Subject the completed report to independent peer review, then iterate on findings until the report is defensible or human intervention is needed.

This is the outermost loop in the investigation. It runs *after* Steps 1–9 are complete — the hypothesis has been tested, the review has completed, the report has been written, and the production re-evaluation is done. The peer review loop catches report-level problems that the internal debate process misses: overclaimed conclusions, statistical gaps, missing comparisons, presentation issues, and logical inconsistencies across documents.

### Round 1 — Deep Review (Opus)

Dispatch the `research-reviewer` subagent via the Agent tool with `subagent_type: "research-reviewer"`. Instruct it to:

1. Read `REPORT.md` as the primary document
2. Also read `CONCLUSIONS.md`, `REPORT_ADDENDUM.md`, and `SENSITIVITY_ANALYSIS.md` (if it exists)
3. Produce a structured peer review with Summary, Strengths, Critical Issues (MAJOR/MINOR), and Prioritized Recommendations

The reviewer writes its output to `PEER_REVIEW_R1.md`.

### Gate 3 — Peer Review Remediation Plan

After receiving `PEER_REVIEW_R1.md`, write a structured plan covering:
- **MAJOR issues:** for each, the proposed action type (text fix / additional analysis / full experiment) and the specific remediation
- **MINOR issues:** for each, the proposed action or deferral rationale
- **Artifact scope:** which files will change and the estimated extent of edits to `REPORT.md`

Present this plan to the user. **Do not address any findings until the user approves.**

This gate applies to Round 1 only. Rounds 2–3 (Haiku verification) do not require a plan gate.

### Address Findings

After the Gate 3 plan is approved, execute the triage. Each issue falls into one of three action types:

1. **Text fix** — Rewrite report prose, fix inconsistencies, restructure sections, correct overclaimed conclusions. Execute these immediately by editing `REPORT.md` and any affected artifacts.
2. **Additional analysis** — Run new statistical tests, compute missing comparisons, generate figures, add confidence intervals. This may require writing and running new scripts. Update `CONCLUSIONS.md` and `REPORT.md` with the results.
3. **Full experiment** — The reviewer identified a gap that requires new empirical work. Re-enter the Steps 6–7 micro-iteration cycle, then propagate results through Steps 7–8 (conclusions → report).

After addressing all actionable findings, update `REPORT.md` and all affected artifacts. For each finding, document in `PEER_REVIEW_R1.md` (appended under a `## Response` section):
- What action was taken
- What was changed and where
- What was deferred and why (if any)

### Rounds 2–3 — Verification Reviews (Haiku)

Dispatch the `research-reviewer-lite` subagent via the Agent tool with `subagent_type: "research-reviewer-lite"`. Same instructions as Round 1, but the reviewer also reads the prior `PEER_REVIEW_R{N-1}.md` to verify that previous findings were addressed.

The reviewer writes to `PEER_REVIEW_R{N}.md`. Same triage-and-address cycle as Round 1.

### Convergence and Termination

**Early exit:** If a round's review contains no MAJOR issues, the loop terminates. Minor issues may be addressed but do not require another review round.

**Cap:** Maximum 3 rounds (1 Opus + up to 2 Haiku). Unbounded review iteration is not rigor — it is polishing.

**After the final round (or early convergence):** Write a `## Peer Review Summary` section appended to `REPORT.md` documenting:
- How many review rounds were conducted
- Key issues identified and how they were resolved
- Any MAJOR issues that remain open after 3 rounds
- Whether human review is recommended before the report is considered final

**If MAJOR issues persist after 3 rounds:** Stop. Do not continue autonomously. Flag the unresolved issues explicitly and return control to the user. The report is not ready without human judgment on the remaining problems.

---

## Step 11 — Final Technical Report (Results Mode)

**Optional.** After the investigation is otherwise complete — Step 9 in `conclusions_only` mode, or Step 10 in `full_report` mode (or after the user declines peer review) — ask:

> *"Do you want a final technical report? This synthesizes all findings into a single publication-ready document written in results mode: findings stated as established facts, logical structure rather than narrative arc."*

Only proceed if the user confirms. If declined, skip and go directly to Step 12 or the investigation wrap-up.

**Goal:** Produce a single self-contained document that presents the investigation's conclusions as established results — not as a record of how they were reached. This is the publication-ready version. `REPORT.md` (if it exists) is preserved as the working document and is not modified.

Dispatch the `report-writer` subagent (Mode 2) via the Agent tool. Provide ALL available artifacts:

| Always | `full_report` mode only |
|--------|------------------------|
| `HYPOTHESIS.md` | `REPORT.md` |
| `CONCLUSIONS.md` | `PEER_REVIEW_R*.md` |
| `REPORT_ADDENDUM.md` | |
| Experiment scripts and figure files | |
| **ensemble mode:** `ENSEMBLE_REVIEW.md` | |
| **debate mode:** Stage 1–4 JSON outputs; `derive_verdict()` output | |

The report-writer synthesizes these into TECHNICAL_REPORT.md without reproducing the debate structure or peer review issues — those are inputs, not content.

**Artifact:** `TECHNICAL_REPORT.md`

---

## Step 12 — Artifact Coherence Audit

**Mode gate:** Runs only when `report_mode == full_report` OR `TECHNICAL_REPORT.md` was produced. Skip entirely in `conclusions_only` mode with no technical report.

**Goal:** Verify that every document the user will read presents a consistent, non-contradictory view of the investigation. This is not a content review — it is a cross-document consistency check. By this point all artifacts are final; the audit finds any drift that crept in across iterations.

**Read every produced artifact before starting.** The check covers all documents that exist:

| Always check | If produced |
|---|---|
| `HYPOTHESIS.md` | `REPORT.md` |
| `CONCLUSIONS.md` | `REPORT_ADDENDUM.md` |
| `README.md` | `PEER_REVIEW_R*.md` |
| **ensemble:** `ENSEMBLE_REVIEW.md` | `TECHNICAL_REPORT.md` |
| **debate:** Stage 1–4 structured JSON outputs | |

**Six checks — execute all:**

1. **Quantitative consistency.** Every headline number, lift estimate, AUC, CI, or metric cited in REPORT.md, README.md, and TECHNICAL_REPORT.md must match CONCLUSIONS.md exactly. Identify any figure that differs between documents, even by rounding or framing.

2. **Claim consistency.** A finding confirmed in CONCLUSIONS.md must not be hedged or contradicted in REPORT.md or TECHNICAL_REPORT.md. A limitation stated in one document must not be absent from another where it is relevant. No "X is validated" in one doc alongside "X requires further study" in another.

3. **README currency.** README accurately reflects the final position: step count is correct, finding summary matches CONCLUSIONS.md, no caveats that were resolved during the investigation remain as open questions.

4. **TECHNICAL_REPORT ↔ REPORT alignment** (if both exist). The logical arc in TECHNICAL_REPORT.md is consistent with the narrative arc in REPORT.md. Limitations described as structural properties in TECHNICAL_REPORT.md must match limitations acknowledged in REPORT.md. The recommendation in both must be identical.

5. **Peer review resolution** (if Step 10 ran). Every MAJOR issue from PEER_REVIEW_R1.md is either addressed in REPORT.md or explicitly deferred with a rationale documented in the `## Response` section. No MAJOR issue silently dropped.

6. **Hypothesis closure.** The final answer to the original hypothesis stated in HYPOTHESIS.md is present and consistent in both CONCLUSIONS.md and REPORT.md (and TECHNICAL_REPORT.md if produced). The reader should not have to infer the answer — it should be stated.

**Output:** Report the audit result inline — do not create a new artifact file. If clean: *"Coherence audit passed — N artifacts checked, no inconsistencies found."* If any inconsistency is found: fix it immediately (edit the relevant artifact), then state what was fixed and in which file. Do not proceed to Step 13 or the investigation wrap-up with a known inconsistency unfixed.

---

## Step 13 — README Readability Review

**Optional.** After Step 12 completes (or after Step 9 in `conclusions_only` mode with no technical report), ask:

> *"Do you want a README readability review? An outside-reader agent will diagnose clarity and structure issues and produce a rewritten README optimized for external audiences."*

Only proceed if the user confirms. If declined, go directly to the investigation wrap-up.

**Mode gate:** Available in both `full_report` and `conclusions_only` modes. Runs after any coherence check that was required.

**Goal:** Subject the README to review from the perspective of a first-time external reader, then produce a rewritten README that surfaces findings, relevance, and how-to-run information in the first 30 seconds of reading.

Dispatch the `readme-rewriter` subagent via the Agent tool with `subagent_type: "readme-rewriter"`. Instruct it to:

1. Read `README.md` as the primary document
2. Also read `CONCLUSIONS.md` and `REPORT.md` (if it exists) to understand what was actually found
3. Produce a structured diagnosis, then a rewrite outline, then the full rewritten README

The subagent will confirm its rewrite outline before producing the final document. Review the outline — if the structure is wrong, send corrections before the rewrite proceeds.

Once the rewritten README is returned, write it to `README.md`. The original README is replaced; it is preserved in git history if rollback is needed.

**Artifact:** `README.md` (updated in place)

---

## Artifact Inventory

At the end of the investigation, these files must exist:

| Artifact | Step | Role | Review mode |
|----------|------|------|-------------|
| `HYPOTHESIS.md` | Pre-1 | Canonical hypothesis and metrics | both |
| `[domain]_poc.py` | 1 | Implements hypothesis as runnable code | both |
| `README.md` | 2 | Intent, quickstart, limitations | both |
| `CRITIQUE_1.md`, `CRITIQUE_2.md`, `CRITIQUE_3.md` | 3 | Independent assessor critiques | ensemble |
| `ENSEMBLE_REVIEW.md` | 3A | Aggregated issues with detection redundancy tiers | ensemble |
| Stage A.1 JSON (ml-critic R1) | 3 | Structured findings with severity, flaw_category, suppressed flags | debate |
| Stage A.2 JSON (ml-defender R1) | 3 | Structured rebuttals with 7-type taxonomy and severity adjustments | debate |
| Stage B.1 JSON (ml-critic-r2, per round) | 4 | Per-finding ACCEPT/CHALLENGE/PARTIAL challenge verdicts | debate |
| Stage B.2 JSON (ml-defender R2, per round) | 4 | Rebuttals with r2_challenge_response and is_final_round framing | debate |
| Stage B.3 derive_verdict() (per round) | 4 | Case verdict and point verdicts; convergence log | debate |
| `[domain]_experiment{N}.py` | 6 | All empirical tests | both |
| `CONCLUSIONS.md` | 7 | Per-finding verdicts with figures | both |
| `*.png` (figures) | 7, 8 | Canonical visualizations | both |
| `REPORT.md` | 8 | Self-contained report of the full arc | both |
| `REPORT_ADDENDUM.md` | 9 | Production re-evaluation and revised recommendation | both |
| `PEER_REVIEW_R{N}.md` | 10 | Peer review findings per round | both |
| `TECHNICAL_REPORT.md` | 11 (optional) | Publication-ready synthesis in results mode | both |
| `INVESTIGATION_LOG.jsonl` | All | Append-only audit trail of every action taken during the investigation | both |

---

## Handling Corrections from the User

1. Stop. Do not continue with the original interpretation.
2. Ask clarifying questions if needed.
3. Revise your understanding explicitly: state what you thought, what was corrected, and what the correct interpretation is.
4. Check whether prior artifacts need updating.
5. Continue from the corrected understanding.

Corrections at Step 2 are especially high-value. A correction there prevents the entire thread from testing the wrong hypothesis.

**Correction blast radius guide:**
- Hypothesis or metric correction → update `HYPOTHESIS.md`, restart from Step 1
- PoC design correction → restart from Step 2 (intent review) onward
- Critique correction [ensemble] → re-dispatch the affected critic(s), re-run Step 3A aggregation
- Ensemble review correction (aggregation error) → re-run Step 3A only (re-read CRITIQUE_1/2/3.md, re-cluster)
- Critique correction [debate] → restart from current Stage B round onward
- Experiment design correction → restart current experiment iteration
- Report correction → re-run Step 8 only
- Peer review finding (text) → re-run Step 8 and resume Step 10
- Peer review finding (analysis) → re-run Steps 6–7 micro-iteration, then Step 8, resume Step 10
- Peer review finding (experiment) → re-enter Steps 6–7, then Steps 8–10
- Technical report correction → re-run Step 11 only (TECHNICAL_REPORT.md is a synthesis; source artifacts are the truth)

---

## Handling Unexpected Results

1. Do not explain them away. Do not attribute them to "implementation details."
2. State the surprise plainly. Mark it explicitly in `CONCLUSIONS.md`.
3. Trace it back to which debate assumption was wrong.
4. Consider whether the surprise changes the recommendation.

---

## Known Framework Limitations

These are open problems as of v8. Do not treat them as design properties.

**Defense case exoneration (open problem):** In a framework evaluation completed 2026-04-13, Claude Sonnet 4.6 was systematically critique-biased — zero `defense_wins` verdicts across 480 defense runs. The strongest adjacent outcome (`empirical_test_agreed`) was reached by multiround on 50% of defense cases. Full exoneration of sound methodology is currently unsolvable with this model. When evaluating a hypothesis that may be sound, multiround with replicate averaging is the best available tool; even then, treat `empirical_test_agreed` as the effective ceiling.

**Multiround verdict variance:** In a framework evaluation completed 2026-04-13, individual multiround runs had a 60.7% verdict flip rate. Single-run multiround verdicts are not authoritative. If using debate mode, plan for ≥3 replicate runs and report the mean verdict, not any single run.

**Convergence loop mitigation (v8):** The Stage B loop (`min_rounds=2`, `max_rounds=4`) provides within-run stabilization — if findings don't move between rounds, the debate stops early with a stable verdict. This reduces but does not eliminate cross-run variance; replicate runs remain recommended for high-stakes decisions.

**Critic over-aggression on clean designs (v8 Phase 3):** In Phase 3 pipeline validation (5 benchmark cases), the critic drove false-positive `critique_wins` on 2/5 cases where ground truth was `defense_wins` or `empirical_test_agreed`. Root cause: the defender CONCEDEd findings it should have rebutted (case 858: CONCEDE at sev=7 on best-of-3 seed selection; case 185: CONCEDE at sev=9 on undefined query structure). The convergence loop provides additional rounds for correction, but the underlying issue is defender concession calibration — the defender is too willing to CONCEDE on arguable findings rather than using DEFER or REBUT-SCOPE. This is an open calibration concern, not a pipeline bug.

---

## What This Process Is Not

- **Not a waterfall.** Corrections and reversals at any step are expected and healthy.
- **Not finished at the report.** The production re-evaluation is where experimental findings collide with operational reality — often producing the most actionable insight.
- **Not complete without the trivial baseline.** A model that cannot outperform a two-line baseline is not a model. This is non-negotiable.
- **Not self-certifying.** The peer review loop catches report-level problems the internal debate misses — overclaimed conclusions, statistical gaps, presentation issues. But 3 rounds of automated review do not substitute for human judgment on whether the work is ready for its intended audience.

---

## Investigation Wrap-Up

When the investigation is complete, write a summary for the user covering:

**`full_report` mode:** The hypothesis tested, the primary metric, the key empirical finding, whether the trivial baseline was beaten, the final recommendation (including any production-constraint reversal from Step 9), the peer review status (how many rounds ran, whether MAJOR issues were resolved, whether human review is still needed — or note that peer review was declined), whether a final technical report (`TECHNICAL_REPORT.md`) was produced, and the `review_mode` used (ensemble or debate).

**`conclusions_only` mode:** The hypothesis tested, the primary metric, the key empirical finding, whether the trivial baseline was beaten, the final recommendation from the production re-evaluation, whether a final technical report (`TECHNICAL_REPORT.md`) was produced, and the `review_mode` used (ensemble or debate). Note that no full report or peer review was run.
