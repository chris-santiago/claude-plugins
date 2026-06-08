# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for flow-lint.py — the AST linter for the Metaflow pipeline standard.

Run with: uv run --with pytest pytest test_flow_lint.py -v

Two load-bearing invariants the suite guards:
  1. The annotated REFERENCE flow lints CLEAN (zero findings) — the positive
     control. If a rule ever fires on it, the rule is wrong, not the reference.
  2. A structurally DIFFERENT clean flow (different DAG shape, different step
     names) also lints clean — the linter must police INVARIANTS, not SHAPE.

Each rule additionally has one deliberately-broken fixture that triggers exactly
that rule and nothing else.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# flow-lint.py has a hyphen in its name, so load it as a module by path.
_HERE = Path(__file__).resolve().parent
_LINTER_PATH = _HERE.parent / "skills" / "pipeline-init" / "scripts" / "flow-lint.py"
_REFERENCE_FLOW = (
    _HERE.parent / "skills" / "pipeline-init" / "assets" / "reference_flow.py"
)

_spec = importlib.util.spec_from_file_location("flow_lint", _LINTER_PATH)
assert _spec is not None and _spec.loader is not None, (
    f"Could not load flow-lint spec from {_LINTER_PATH}; check the path."
)
flow_lint = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module by __module__ name.
sys.modules["flow_lint"] = flow_lint
_spec.loader.exec_module(flow_lint)

lint_source = flow_lint.lint_source


def rule_ids(src):
    return [f.rule_id for f in lint_source(src)]


# ── Positive control: the annotated reference flow ──────────────────────────

class TestReferenceFlowPositiveControl:
    """The shipped reference_flow.py MUST lint clean — zero findings."""

    def test_reference_flow_exists(self):
        assert _REFERENCE_FLOW.exists(), f"missing reference flow: {_REFERENCE_FLOW}"

    def test_reference_flow_zero_findings(self):
        findings = lint_source(
            _REFERENCE_FLOW.read_text(encoding="utf-8"), str(_REFERENCE_FLOW)
        )
        assert findings == [], "reference flow must be clean, got: " + "; ".join(
            f.render(_REFERENCE_FLOW.name) for f in findings
        )


# ── Rule: merge-artifacts-module ────────────────────────────────────────────

_BROKEN_MERGE = '''
class F:
    def join(self, inputs):
        self.all_records = [r for inp in inputs for r in inp.records]
        self.merge_artifacts(inputs)
        self.next(self.end)
'''

_CLEAN_MERGE_INCLUDE = '''
class F:
    def join(self, inputs):
        self.merge_artifacts(inputs, include=["data_cfg", "training_cfg"])
        self.next(self.end)
'''

_CLEAN_MERGE_EXCLUDE = '''
class F:
    def join(self, inputs):
        self.merge_artifacts(inputs, exclude=["models"])
        self.next(self.end)
'''


class TestMergeArtifactsModule:
    def test_broken_unconstrained_merge_flagged(self):
        ids = rule_ids(_BROKEN_MERGE)
        assert ids == ["merge-artifacts-module"]

    def test_include_is_clean(self):
        assert "merge-artifacts-module" not in rule_ids(_CLEAN_MERGE_INCLUDE)

    def test_exclude_is_clean(self):
        assert "merge-artifacts-module" not in rule_ids(_CLEAN_MERGE_EXCLUDE)


# ── Rule: cwd-relative-config ───────────────────────────────────────────────

_BROKEN_CONFIG_STR = '''
from metaflow import Config
cfg = Config("cfg", default="conf/config.yaml", parser=p)
'''

_BROKEN_CONFIG_PATH = '''
import pathlib
from metaflow import Config
cfg = Config("cfg", default=str(pathlib.Path("conf") / "config.yaml"))
'''

_CLEAN_CONFIG_FILE_ANCHORED = '''
import pathlib
from metaflow import Config
_CONF = pathlib.Path(__file__).resolve().parent / "conf"
cfg = Config("cfg", default=str(_CONF / "config.yaml"), parser=p)
'''

_CLEAN_CONFIG_DIRECT_FILE = '''
import pathlib
from metaflow import Config
cfg = Config("cfg", default=str(pathlib.Path(__file__).parent / "config.yaml"))
'''


