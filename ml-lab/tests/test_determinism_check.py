# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for determinism-check.py — pure-function unit tests for compare_aggregates.

Run with: uv run --with pytest pytest plugins/ml-lab/tests/test_determinism_check.py -v

These tests exercise only the pure compare_aggregates function and the
canonicalize_cell helper. No Metaflow imports or network access required.

The loader pattern reuses the importlib hyphen-module approach from test_flow_lint.py
because determinism-check.py also has a hyphen in its name.
"""

import importlib.util
import sys
from pathlib import Path

# determinism-check.py has a hyphen in its name, so load it as a module by path.
_HERE = Path(__file__).resolve().parent
_SCRIPT_PATH = (
    _HERE.parent / "skills" / "pipeline-init" / "scripts" / "determinism-check.py"
)

_spec = importlib.util.spec_from_file_location("determinism_check", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None, (
    f"Could not load determinism-check spec from {_SCRIPT_PATH}; check the path."
)
determinism_check = importlib.util.module_from_spec(_spec)
sys.modules["determinism_check"] = determinism_check
_spec.loader.exec_module(determinism_check)

compare_aggregates = determinism_check.compare_aggregates
canonicalize_cell = determinism_check.canonicalize_cell


# ── Fixtures: sample aggregate data ─────────────────────────────────────────

def _lift_row(cell, lift_mean, lift_lo, lift_hi, ci_excludes_zero=True, n_seeds=5):
    return {
        "cell": cell,
        "lift_mean": lift_mean,
        "lift_lo": lift_lo,
        "lift_hi": lift_hi,
        "ci_excludes_zero": ci_excludes_zero,
        "n_seeds": n_seeds,
    }


def _agg_row(cell, method, **metric_kwargs):
    return {"cell": cell, "method": method, **metric_kwargs}


_CELL_A = {"sep": 0.1, "eval_k": 10}
_CELL_B = {"sep": 0.2, "eval_k": 10}


# ── canonicalize_cell ────────────────────────────────────────────────────────

class TestCanonicalizeCell:
    def test_scalar_values_produce_sorted_tuple(self):
        cell = {"eval_k": 10, "sep": 0.1}
        result = canonicalize_cell(cell)
        # Keys sorted, values unchanged
        assert result == (("eval_k", 10), ("sep", 0.1))

    def test_keys_are_sorted_regardless_of_insertion_order(self):
        cell_forward = {"a": 1, "b": 2}
        cell_backward = {"b": 2, "a": 1}
        assert canonicalize_cell(cell_forward) == canonicalize_cell(cell_backward)

    def test_list_values_converted_to_tuples(self):
        cell = {"band": [0.0, 0.02], "eval_k": 10}
        result = canonicalize_cell(cell)
        # The list must become a tuple so it is hashable
        assert result == (("band", (0.0, 0.02)), ("eval_k", 10))

    def test_nested_list_values_converted_recursively(self):
        cell = {"band": [[0.0, 0.1], [0.2, 0.3]], "k": 5}
        result = canonicalize_cell(cell)
        assert result == (("band", ((0.0, 0.1), (0.2, 0.3))), ("k", 5))

    def test_result_is_hashable(self):
        cell = {"band": [0.0, 0.02], "sep": 0.1}
        key = canonicalize_cell(cell)
        # Must not raise — needed for dict/set lookups.
        _ = {key: "value"}


# ── compare_aggregates: identical inputs ────────────────────────────────────

class TestIdenticalInputs:
    def test_identical_lift_and_agg_returns_empty(self):
        lift = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift, agg, lift, agg)
        assert diffs == [], f"expected no diffs, got: {diffs}"

    def test_multiple_rows_identical_returns_empty(self):
        lift = [
            _lift_row(_CELL_A, 0.05, 0.01, 0.09),
            _lift_row(_CELL_B, 0.12, 0.08, 0.16, ci_excludes_zero=False, n_seeds=3),
        ]
        agg = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_B, "ce", recall_at_k_mean=0.75),
        ]
        diffs = compare_aggregates(lift, agg, lift, agg)
        assert diffs == [], f"expected no diffs, got: {diffs}"


# ── compare_aggregates: lift_results differences ────────────────────────────

class TestLiftResultsDifferences:
    def test_differing_lift_mean_reports_diff_naming_cell(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        lift_b = [_lift_row(_CELL_A, 0.06, 0.01, 0.09)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        # The diff message must mention the cell in some recognizable form.
        assert "lift_mean" in diffs[0]
        assert "sep" in diffs[0] or "eval_k" in diffs[0]

    def test_differing_lift_lo_reports_diff(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        lift_b = [_lift_row(_CELL_A, 0.05, 0.02, 0.09)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        assert "lift_lo" in diffs[0]

    def test_differing_lift_hi_reports_diff(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        lift_b = [_lift_row(_CELL_A, 0.05, 0.01, 0.10)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        assert "lift_hi" in diffs[0]

    def test_differing_ci_excludes_zero_reports_diff(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09, ci_excludes_zero=True)]
        lift_b = [_lift_row(_CELL_A, 0.05, 0.01, 0.09, ci_excludes_zero=False)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        assert "ci_excludes_zero" in diffs[0]

    def test_differing_n_seeds_reports_diff(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09, n_seeds=5)]
        lift_b = [_lift_row(_CELL_A, 0.05, 0.01, 0.09, n_seeds=3)]
        agg = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        assert "n_seeds" in diffs[0]


# ── compare_aggregates: missing cells ───────────────────────────────────────

class TestMissingCells:
    def test_cell_in_a_not_in_b_is_reported(self):
        lift_a = [
            _lift_row(_CELL_A, 0.05, 0.01, 0.09),
            _lift_row(_CELL_B, 0.12, 0.08, 0.16),
        ]
        lift_b = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_B, "topk", recall_at_k_mean=0.74),
        ]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg[:-1])
        # At least one diff must mention the missing cell.
        assert any("sep" in d or "eval_k" in d for d in diffs), (
            f"missing cell not reported; diffs: {diffs}"
        )

    def test_cell_in_b_not_in_a_is_reported(self):
        lift_a = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        lift_b = [
            _lift_row(_CELL_A, 0.05, 0.01, 0.09),
            _lift_row(_CELL_B, 0.12, 0.08, 0.16),
        ]
        agg_a = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        agg_b = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_B, "topk", recall_at_k_mean=0.74),
        ]
        diffs = compare_aggregates(lift_a, agg_a, lift_b, agg_b)
        assert len(diffs) > 0


# ── compare_aggregates: ordering independence ────────────────────────────────

class TestOrderIndependence:
    def test_lift_rows_in_different_order_are_equal(self):
        """Core property: same values, different row order -> empty diff.

        This proves the comparison is order-independent, which is the whole
        point of the order_independent contract.
        """
        lift_a = [
            _lift_row(_CELL_A, 0.05, 0.01, 0.09),
            _lift_row(_CELL_B, 0.12, 0.08, 0.16),
        ]
        lift_b = [
            _lift_row(_CELL_B, 0.12, 0.08, 0.16),
            _lift_row(_CELL_A, 0.05, 0.01, 0.09),
        ]
        agg_a = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_B, "ce", recall_at_k_mean=0.75),
        ]
        agg_b = [
            _agg_row(_CELL_B, "ce", recall_at_k_mean=0.75),
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
        ]
        diffs = compare_aggregates(lift_a, agg_a, lift_b, agg_b)
        assert diffs == [], (
            "reordered but otherwise identical inputs must produce no diffs; "
            f"got: {diffs}"
        )

    def test_agg_rows_in_different_order_are_equal(self):
        lift = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg_a = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_A, "ce", recall_at_k_mean=0.75),
        ]
        agg_b = [
            _agg_row(_CELL_A, "ce", recall_at_k_mean=0.75),
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
        ]
        diffs = compare_aggregates(lift, agg_a, lift, agg_b)
        assert diffs == [], f"reordered agg rows must produce no diffs; got: {diffs}"


# ── compare_aggregates: aggregate_results differences ───────────────────────

class TestAggregateResultsDifferences:
    def test_differing_primary_metric_value_is_reported(self):
        lift = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg_a = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        agg_b = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.79)]
        diffs = compare_aggregates(lift, agg_a, lift, agg_b)
        assert len(diffs) == 1
        assert "recall_at_k_mean" in diffs[0]

    def test_different_metric_key_set_is_reported(self):
        lift = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg_a = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        agg_b = [_agg_row(_CELL_A, "topk", precision_at_k_mean=0.82)]
        diffs = compare_aggregates(lift, agg_a, lift, agg_b)
        assert len(diffs) >= 1

    def test_missing_method_in_b_is_reported(self):
        lift = [_lift_row(_CELL_A, 0.05, 0.01, 0.09)]
        agg_a = [
            _agg_row(_CELL_A, "topk", recall_at_k_mean=0.82),
            _agg_row(_CELL_A, "ce", recall_at_k_mean=0.75),
        ]
        agg_b = [_agg_row(_CELL_A, "topk", recall_at_k_mean=0.82)]
        diffs = compare_aggregates(lift, agg_a, lift, agg_b)
        assert len(diffs) > 0


# ── compare_aggregates: list-valued cell axis ────────────────────────────────

class TestListValuedCellAxis:
    def test_band_axis_list_value_canonicalizes_and_matches(self):
        """Cell with a list-valued axis (e.g. band: [0.0, 0.02]) must not raise
        and must match correctly across runs."""
        cell = {"band": [0.0, 0.02], "eval_k": 10}
        lift = [_lift_row(cell, 0.07, 0.02, 0.12)]
        agg = [_agg_row(cell, "topk", recall_at_k_mean=0.83)]
        diffs = compare_aggregates(lift, agg, lift, agg)
        assert diffs == [], f"list-valued cell must match; got: {diffs}"

    def test_band_axis_list_value_different_order_matches(self):
        """Same list-valued cell in different row orders still matches."""
        cell_1 = {"band": [0.0, 0.02], "eval_k": 5}
        cell_2 = {"band": [0.0, 0.02], "eval_k": 10}
        lift_a = [_lift_row(cell_1, 0.05, 0.01, 0.09), _lift_row(cell_2, 0.07, 0.02, 0.12)]
        lift_b = [_lift_row(cell_2, 0.07, 0.02, 0.12), _lift_row(cell_1, 0.05, 0.01, 0.09)]
        agg_a = [_agg_row(cell_1, "topk", recall_at_k_mean=0.80), _agg_row(cell_2, "topk", recall_at_k_mean=0.83)]
        agg_b = [_agg_row(cell_2, "topk", recall_at_k_mean=0.83), _agg_row(cell_1, "topk", recall_at_k_mean=0.80)]
        diffs = compare_aggregates(lift_a, agg_a, lift_b, agg_b)
        assert diffs == [], f"list-valued cell reordered must match; got: {diffs}"

    def test_band_axis_list_value_differing_detects_difference(self):
        """When values genuinely differ, even with list-valued cells, a diff is reported."""
        cell = {"band": [0.0, 0.02], "eval_k": 10}
        lift_a = [_lift_row(cell, 0.07, 0.02, 0.12)]
        lift_b = [_lift_row(cell, 0.08, 0.02, 0.12)]  # lift_mean differs
        agg = [_agg_row(cell, "topk", recall_at_k_mean=0.83)]
        diffs = compare_aggregates(lift_a, agg, lift_b, agg)
        assert len(diffs) == 1
        assert "lift_mean" in diffs[0]
