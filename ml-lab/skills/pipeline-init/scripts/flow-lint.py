# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Deterministic AST linter for the ml-lab Metaflow + Hydra pipeline standard.

Detects five MECHANICAL anti-patterns that the pipeline standard forbids. Every
check is purely structural (stdlib `ast` only, no regex over source, no project
deps) so it runs anywhere `python` runs and never imports the flow under test.

Rules
-----
merge-artifacts-module
    `merge_artifacts(...)` with NO `include=`/`exclude=` keyword. An unconstrained
    merge compares every artifact for equality across branches; an `nn.Module`
    (or tensor) artifact raises when compared, so the merge must be scoped.

cwd-relative-config
    A `Config(...)` whose `default=` is a CWD-relative path (bare string literal
    or `Path("...")`) instead of a `__file__`-anchored expression. CWD-relative
    config defaults break under `uv run` script mode.

per-config-foreach
    `self.next(self.<step>, foreach="<attr>")` whose `<attr>` names a per-method /
    per-config list instead of the dataset/data-axis grain. Fanning out per
    config explodes the branch count and regenerates data redundantly.

bare-project-import
    A first-party (`from <pkg> import ...` / `import <pkg>`) import with NO
    module-scope `sys.path.insert(...)` lexically preceding it. Without the shim
    the project package is not importable under `uv run` script mode.

module-global-experiment-const
    A module-level UPPERCASE name bound to a literal (or literal collection) that
    is READ inside a `@step`/`@card` body. Hardcoded experiment parameters belong
    in Hydra config, not in module globals consumed by a step.

CLI
---
    flow-lint.py <flow.py> [<flow.py> ...]

Prints one line per finding (`file:line  [rule-id]  message`) and exits non-zero
if any finding is reported.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass


# ── Allowlist for the bare-project-import rule ──────────────────────────────
# A top-level package NOT in this set is treated as first-party. The rule only
# fires on first-party imports lacking a preceding sys.path.insert, so this list
# is deliberately broad: every stdlib top-level module plus the common
# third-party packages a flow legitimately imports without a path shim.
_THIRD_PARTY = frozenset({
    "metaflow", "hydra", "omegaconf", "torch", "numpy", "np", "sklearn",
    "pandas", "scipy", "yaml", "pytest", "matplotlib", "seaborn",
    "lightning", "pytorch_lightning", "transformers", "datasets",
    "tqdm", "joblib", "requests", "pydantic", "click", "typer",
})

_STDLIB = frozenset(sys.stdlib_module_names) | frozenset({"__future__"})

_ALLOWED_TOP_PKGS = _THIRD_PARTY | _STDLIB


@dataclass(frozen=True)
class Finding:
    """One linter finding. `line` is 1-based, matching the source file."""

    line: int
    rule_id: str
    message: str

    def render(self, filename: str) -> str:
        return f"{filename}:{self.line}  [{self.rule_id}]  {self.message}"


# ── Shared AST predicates ───────────────────────────────────────────────────

def _call_func_name(call: ast.Call) -> str | None:
    """Return the bare callee name for `foo(...)` or `obj.foo(...)`, else None."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_literal_node(node: ast.expr) -> bool:
    """True if `node` is a literal scalar or a collection of literals.

    A dict/list/tuple/set counts as literal only when EVERY element is itself a
    literal (recursively). This is what separates a hardcoded parameter table
    (`AXES = [1, 2, 3]`) from a dispatch registry (`{"ce": _train_ce}`), whose
    values are Names rather than literals.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_node(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            k is not None and _is_literal_node(k) and _is_literal_node(v)
            for k, v in zip(node.keys, node.values)
        )
    # Unary minus on a literal (e.g. -1, -0.5) is still a literal.
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_literal_node(node.operand)
    return False


def _is_numeric_literal(node: ast.expr) -> bool:
    """True if `node` is a bare numeric literal (int or float, NOT bool).

    bool is excluded because True/False are structural flags, not experiment
    parameters. None and str are also excluded for the same reason.
    """
    if isinstance(node, ast.Constant):
        # isinstance(True, int) is True in Python, so test bool first.
        if isinstance(node.value, bool):
            return False
        return isinstance(node.value, (int, float))
    # Unary minus on a numeric literal (e.g. -1, -0.5).
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_numeric_literal(node.operand)
    return False


