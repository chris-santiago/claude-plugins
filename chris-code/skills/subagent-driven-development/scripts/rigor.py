#!/usr/bin/env python3
"""
rigor.py — resolve the test rigor level (light < standard < heavy) for a
project, a plan task, or the files of a run (rigor-level spec §4.1-4.2, §6).

The project level comes from the repo-root CLAUDE.md line `Test rigor:
<level>` when there is one; otherwise from the counted source lines (base),
a language binding (floor at standard), and numeric or ML dependencies
(one step up, capped at heavy). A plan task's `Rigor:` line can raise its
task above the project level, never lower it.

Stateless and deterministic: it reads tracked files, CLAUDE.md, the plan,
and the store's stage entries, and writes nothing.

Exit codes: 0 resolved; 2 a bad CLAUDE.md value, a task `Rigor:` line
below the project level or unknown, or a usage error.

Usage: python3 rigor.py [--repo DIR]
       python3 rigor.py [--repo DIR] --plan PLAN --task N
       python3 rigor.py [--repo DIR] --plan PLAN --store STORE --files
"""

from __future__ import annotations

import argparse
import configparser
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import ledger  # this script's directory: the store's stage entries

LEVELS = ("light", "standard", "heavy")
LIGHT_BELOW = 5_000
HEAVY_ABOVE = 30_000

LANGUAGES = {
    ".py": "python", ".rs": "rust", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".c": "c", ".h": "c", ".cc": "c++", ".cpp": "c++", ".hpp": "c++",
    ".cs": "c#", ".rb": "ruby", ".swift": "swift", ".scala": "scala",
}
# Test, vendored, and generated paths: any of these directory segments.
EXCLUDED_DIRS = frozenset({"test", "tests", "vendor", "third_party", "node_modules",
                           "build", "dist", "target", "generated"})
EXCLUDED_NAME_RE = re.compile(
    r"^test_.*\.py$|_test\.(py|rs|go)$|^tests\.rs$|\.(test|spec)\.[^.]+$|_pb2\.py$")

CARGO_BINDINGS = frozenset({"pyo3", "napi", "wasm-bindgen", "cxx"})
PYTHON_BINDINGS = frozenset({"cffi"})
# "pytorch" is torch's conda package name.
PYTHON_NUMERIC = frozenset({"numpy", "scipy", "pandas", "polars", "torch", "pytorch", "jax",
                            "tensorflow", "scikit-learn"})
CARGO_NUMERIC = frozenset({"ndarray", "nalgebra", "polars", "arrow"})

CLAUDE_MD_LINE_RE = re.compile(
    r"^\s*(?:[-*+][ \t]+)?(?:\*\*)?Test rigor(?:\*\*)?:(?:\*\*)?(.*)$", re.IGNORECASE)
# A dependency name at the start of a PEP 508 string, a requirements line,
# or a conda spec (after any `channel::` prefix).
DEP_NAME_RE = re.compile(r"^\s*(?:[\w.-]+::)?([A-Za-z0-9][A-Za-z0-9._-]*)")


class RigorError(Exception):
    """A bad CLAUDE.md value, or a task `Rigor:` line that would lower or
    name no level: exit 2."""


@dataclass(frozen=True)
class Resolution:
    level: str
    reasons: tuple[str, ...]

    def line(self) -> str:
        return f"{self.level}: {'; '.join(self.reasons)}"


def _rank(level: str) -> int:
    return LEVELS.index(level)


def _git_lines(repo: Path, *args: str) -> list[str] | None:
    """A git command's NUL-separated output, or None outside a work tree."""
    try:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return None
    return [p for p in out.decode(errors="replace").split("\0") if p]


def _excluded(top: Path, rel: str) -> bool:
    """Tests, vendored and generated code, and tracked symlinks (git
    tracks the link, not what it points at)."""
    *dirs, name = rel.split("/")
    return (bool(EXCLUDED_DIRS.intersection(dirs)) or bool(EXCLUDED_NAME_RE.search(name))
            or (top / rel).is_symlink())


def _read(path: Path) -> str | None:
    """A regular file's text, or None: a device or FIFO would never end."""
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def level_word(value: str) -> str:
    """The level a `Test rigor:` or `Rigor:` value names: its first word,
    lowercased, without markdown decoration or trailing punctuation. Words
    after it are a note ("heavy, NaN inputs are realistic")."""
    words = value.replace("*", "").replace("`", "").split()
    return words[0].rstrip(".,;:!?)").lower() if words else ""