class TestCwdRelativeConfig:
    def test_broken_bare_string_flagged(self):
        ids = rule_ids(_BROKEN_CONFIG_STR)
        assert ids == ["cwd-relative-config"]

    def test_broken_relative_path_flagged(self):
        assert "cwd-relative-config" in rule_ids(_BROKEN_CONFIG_PATH)

    def test_file_anchored_via_var_is_clean(self):
        assert "cwd-relative-config" not in rule_ids(_CLEAN_CONFIG_FILE_ANCHORED)

    def test_file_anchored_direct_is_clean(self):
        assert "cwd-relative-config" not in rule_ids(_CLEAN_CONFIG_DIRECT_FILE)


# ── Rule: per-config-foreach ────────────────────────────────────────────────

_BROKEN_FOREACH = '''
class F:
    def start(self):
        self.next(self.train, foreach="methods")
'''

_CLEAN_FOREACH_DATASET = '''
class F:
    def start(self):
        self.next(self.train, foreach="dataset_keys")
'''

_CLEAN_FOREACH_SEED = '''
class F:
    def start(self):
        self.next(self.train, foreach="seeds")
'''


class TestPerConfigForeach:
    def test_broken_methods_grain_flagged(self):
        ids = rule_ids(_BROKEN_FOREACH)
        assert ids == ["per-config-foreach"]

    def test_configs_grain_flagged(self):
        src = _BROKEN_FOREACH.replace('"methods"', '"configs"')
        assert "per-config-foreach" in rule_ids(src)

    def test_models_grain_flagged(self):
        src = _BROKEN_FOREACH.replace('"methods"', '"model_arms"')
        assert "per-config-foreach" in rule_ids(src)

    def test_dataset_grain_is_clean(self):
        assert "per-config-foreach" not in rule_ids(_CLEAN_FOREACH_DATASET)

    def test_seed_grain_is_clean(self):
        assert "per-config-foreach" not in rule_ids(_CLEAN_FOREACH_SEED)


# ── Rule: bare-project-import ───────────────────────────────────────────────

_BROKEN_IMPORT = '''
import numpy as np
from my_project import primary_metric_lib
'''

_CLEAN_IMPORT_SHIMMED = '''
import pathlib
import sys
_SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from my_project import primary_metric_lib
'''

_CLEAN_IMPORT_THIRD_PARTY = '''
import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from metaflow import FlowSpec
'''


class TestBareProjectImport:
    def test_broken_no_shim_flagged(self):
        ids = rule_ids(_BROKEN_IMPORT)
        assert ids == ["bare-project-import"]

    def test_plain_import_first_party_flagged(self):
        src = "import my_project\n"
        assert "bare-project-import" in rule_ids(src)

    def test_shim_before_import_is_clean(self):
        assert "bare-project-import" not in rule_ids(_CLEAN_IMPORT_SHIMMED)

    def test_third_party_imports_are_clean(self):
        assert "bare-project-import" not in rule_ids(_CLEAN_IMPORT_THIRD_PARTY)

    def test_shim_after_import_still_flags(self):
        src = (
            "import sys\n"
            "from my_project import x\n"
            "sys.path.insert(0, 'src')\n"
        )
        assert "bare-project-import" in rule_ids(src)


# ── Rule: module-global-experiment-const ────────────────────────────────────

_BROKEN_CONST = '''
N_SEEDS = 5

class F:
    def start(self):
        for s in range(N_SEEDS):
            print(s)
        self.next(self.end)
'''

_BROKEN_ANN_ASSIGN_CONST = '''
N_SEEDS: int = 5

class F:
    def start(self):
        for s in range(N_SEEDS):
            print(s)
        self.next(self.end)
'''

_BROKEN_BUDGETS_LIST = '''
BUDGETS = [0.005, 0.01]

class F:
    def start(self):
        for b in BUDGETS:
            print(b)
        self.next(self.end)
'''

_BROKEN_MIX_LIST = '''
MIX = ["a", 5]

class F:
    def start(self):
        for x in MIX:
            print(x)
        self.next(self.end)
'''

# Structural constants: pure-string scalar, bool, None, pure-string collection.
# ALL of these must be clean — the standard explicitly allows them as they are
# not hardcoded experiment parameters.
_CLEAN_STRUCTURAL_CONSTS = '''
LABEL_COL = "target"
SCHEMA_VERSION = "v1"
DEBUG = False
SENTINEL = None

class F:
    def start(self):
        print(LABEL_COL, SCHEMA_VERSION, DEBUG, SENTINEL)
        self.next(self.end)
'''

