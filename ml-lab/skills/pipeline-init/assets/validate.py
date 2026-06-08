# /// script
# requires-python = ">=3.10"
# dependencies = ["metaflow>=2.19"]
# ///
"""Reproduction gate for the pipeline standard.

Pulls aggregate.lift_results + an_*.an_result from a flow run
and compares against author-recorded target numbers. Acceptance is CI-overlap OR
observed mean within the target CI, PER SLICE — never bit-exact (Metaflow's
fan-out RNG/scheduling differs from a plain multiprocessing pool).

Run from the repo root:
    uv run flow/validate.py <experiment> [<run-pathspec>]

The PEP 723 header lists metaflow ONLY — validate.py is a pure Metaflow client and
must not pull project deps.

==============================================================================
STRICT ENGINE below this line is the standard's invariant core — keep it shaped.
AUTHOR-FILLED blocks are marked with `# AUTHOR:` and are seeded by pipeline-init
from the PoC's recorded numbers.
==============================================================================
"""
import sys

from metaflow import Flow, Run, namespace

namespace(None)  # see runs regardless of user namespace

# --- AUTHOR: flow name -------------------------------------------------------
# pipeline-init fills this with your FlowSpec class name.
FLOW_NAME = "ReferenceFlow"

# --- AUTHOR: per-slice targets ----------------------------------------------
# pipeline-init SEEDS this from the PoC's recorded numbers. Each entry:
#   (cell-match dict, lift_mean, lift_lo, lift_hi)
# `cell-match` is matched against each lift_result's `cell` by string equality on
# the listed keys (so a cell with extra keys still matches). Use generic field
# names (`separation`, `eval_k`); the metric field is the primary metric.
TARGETS = {
    "baseline_vs_method": [
        ({"separation": 1.0, "eval_k": 50}, 0.120, 0.060, 0.180),
        ({"separation": 1.0, "eval_k": 200}, 0.030, -0.010, 0.070),
        ({"separation": 2.0, "eval_k": 50}, 0.040, 0.000, 0.080),
        ({"separation": 2.0, "eval_k": 200}, 0.010, -0.020, 0.040),
    ],
}


def overlaps(lo1, hi1, lo2, hi2):
    return not (hi1 < lo2 or hi2 < lo1)


def hkey(cell):
    """Hashable, order-independent cell key (lists -> tuples)."""
    return tuple(sorted((k, tuple(v) if isinstance(v, list) else v)
                        for k, v in cell.items()))


def cell_matches(cell, want):
    """True if `cell` matches every key/value in `want` (tolerates extra keys in cell).

    Numeric target values use a small-tolerance numeric compare so a dtype change
    (e.g. 2 vs 2.0) does not silently report MISSING. Non-numeric keys fall back to
    string equality.
    """
    for k, v in want.items():
        cv = cell.get(k)
        try:
            if abs(float(cv) - float(v)) > 1e-9:
                return False
        except (TypeError, ValueError):
            if str(cv) != str(v):
                return False
    return True


# --- AUTHOR: per-analysis checks --------------------------------------------
# Provide exactly ONE check_<analysis>(run) per analysis branch you want gated.
# Read the branch's an_result, apply the slice acceptance rule, print PASS/FAIL.
# Define new check_* functions here; register them in the dispatch block in main().
def check_metric_trend(run):
    """Example analysis check: primary-metric trend rows are present and finite."""
    ar = run["an_metric_trend"].task.data.an_result
    rows = (ar or {}).get("rows") or []
    print("\n=== Analysis gate: metric_trend ===")
    ok = bool(rows) and all(r.get("primary_mean") is not None for r in rows)
    for r in rows:
        print(f"  sep={r.get('separation')} k={r.get('eval_k')} "
              f"{r.get('method')}: primary_mean={r.get('primary_mean')}")
    print(f"  {'PASS' if ok else 'FAIL'}  {len(rows)} rows")


def main():
    exp = sys.argv[1] if len(sys.argv) > 1 else None
    run = Run(sys.argv[2]) if len(sys.argv) > 2 else Flow(FLOW_NAME).latest_run
    print(f"Run: {run.pathspec}  finished={run.finished}  successful={run.successful}")

    agg = run["aggregate"].task.data
    lift_results = agg.lift_results
    aggregate_results = agg.aggregate_results  # [{cell, method, <primary_metric>_mean}]

    print("\n=== Paired lifts (topk_ranking - baseline_ce) ===")
    for lr in sorted(lift_results, key=lambda x: str(x["cell"])):
        star = "*" if lr["ci_excludes_zero"] else " "
        print(f"  {str(lr['cell']):<40} lift={lr['lift_mean']:+.3f} "
              f"[{lr['lift_lo']:+.3f},{lr['lift_hi']:+.3f}]{star} (n={lr['n_seeds']})")

    # Per-(cell, method) primary-metric means — the other half of the pinned
    # aggregate-output contract (Seam 4). Read here so the template shows authors
    # how to pull both `lift_results` and `aggregate_results` from a run.
    print("\n=== Aggregate per (cell, method) ===")
    for ar in sorted(aggregate_results, key=lambda x: str(x["cell"])):
        means = {k: v for k, v in ar.items() if k not in ("cell", "method")}
        print(f"  {str(ar['cell']):<40} {ar['method']}: {means}")

    # Per-analysis checks (author-extended).
    # One check_<analysis>(run) call per analysis branch, dispatched on the
    # experiment name so each experiment runs only its own checks.
    # >>> ADD PER-ANALYSIS CHECKS HERE (one `elif exp == "<name>":` block) <<<
    if exp == "baseline_vs_method":
        check_metric_trend(run)

    # Reproduction gate: CI-overlap OR observed mean within target CI, per slice.
    if exp and exp in TARGETS:
        print(f"\n=== Reproduction gate: {exp} (CI-overlap acceptance) ===")
        allpass = True
        for want, tm, tlo, thi in TARGETS[exp]:
            match = [lr for lr in lift_results if cell_matches(lr["cell"], want)]
            if not match:
                print(f"  MISSING  {want}  (target {tm:+.3f} [{tlo:+.3f},{thi:+.3f}])")
                allpass = False
                continue
            lr = match[0]
            ok_overlap = overlaps(lr["lift_lo"], lr["lift_hi"], tlo, thi)
            ok_point = tlo <= lr["lift_mean"] <= thi
            ok = ok_overlap or ok_point
            allpass = allpass and ok
            print(f"  {'PASS' if ok else 'FAIL'}  {want}  "
                  f"obs {lr['lift_mean']:+.3f} [{lr['lift_lo']:+.3f},{lr['lift_hi']:+.3f}]  "
                  f"vs target {tm:+.3f} [{tlo:+.3f},{thi:+.3f}]")
        print(f"\n  {'ALL PASS' if allpass else 'SOME FAILED'}")

    # Dump the experiment's analysis results (an_* branches).
    for stepname in [s.id for s in run if s.id.startswith("an_")]:
        try:
            ar = run[stepname].task.data.an_result
        except Exception:
            continue
        if ar and (not exp or ar.get("experiment") == exp):
            print(f"\n=== analysis [{stepname}] {ar.get('experiment')} ===")
            for row in (ar.get("rows") or [])[:20]:
                print("  ", row)
            if ar.get("result"):
                print("  ", ar["result"])


if __name__ == "__main__":
    main()
