# /// script
# requires-python = ">=3.10"
# dependencies = ["metaflow>=2.19"]
# ///
"""Determinism-verification helper for ml-lab Metaflow pipelines.

Verifies that a flow reproduces its own aggregate outputs across two runs,
matching the contract declared in `run.data.determinism`:

  order_independent  — outputs agree across runs regardless of worker ordering
  single_worker      — outputs agree when both runs use --max-workers 1
  nondeterministic   — verification skipped (escape hatch, exits 0)

Usage
-----
Compare two specific runs:
    uv run determinism-check.py <run_a_pathspec> <run_b_pathspec>

Compare the latest two runs of a named flow:
    uv run determinism-check.py --flow <FlowName>

The pure compare_aggregates function is importable without Metaflow for
unit-testing purposes.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Pure comparison logic (no Metaflow dependency — unit-testable in isolation)
# ---------------------------------------------------------------------------

def canonicalize_cell(cell: dict[str, Any]) -> tuple:
    """Return a stable, hashable key for a cell dict.

    Sorts keys so insertion order does not affect equality. Converts list
    values to tuples recursively so unhashable lists do not break set/dict
    lookups and so ordering within a list-valued axis (e.g. band: [0.0, 0.02])
    is preserved as part of the identity.
    """
    def _to_hashable(v: Any) -> Any:
        if isinstance(v, list):
            return tuple(_to_hashable(item) for item in v)
        return v

    return tuple(sorted((k, _to_hashable(v)) for k, v in cell.items()))


# Fields compared per lift_results row (beyond the cell key).
_LIFT_FIELDS = ("lift_mean", "lift_lo", "lift_hi", "ci_excludes_zero", "n_seeds")


def compare_aggregates(
    lift_a: list[dict],
    agg_a: list[dict],
    lift_b: list[dict],
    agg_b: list[dict],
) -> list[str]:
    """Compare the aggregate-step outputs of two runs for exact equality.

    Parameters
    ----------
    lift_a, lift_b:
        lift_results artifacts from run A and run B respectively.
        Each element: {cell: dict, lift_mean: float, lift_lo: float,
                       lift_hi: float, ci_excludes_zero: bool, n_seeds: int}
    agg_a, agg_b:
        aggregate_results artifacts from run A and run B.
        Each element: {cell: dict, method: str, <primary_metric>_mean: float, ...}

    Returns
    -------
    list[str]
        Human-readable diff strings. Empty list means the two runs are identical.
    """
    diffs: list[str] = []
    diffs.extend(_compare_lift(lift_a, lift_b))
    diffs.extend(_compare_agg(agg_a, agg_b))
    return diffs


def _compare_lift(lift_a: list[dict], lift_b: list[dict]) -> list[str]:
    """Compare lift_results rows, matched by canonicalized cell key."""
    map_a = {canonicalize_cell(row["cell"]): row for row in lift_a}
    map_b = {canonicalize_cell(row["cell"]): row for row in lift_b}

    diffs: list[str] = []
    keys_a = set(map_a)
    keys_b = set(map_b)

    for key in keys_a - keys_b:
        diffs.append(
            f"[lift_results] cell present in run A but not run B: "
            f"{_format_key(key)}"
        )
    for key in keys_b - keys_a:
        diffs.append(
            f"[lift_results] cell present in run B but not run A: "
            f"{_format_key(key)}"
        )

    for key in keys_a & keys_b:
        row_a = map_a[key]
        row_b = map_b[key]
        for field in _LIFT_FIELDS:
            va = row_a.get(field)
            vb = row_b.get(field)
            if va != vb:
                diffs.append(
                    f"[lift_results] cell={_format_key(key)} "
                    f"field={field} run_a={va!r} run_b={vb!r}"
                )

    return diffs


def _compare_agg(agg_a: list[dict], agg_b: list[dict]) -> list[str]:
    """Compare aggregate_results rows, matched by (cell, method)."""
    def _key(row: dict) -> tuple:
        return (canonicalize_cell(row["cell"]), row["method"])

    def _metric_fields(row: dict) -> dict:
        return {k: v for k, v in row.items() if k not in ("cell", "method")}

    map_a = {_key(row): _metric_fields(row) for row in agg_a}
    map_b = {_key(row): _metric_fields(row) for row in agg_b}

    diffs: list[str] = []
    keys_a = set(map_a)
    keys_b = set(map_b)

    for key in keys_a - keys_b:
        cell_key, method = key
        diffs.append(
            f"[aggregate_results] (cell={_format_key(cell_key)}, method={method!r}) "
            f"present in run A but not run B"
        )
    for key in keys_b - keys_a:
        cell_key, method = key
        diffs.append(
            f"[aggregate_results] (cell={_format_key(cell_key)}, method={method!r}) "
            f"present in run B but not run A"
        )

    for key in keys_a & keys_b:
        cell_key, method = key
        fields_a = map_a[key]
        fields_b = map_b[key]

        if set(fields_a) != set(fields_b):
            diffs.append(
                f"[aggregate_results] (cell={_format_key(cell_key)}, method={method!r}) "
                f"metric key sets differ: run_a={sorted(fields_a)!r} "
                f"run_b={sorted(fields_b)!r}"
            )
            continue

        for field, va in fields_a.items():
            vb = fields_b[field]
            if va != vb:
                diffs.append(
                    f"[aggregate_results] (cell={_format_key(cell_key)}, "
                    f"method={method!r}) field={field} "
                    f"run_a={va!r} run_b={vb!r}"
                )

    return diffs


def _format_key(key: tuple) -> str:
    """Format a canonicalized cell key as a readable dict-like string."""
    return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in key) + "}"


# ---------------------------------------------------------------------------
# Metaflow access layer (isolated so tests never import it)
# ---------------------------------------------------------------------------

def _load_run(pathspec: str):
    from metaflow import Run  # noqa: PLC0415 — deferred to keep module importable

    return Run(pathspec)


def _latest_two_runs(flow_name: str):
    from metaflow import Flow  # noqa: PLC0415

    flow = Flow(flow_name)
    runs = list(flow.runs())
    if len(runs) < 2:
        print(
            f"ERROR: flow '{flow_name}' has fewer than 2 runs; "
            "cannot compare without at least two completed runs.",
            file=sys.stderr,
        )
        sys.exit(1)
    return runs[0], runs[1]


def _get_artifact(run, step_name: str, artifact_name: str):
    """Return a named artifact from a run's step, with a clear error on failure."""
    try:
        step = run[step_name]
    except KeyError:
        print(
            f"ERROR: run {run.pathspec!r} has no step {step_name!r}.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        task = next(iter(step.tasks()))
    except StopIteration:
        print(
            f"ERROR: step {step_name!r} in run {run.pathspec!r} has no tasks.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return getattr(task.data, artifact_name)
    except AttributeError:
        print(
            f"ERROR: artifact {artifact_name!r} not found in "
            f"{run.pathspec!r}/{step_name}.",
            file=sys.stderr,
        )
        sys.exit(1)


_CONTRACT_VALID_VALUES = frozenset(
    {"order_independent", "single_worker", "nondeterministic"}
)

_HOW_TO_REPRODUCE = {
    "order_independent": (
        "To produce two comparison runs: execute the flow twice at different "
        "--max-workers settings (e.g. --max-workers 1 and --max-workers 4). "
        "The aggregate outputs must be identical regardless of worker count."
    ),
    "single_worker": (
        "To produce two comparison runs: execute the flow twice, both times "
        "with --max-workers 1. "
        "The aggregate outputs must be identical between the two single-worker runs."
    ),
}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a Metaflow flow reproduces its aggregate outputs "
            "as its declared determinism contract claims."
        )
    )
    parser.add_argument(
        "runs",
        nargs="*",
        metavar="RUN_PATHSPEC",
        help=(
            "Two run pathspecs to compare (e.g. MyFlow/123 MyFlow/456). "
            "Omit to use the latest two runs of --flow."
        ),
    )
    parser.add_argument(
        "--flow",
        metavar="FLOW_NAME",
        help="Flow name to look up the latest two runs when no pathspecs are given.",
    )
    parser.add_argument(
        "--contract",
        choices=sorted(_CONTRACT_VALID_VALUES),
        metavar="CONTRACT",
        help=(
            "Override the determinism contract (fallback when the run artifact "
            "is absent). One of: order_independent, single_worker, nondeterministic. "
            "Final fallback if neither the artifact nor this flag is present: "
            "order_independent."
        ),
    )

    args = parser.parse_args(argv)

    # Resolve namespace so all runs are visible regardless of current user.
    from metaflow import namespace  # noqa: PLC0415

    namespace(None)

    # Resolve the two runs.
    if len(args.runs) == 2:
        run_a = _load_run(args.runs[0])
        run_b = _load_run(args.runs[1])
    elif len(args.runs) == 0:
        if not args.flow:
            print(
                "ERROR: supply two run pathspecs or --flow <FlowName>.",
                file=sys.stderr,
            )
            return 2
        run_a, run_b = _latest_two_runs(args.flow)
    else:
        print(
            f"ERROR: expected 0 or 2 run pathspecs, got {len(args.runs)}.",
            file=sys.stderr,
        )
        return 2

    # Resolve contract.
    contract: str
    try:
        contract = run_a.data.determinism
        if contract not in _CONTRACT_VALID_VALUES:
            print(
                f"WARNING: run artifact determinism={contract!r} is not a recognized "
                f"contract value; falling back to --contract / default.",
                file=sys.stderr,
            )
            raise AttributeError
    except AttributeError:
        contract = args.contract or "order_independent"

    print(f"Determinism contract: {contract!r}")
    print(f"Run A: {run_a.pathspec}")
    print(f"Run B: {run_b.pathspec}")

    # Nondeterministic escape hatch.
    if contract == "nondeterministic":
        print(
            "\nDeterminism check N/A — experiment declares nondeterministic by design "
            "(escape hatch). No comparison performed."
        )
        return 0

    # Pull aggregate artifacts.
    lift_a = _get_artifact(run_a, "aggregate", "lift_results")
    agg_a = _get_artifact(run_a, "aggregate", "aggregate_results")
    lift_b = _get_artifact(run_b, "aggregate", "lift_results")
    agg_b = _get_artifact(run_b, "aggregate", "aggregate_results")

    # Compare.
    diffs = compare_aggregates(lift_a, agg_a, lift_b, agg_b)

    if not diffs:
        print(f"\nPASS: aggregate outputs are identical ({contract} contract satisfied).")
        return 0

    print(f"\nFAIL: {len(diffs)} difference(s) found ({contract} contract violated):")
    for diff in diffs:
        print(f"  {diff}")
    print()
    print(_HOW_TO_REPRODUCE.get(contract, ""))
    return 1


if __name__ == "__main__":
    sys.exit(main())