# Pure-string list: an axis-name list is a structural constant, not a numeric
# experiment parameter. The pipeline-reviewer "axes-match-source" judgment check
# handles string axis lists — this lint rule deliberately does not flag them.
_CLEAN_STRING_LIST_CONST = '''
AXES = ["sep", "eval_k"]

class F:
    def start(self):
        print(AXES)
        self.next(self.end)
'''

# A step that locally rebinds a module-global name should NOT be flagged: the
# local assignment shadows the global, so the read refers to the local.
_CLEAN_LOCAL_REBIND = '''
N_SEEDS = 5

class F:
    def start(self):
        N_SEEDS = len(self.cfg["seeds"])
        for s in range(N_SEEDS):
            print(s)
        self.next(self.end)
'''

_CLEAN_REGISTRY = '''
TRAIN_REGISTRY = {"ce": _train_ce, "topk": _train_topk}

class F:
    def train(self):
        fn = TRAIN_REGISTRY[self.kind]
        self.next(self.end)
'''

_CLEAN_FROZENSET = '''
AGNOSTIC = frozenset({"ce"})

class F:
    def train(self):
        ok = self.kind in AGNOSTIC
        self.next(self.end)
'''

_CLEAN_CONST_NOT_IN_STEP = '''
N_SEEDS = 5

def helper():
    return N_SEEDS

class F:
    def start(self):
        self.next(self.end)
'''


class TestModuleGlobalExperimentConst:
    def _decorate(self, src):
        # The step-detection rule keys on @step/@card; wrap method bodies.
        return src.replace("    def ", "    @step\n    def ")

    def test_broken_literal_const_read_in_step_flagged(self):
        ids = rule_ids(self._decorate(_BROKEN_CONST))
        assert ids == ["module-global-experiment-const"]

    def test_list_const_read_in_step_flagged(self):
        src = self._decorate(_BROKEN_CONST).replace("N_SEEDS = 5", "AXES = [1, 2, 3]")
        src = src.replace("range(N_SEEDS)", "AXES")
        assert "module-global-experiment-const" in rule_ids(src)

    def test_float_budget_const_flagged(self):
        src = self._decorate(_BROKEN_CONST).replace("N_SEEDS = 5", "BUDGET = 0.01")
        src = src.replace("range(N_SEEDS)", "[BUDGET]")
        assert "module-global-experiment-const" in rule_ids(src)

    def test_registry_dict_is_clean(self):
        assert "module-global-experiment-const" not in rule_ids(
            self._decorate(_CLEAN_REGISTRY)
        )

    def test_frozenset_constructor_is_clean(self):
        assert "module-global-experiment-const" not in rule_ids(
            self._decorate(_CLEAN_FROZENSET)
        )

    def test_const_not_read_in_step_is_clean(self):
        assert "module-global-experiment-const" not in rule_ids(
            self._decorate(_CLEAN_CONST_NOT_IN_STEP)
        )


class TestModuleGlobalExperimentConstNarrowing:
    """Lock the narrowed numeric-only predicate for module-global-experiment-const.

    Structural constants (pure-string scalars, bool, None, pure-string lists)
    MUST NOT be flagged. Only NUMERIC-bearing values trigger the rule.
    """

    def _decorate(self, src):
        return src.replace("    def ", "    @step\n    def ")

    # --- must NOT flag (structural / non-numeric constants) ---

    def test_pure_string_scalar_consts_are_clean(self):
        """LABEL_COL, SCHEMA_VERSION, DEBUG, SENTINEL all clean when read in a step."""
        ids = rule_ids(self._decorate(_CLEAN_STRUCTURAL_CONSTS))
        assert "module-global-experiment-const" not in ids, (
            "pure-string/bool/None consts must not flag; got: " + str(ids)
        )

    def test_pure_string_list_const_is_clean(self):
        """AXES = ['sep', 'eval_k'] (pure-string list) must not flag."""
        ids = rule_ids(self._decorate(_CLEAN_STRING_LIST_CONST))
        assert "module-global-experiment-const" not in ids, (
            "pure-string list const must not flag; got: " + str(ids)
        )

    def test_local_rebind_suppresses_flag(self):
        """A step that locally reassigns N_SEEDS must not flag the module global."""
        ids = rule_ids(self._decorate(_CLEAN_LOCAL_REBIND))
        assert "module-global-experiment-const" not in ids, (
            "locally-rebound name must not flag against module global; got: " + str(ids)
        )

    # --- must flag (numeric-bearing constants) ---

    def test_int_const_read_in_step_flags(self):
        """N_SEEDS = 5 (plain Assign, int) read in a step flags."""
        ids = rule_ids(self._decorate(_BROKEN_CONST))
        assert "module-global-experiment-const" in ids

    def test_ann_assign_int_const_flags(self):
        """N_SEEDS: int = 5 (AnnAssign) read in a step flags."""
        ids = rule_ids(self._decorate(_BROKEN_ANN_ASSIGN_CONST))
        assert "module-global-experiment-const" in ids, (
            "annotated numeric assignment must flag; got: " + str(ids)
        )

    def test_numeric_list_const_flags(self):
        """BUDGETS = [0.005, 0.01] (float list) read in a step flags."""
        ids = rule_ids(self._decorate(_BROKEN_BUDGETS_LIST))
        assert "module-global-experiment-const" in ids, (
            "numeric list const must flag; got: " + str(ids)
        )

    def test_mixed_string_numeric_list_flags(self):
        """MIX = ['a', 5] (mixed: contains a numeric) read in a step flags."""
        ids = rule_ids(self._decorate(_BROKEN_MIX_LIST))
        assert "module-global-experiment-const" in ids, (
            "mixed string+numeric list const must flag; got: " + str(ids)
        )