def _contains_numeric_literal(node: ast.expr) -> bool:
    """True if `node` is a numeric literal OR a collection/dict whose literal
    contents include at least one numeric literal (recursively).

    Deliberately conservative narrowing for the module-global-experiment-const
    rule: the anti-pattern is hardcoded NUMERIC experiment parameters (seeds,
    budgets, epoch counts, learning rates) that belong in Hydra config.
    Pure-string scalars, bool, None, and pure-string collections are NOT flagged
    here because they are legitimate structural constants (e.g. LABEL_COL =
    "target", SCHEMA_VERSION = "v1", DEBUG = False). Axis-name string lists like
    AXES = ["sep", "eval_k"] are also left clean; the pipeline-reviewer agent's
    "axes-match-source" judgment check handles those, not this lint rule.
    """
    if _is_numeric_literal(node):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        # Must be an all-literal collection that contains at least one numeric.
        if not all(_is_literal_node(e) for e in node.elts):
            return False
        return any(_contains_numeric_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        # Must be an all-literal dict that contains at least one numeric value.
        if not all(
            k is not None and _is_literal_node(k) and _is_literal_node(v)
            for k, v in zip(node.keys, node.values)
        ):
            return False
        return any(
            _contains_numeric_literal(k) or _contains_numeric_literal(v)
            for k, v in zip(node.keys, node.values)
            if k is not None
        )
    return False


def _refers_to_file(node: ast.expr, file_anchored_names: set[str]) -> bool:
    """True if `node`'s subtree references `__file__` or a `__file__`-derived name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            if sub.id == "__file__" or sub.id in file_anchored_names:
                return True
    return False


def _names_read(node: ast.AST) -> set[str]:
    """All bare names loaded (read) anywhere within `node`."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            out.add(sub.id)
    return out


def _is_step_decorated(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if a function carries a Metaflow `@step`/`@card` decorator."""
    for dec in func.decorator_list:
        name = dec.attr if isinstance(dec, ast.Attribute) else (
            dec.id if isinstance(dec, ast.Name) else None
        )
        if name in {"step", "card"}:
            return True
    return False


# ── Rule: merge-artifacts-module ────────────────────────────────────────────

def _check_merge_artifacts(tree: ast.Module) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_func_name(node) != "merge_artifacts":
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "include" not in kwargs and "exclude" not in kwargs:
            findings.append(Finding(
                node.lineno,
                "merge-artifacts-module",
                "merge_artifacts() has no include=/exclude=; an unconstrained "
                "merge compares every artifact and raises on an nn.Module/tensor. "
                "Scope it with include=[...] of flat artifacts.",
            ))
    return findings


# ── Rule: cwd-relative-config ───────────────────────────────────────────────

def _config_default_node(call: ast.Call) -> ast.expr | None:
    """The `default=` value of a `Config(...)` call (2nd positional or keyword)."""
    for kw in call.keywords:
        if kw.arg == "default":
            return kw.value
    # Positional: Config(name, default, ...) -> index 1 is the default.
    if len(call.args) >= 2:
        return call.args[1]
    return None


def _check_cwd_relative_config(
    tree: ast.Module, file_anchored_names: set[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_func_name(node) != "Config":
            continue
        default = _config_default_node(node)
        if default is None:
            continue
        if _refers_to_file(default, file_anchored_names):
            continue  # __file__-anchored -> CLEAN
        findings.append(Finding(
            default.lineno,
            "cwd-relative-config",
            "Config default= is not anchored to __file__; a CWD-relative path "
            "breaks under `uv run` script mode. Anchor it via "
            "Path(__file__).parent / ...",
        ))
    return findings


# ── Rule: per-config-foreach ────────────────────────────────────────────────
# Intentionally NAME-BASED: the foreach grain must be the data/dataset axis, not
# a per-method/per-config list. We flag a foreach attribute whose name ends in
# method(s)/arm(s)/config(s)/model(s). A name mentioning the data axis
# (dataset/data/cell/key/seed/branch) is always CLEAN even if it also matches a
# per-config token, because data-grain naming is the explicit correct signal.

_PER_CONFIG_TOKENS = ("method", "arm", "config", "model")
_DATA_GRAIN_TOKENS = ("dataset", "data", "cell", "key", "seed", "branch")


def _foreach_grain_is_per_config(attr: str) -> bool:
    lowered = attr.lower()
    if any(tok in lowered for tok in _DATA_GRAIN_TOKENS):
        return False  # explicit data-grain naming wins
    stem = lowered[:-1] if lowered.endswith("s") else lowered
    return any(stem.endswith(tok) for tok in _PER_CONFIG_TOKENS)


def _check_per_config_foreach(tree: ast.Module) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_func_name(node) != "next":
            continue
        for kw in node.keywords:
            if kw.arg != "foreach" or not isinstance(kw.value, ast.Constant):
                continue
            attr = kw.value.value
            if isinstance(attr, str) and _foreach_grain_is_per_config(attr):
                findings.append(Finding(
                    node.lineno,
                    "per-config-foreach",
                    f"foreach={attr!r} fans out per method/config rather than "
                    "over the dataset/data axis. The foreach grain must be the "
                    "(data_axes + seed) dataset key.",
                ))
    return findings


# ── Rule: bare-project-import ───────────────────────────────────────────────

def _top_pkg(name: str) -> str:
    return name.split(".", 1)[0]


def _check_bare_project_import(tree: ast.Module) -> list[Finding]:
    """Flag first-party imports with no preceding module-scope sys.path.insert.

    Only module-level statements are considered: a sys.path.insert at module
    scope that lexically precedes the import makes that import (and every later
    first-party import) CLEAN.
    """
    findings: list[Finding] = []
    shim_seen = False
    for node in tree.body:
        if _is_sys_path_insert(node):
            shim_seen = True
            continue
        for top in _imported_first_party_pkgs(node):
            if not shim_seen:
                findings.append(Finding(
                    node.lineno,
                    "bare-project-import",
                    f"first-party import of {top!r} with no preceding module-scope "
                    "sys.path.insert(...). Add the path shim before importing the "
                    "project package so `uv run` script mode can resolve it.",
                ))
    return findings


def _is_sys_path_insert(node: ast.stmt) -> bool:
    """True if `node` is an `sys.path.insert(...)` call, possibly inside an `if`."""
    calls: list[ast.Call] = []
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        calls.append(node.value)
    elif isinstance(node, ast.If):
        # The reference uses `if str(_SRC) not in sys.path: sys.path.insert(...)`.
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                calls.append(sub)
    for call in calls:
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "insert"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "path"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "sys"
        ):
            return True
    return False


def _imported_first_party_pkgs(node: ast.stmt) -> list[str]:
    """First-party top-level package names imported by a module-level stmt."""
    pkgs: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = _top_pkg(alias.name)
            if top not in _ALLOWED_TOP_PKGS:
                pkgs.append(top)
    elif isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return []  # relative import, not a bare top-level package
        if node.module is None:
            return []
        top = _top_pkg(node.module)
        if top not in _ALLOWED_TOP_PKGS:
            pkgs.append(top)
    return pkgs


# ── Rule: module-global-experiment-const ────────────────────────────────────

def _module_literal_consts(tree: ast.Module) -> dict[str, int]:
    """Map UPPERCASE module-level names bound to a NUMERIC-bearing literal -> line.

    Only flags names whose value is a numeric scalar (int/float, not bool) or a
    collection/dict literal whose contents include at least one numeric literal
    (recursively). Pure-string scalars, bool, None, and pure-string collections
    are excluded: they are legitimate structural constants, not hardcoded
    experiment parameters.

    Handles both plain assignments (`ast.Assign`) and annotated assignments
    (`ast.AnnAssign`, e.g. `N_SEEDS: int = 5`) so annotated numeric consts are
    also caught.

    Excludes names bound to call results (registries/constructors), comprehensions,
    and any value whose elements are not all literals (dispatch tables).
    """
    consts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not _contains_numeric_literal(node.value):
                continue  # call results, registries, pure-string/bool/None consts
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_upper_const(target.id):
                    consts[target.id] = node.lineno
        elif isinstance(node, ast.AnnAssign):
            # e.g. N_SEEDS: int = 5 — only when a value is present.
            if node.value is None:
                continue
            if not _contains_numeric_literal(node.value):
                continue
            target = node.target
            if isinstance(target, ast.Name) and _is_upper_const(target.id):
                consts[target.id] = node.lineno
    return consts


def _is_upper_const(name: str) -> bool:
    """True for UPPERCASE constant names (allowing digits/underscores).

    Leading-underscore names (e.g. `_CONF_DIR`) still count as uppercase consts,
    but in practice those are bound to call results and excluded earlier. A name
    must contain at least one letter and have no lowercase letters.
    """
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and name.upper() == name


def _check_module_global_experiment_const(tree: ast.Module) -> list[Finding]:
    consts = _module_literal_consts(tree)
    if not consts:
        return []
    findings: list[Finding] = []
    reported: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_step_decorated(node):
            continue
        read = _names_read_in_body(node)
        for name in sorted(read & set(consts)):
            if name in reported:
                continue
            reported.add(name)
            findings.append(Finding(
                consts[name],
                "module-global-experiment-const",
                f"module-global literal {name!r} is read inside step "
                f"{node.name!r}. Hardcoded experiment parameters belong in Hydra "
                "config, not in a module global consumed by a step.",
            ))
    return findings


def _names_bound_in_body(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names bound (stored) anywhere inside a function body."""
    out: set[str] = set()
    for stmt in func.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                out.add(sub.id)
    return out


def _names_read_in_body(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names read inside a function body (decorators/signature excluded).

    Subtracts names that are locally bound within the same body: a step that
    reassigns a module-global name (`N_SEEDS = compute(); range(N_SEEDS)`) is
    reading its own local, not the module global.
    """
    read: set[str] = set()
    for stmt in func.body:
        read |= _names_read(stmt)
    return read - _names_bound_in_body(func)


# ── Module-scope __file__-derivation tracking (for cwd-relative-config) ──────

def _file_anchored_names(tree: ast.Module) -> set[str]:
    """Module-level names whose assigned value derives from `__file__`.

    Resolves transitively: a name assigned from another already-anchored name is
    itself anchored (single forward pass over module-level assignments).
    """
    anchored: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not _refers_to_file(node.value, anchored):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                anchored.add(target.id)
    return anchored


# ── Public API ──────────────────────────────────────────────────────────────

def lint_source(src: str, filename: str = "<source>") -> list[Finding]:
    """Lint Python source text, returning findings sorted by line then rule.

    Raises SyntaxError if `src` does not parse (the caller decides how to surface
    it); a malformed flow is itself a failure worth surfacing loudly.
    """
    tree = ast.parse(src, filename=filename)
    anchored = _file_anchored_names(tree)
    findings: list[Finding] = []
    findings += _check_merge_artifacts(tree)
    findings += _check_cwd_relative_config(tree, anchored)
    findings += _check_per_config_foreach(tree)
    findings += _check_bare_project_import(tree)
    findings += _check_module_global_experiment_const(tree)
    findings.sort(key=lambda f: (f.line, f.rule_id))
    return findings


def lint_file(path: str) -> list[Finding]:
    """Lint a single file by path."""
    with open(path, encoding="utf-8") as fh:
        return lint_source(fh.read(), filename=path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: flow-lint.py <flow.py> [<flow.py> ...]", file=sys.stderr)
        return 2

    total = 0
    for path in args:
        try:
            findings = lint_file(path)
        except FileNotFoundError:
            print(f"{path}: no such file", file=sys.stderr)
            return 2
        except SyntaxError as exc:
            print(f"{path}:{exc.lineno}  [syntax-error]  {exc.msg}", file=sys.stderr)
            return 2
        for finding in findings:
            print(finding.render(path))
        total += len(findings)

    if total:
        print(f"\n{total} finding(s) across {len(args)} file(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