def _claude_md_level(top: Path) -> str | None:
    text = _read(top / "CLAUDE.md")
    if text is None:
        return None
    # Here, not at module level: task_brief imports this module.
    from task_brief import _iter_fence_aware
    for line, in_fence in _iter_fence_aware(text.splitlines()):
        m = None if in_fence else CLAUDE_MD_LINE_RE.match(line)
        if m:
            value = level_word(m.group(1))
            if value not in LEVELS:
                raise RigorError(f"CLAUDE.md: 'Test rigor: {m.group(1).strip()}' is not a level; "
                                 f"write one of {', '.join(LEVELS)}")
            return value
    return None


def _count_source(top: Path, files: list[str]) -> tuple[int, list[str]]:
    """Non-blank lines in counted source files, and their languages,
    most lines first."""
    per_language: Counter[str] = Counter()
    for rel in files:
        language = LANGUAGES.get(Path(rel).suffix)
        if language is None or _excluded(top, rel):
            continue
        text = _read(top / rel)
        if text is not None:
            per_language[language] += sum(1 for line in text.splitlines() if line.strip())
    languages = [lang for lang, n in per_language.most_common() if n]
    return sum(per_language.values()), languages


def _normalize_dep(name: str) -> str:
    """PEP 503: case and any run of `-`, `_` or `.` don't distinguish names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _dep_name(spec: str) -> str | None:
    m = DEP_NAME_RE.match(spec)
    return _normalize_dep(m.group(1)) if m else None


def _cargo_deps(data: dict) -> set[str]:
    """Every dependency key in any `*dependencies` table, at any depth
    (workspace and target-specific tables included)."""
    names = set()
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if key.endswith("dependencies"):
            names |= {_normalize_dep(k) for k in value}
        else:
            names |= _cargo_deps(value)
    return names


def _pyproject_deps(data: dict) -> set[str]:
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs += group
    for group in data.get("dependency-groups", {}).values():
        specs += [s for s in group if isinstance(s, str)]
    names = {n for s in specs if isinstance(s, str) and (n := _dep_name(s))}
    poetry = data.get("tool", {}).get("poetry", {})
    tables = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    tables += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
    return names | {_normalize_dep(k) for t in tables for k in t}


def _setup_cfg_deps(text: str) -> set[str]:
    # No interpolation: a `%` in a wheel URL (`%2B`) is literal text.
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    specs = parser.get("options", "install_requires", fallback="").splitlines()
    if parser.has_section("options.extras_require"):
        for _, value in parser.items("options.extras_require"):
            specs += value.splitlines()
    return {n for s in specs if (n := _dep_name(s))}


def _line_deps(text: str, *, item_prefix: str = "") -> set[str]:
    """Names from a requirements file (item_prefix "") or the list items of
    an environment.yml (item_prefix "-"); comments and options skipped."""
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if item_prefix:
            if not line.startswith(item_prefix):
                continue
            line = line[len(item_prefix):].strip()
        if line and not line.startswith("-") and (name := _dep_name(line)):
            names.add(name)
    return names


def _is_manifest(name: str) -> bool:
    return name in ("Cargo.toml", "pyproject.toml", "setup.cfg", "environment.yml") or (
        name.startswith("requirements") and name.endswith(".txt"))


def _manifest_markers(name: str, text: str) -> tuple[set[str], set[str]]:
    """(binding markers, numeric markers) in one manifest. Raises on a
    manifest that doesn't parse, or parses to an unexpected shape."""
    if name == "Cargo.toml":
        deps = _cargo_deps(tomllib.loads(text))
        return deps & CARGO_BINDINGS, deps & CARGO_NUMERIC
    bindings = set()
    if name == "pyproject.toml":
        data = tomllib.loads(text)
        build = data.get("build-system", {})
        requires = {n for s in build.get("requires", []) if (n := _dep_name(s))}
        if "maturin" in requires or "maturin" in str(build.get("build-backend", "")):
            bindings.add("maturin")
        deps = _pyproject_deps(data)
    elif name == "setup.cfg":
        deps = _setup_cfg_deps(text)
    else:
        deps = _line_deps(text, item_prefix="-" if name == "environment.yml" else "")
    return bindings | (deps & PYTHON_BINDINGS), deps & PYTHON_NUMERIC


def _markers(top: Path, files: list[str]) -> tuple[set[str], set[str]]:
    """(binding markers, numeric markers) found in the tracked manifests.
    A manifest that doesn't parse is skipped: the level is a heuristic,
    and a broken manifest fails its own build loudly enough."""
    bindings, numeric = set(), set()
    for rel in files:
        name = rel.rsplit("/", 1)[-1]
        if not _is_manifest(name) or _excluded(top, rel) or (text := _read(top / rel)) is None:
            continue
        try:
            found_bindings, found_numeric = _manifest_markers(name, text)
        except (ValueError, TypeError, AttributeError, configparser.Error):
            continue
        bindings |= found_bindings
        numeric |= found_numeric
    return bindings, numeric