# ── Clean-but-structurally-different flow (invariant, not shape, policing) ───

# A DIFFERENT DAG: no select_by_val, a single analysis branch, differently-named
# steps (`prepare`/`fit`/`gather`/`summarize`), a Path(__file__)-anchored Config,
# a seed-keyed foreach, an exclude= merge, a sys.path shim before the first-party
# import, and a frozenset registry global. Every invariant honored, zero findings.
_CLEAN_DIFFERENT_FLOW = '''
from __future__ import annotations
import pathlib
import sys

_PKG = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import numpy as np
import torch.nn as nn
from metaflow import Config, FlowSpec, card, step

from analysis_pkg import scoring

_CONF_ROOT = pathlib.Path(__file__).parent / "conf"

FIT_REGISTRY = {"linear": _fit_linear, "tree": _fit_tree}


def make_data(spec, axes, seed):
    return {"X": None, "y": None}


class SingleBranchFlow(FlowSpec):
    cfg = Config("cfg", default=str(_CONF_ROOT / "config.yaml"))

    @step
    def prepare(self):
        self.dataset_keys = build_keys(self.cfg)
        self.next(self.fit, foreach="dataset_keys")

    @step
    def fit(self):
        dk = self.input
        self.records = train_all(dk)
        self.next(self.gather)

    @step
    def gather(self, inputs):
        self.all_records = [r for inp in inputs for r in inp.records]
        self.merge_artifacts(inputs, exclude=["records"])
        self.next(self.an_summary)

    @card
    @step
    def an_summary(self):
        self.an_result = {"rows": summarize(self.all_records)}
        self.next(self.summarize)

    @step
    def summarize(self):
        print(self.an_result)
        self.next(self.end)

    @step
    def end(self):
        print("done")
'''


class TestCleanButDifferentFlow:
    """A different-shaped flow that honors every invariant lints clean."""

    def test_zero_findings(self):
        findings = lint_source(_CLEAN_DIFFERENT_FLOW, "different_flow.py")
        assert findings == [], "different clean flow must be clean, got: " + "; ".join(
            f.render("different_flow.py") for f in findings
        )


# ── API / CLI smoke ─────────────────────────────────────────────────────────

class TestApiAndCli:
    def test_lint_source_raises_on_syntax_error(self):
        with pytest.raises(SyntaxError):
            lint_source("def (:\n")

    def test_findings_render_format(self):
        findings = lint_source(_BROKEN_FOREACH, "f.py")
        rendered = findings[0].render("f.py")
        assert rendered.startswith("f.py:")
        assert "[per-config-foreach]" in rendered

    def test_main_clean_file_exit_zero(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text(_CLEAN_FOREACH_DATASET)
        assert flow_lint.main([str(f)]) == 0

    def test_main_broken_file_exit_one(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text(_BROKEN_FOREACH)
        assert flow_lint.main([str(f)]) == 1

    def test_main_no_args_exit_two(self):
        assert flow_lint.main([]) == 2