def project_level(repo: Path) -> Resolution:
    """The project's level and the reasons for it (spec §4.1). Raises
    RigorError on a CLAUDE.md `Test rigor:` value that names no level."""
    top_lines = _git_lines(repo, "rev-parse", "--show-toplevel")
    if not top_lines:
        return Resolution("standard", (f"{repo} is not a git work tree",))
    top = Path(top_lines[0].strip())
    declared = _claude_md_level(top)
    if declared is not None:
        return Resolution(declared, ("set in CLAUDE.md",))
    files = _git_lines(top, "ls-files", "-z") or []
    lines, languages = _count_source(top, files)
    if not lines:
        return Resolution("standard", ("no tracked source to count",))
    level = "light" if lines < LIGHT_BELOW else "standard" if lines <= HEAVY_ABOVE else "heavy"
    reasons = [f"{lines:,} source lines ({', '.join(languages)})"]
    bindings, numeric = _markers(top, files)
    if bindings and _rank(level) < _rank("standard"):
        level = "standard"
        reasons.append(f"{', '.join(sorted(bindings))} binding: floor standard")
    if numeric and level != "heavy":
        level = LEVELS[_rank(level) + 1]
        reasons.append(f"{', '.join(sorted(numeric))} +1")
    return Resolution(level, tuple(reasons))


def task_level(project: Resolution, declared: str | None, task: str) -> Resolution:
    """A task's level from its plan `Rigor:` value (None when it has
    none): the project level, or the higher one the line raises it to
    (spec §4.2). A value below the project level, or no level, raises
    RigorError."""
    if declared is None or declared == project.level:
        return project
    if declared not in LEVELS or _rank(declared) < _rank(project.level):
        raise RigorError(
            f"task {task}: 'Rigor: {declared}' would lower or name no level; the project is "
            f"{project.line()}. A task's Rigor: line can only raise it (standard or heavy)")
    return Resolution(declared, (f"task {task} raised from {project.level}", *project.reasons))


def _plan_task_level(task_brief, project: Resolution, plan_text: str, task: str) -> Resolution:
    entry = task_brief.extract_task_entry(plan_text, task)
    return task_level(project, task_brief.rigor_line(entry), task)


def file_levels(task_brief, project: Resolution, plan_text: str,
                store_dir: Path) -> dict[str, str]:
    """Each file a raised task's latest stage footprint lists, at the
    highest level among the tasks that list it. Staged tasks the plan
    doesn't hold take the project level."""
    levels: dict[str, str] = {}
    for task, entry in sorted(ledger.stage_map(ledger.load_progress_log(store_dir)).items()):
        try:
            level = _plan_task_level(task_brief, project, plan_text, str(task)).level
        except task_brief.UsageError:
            continue
        if level == project.level:
            continue
        for path in entry.get("files", []):
            if _rank(level) > _rank(levels.get(path, project.level)):
                levels[path] = level
    return levels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve the test rigor level.")
    parser.add_argument("--repo", default=".", help="a directory in the work tree (default: .)")
    parser.add_argument("--plan", help="plan file whose task Rigor: lines to apply")
    parser.add_argument("--task", help="with --plan: print this task's level")
    parser.add_argument("--store", help="with --plan --files: the run's ledger store")
    parser.add_argument("--files", action="store_true",
                        help="with --plan --store: print the files above the project level")
    return parser


def _run(args: argparse.Namespace, task_brief) -> list[str]:
    project = project_level(Path(args.repo))
    if args.plan is None:
        return [project.line()]
    plan_text = Path(args.plan).read_text(encoding="utf-8")
    if args.task is not None:
        return [_plan_task_level(task_brief, project, plan_text, args.task).line()]
    levels = file_levels(task_brief, project, plan_text, Path(args.store))
    return [project.line(), *(f"{levels[path]} {path}" for path in sorted(levels))]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    task_mode = args.task is not None and args.store is None and not args.files
    files_mode = args.task is None and args.store is not None and args.files
    if args.plan is None and (args.task is not None or args.store is not None or args.files):
        parser.error("--task, --store, and --files need --plan")
    if args.plan is not None and not (task_mode or files_mode):
        parser.error("--plan takes either --task N, or --store STORE --files")
    # Here, not at module level: task_brief imports this module.
    import task_brief
    try:
        lines = _run(args, task_brief)
    except (RigorError, OSError, UnicodeDecodeError, ledger.RecordError,
            task_brief.UsageError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
