#!/usr/bin/env python3
"""
Tests for rigor.py (rigor-level spec §4.1-4.2, §6.2-6.3, §9).

Each test builds a throwaway git repo whose tracked files set the counted
source lines and the dependency markers.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = (Path(__file__).resolve().parents[1]
               / "skills" / "subagent-driven-development" / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import rigor  # noqa: E402

RIGOR_PY = SCRIPTS_DIR / "rigor.py"


def _lines(n: int) -> str:
    return "x = 1\n" * n


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def track(self) -> None:
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)

    def level(self) -> rigor.Resolution:
        self.track()
        return rigor.project_level(self.repo)

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        self.track()
        return subprocess.run([sys.executable, str(RIGOR_PY), "--repo", str(self.repo), *args],
                              capture_output=True, text=True)


class TestSizeBase(RepoTestCase):
    def test_thresholds(self):
        for lines, expected in [(4999, "light"), (5000, "standard"),
                                (30000, "standard"), (30001, "heavy")]:
            with self.subTest(lines=lines):
                self.write("src/app.py", _lines(lines))
                self.assertEqual(self.level().level, expected)

    def test_reason_names_the_count_and_languages(self):
        self.write("app/server.py", _lines(3000))
        self.write("web/main.ts", _lines(1000))
        result = self.level()
        self.assertEqual(result.level, "light")
        self.assertEqual(result.reasons, ("4,000 source lines (python, typescript)",))

    def test_blank_lines_and_untracked_files_are_not_counted(self):
        self.write("src/app.py", "x = 1\n\n   \n" * 5000)
        self.track()
        self.write("src/untracked.py", _lines(10000))
        self.assertEqual(rigor.project_level(self.repo).reasons,
                         ("5,000 source lines (python)",))

    def test_tests_vendored_generated_and_non_source_are_not_counted(self):
        self.write("src/app.py", _lines(1000))
        excluded = ["tests/test_app.py", "test/helpers.py", "pkg/test_util.py", "pkg/util_test.py",
                    "crate/src/lib_test.rs", "crate/src/tests.rs", "svc/handler_test.go",
                    "web/app.test.ts", "web/app.spec.js", "vendor/lib.py",
                    "third_party/x.c", "web/node_modules/dep/index.js", "build/out.py",
                    "dist/bundle.js", "crate/target/debug/gen.rs", "generated/api.py",
                    "proto/api_pb2.py", "README.md", "data/rows.json", "notes.txt"]
        for rel in excluded:
            self.write(rel, _lines(10000))
        self.assertEqual(self.level().reasons, ("1,000 source lines (python)",))


class TestMarkers(RepoTestCase):
    def test_binding_floors_a_small_project_at_standard(self):
        self.write("src/lib.rs", _lines(1000))
        self.write("Cargo.toml", '[package]\nname = "x"\n\n[dependencies]\npyo3 = { version = "0.21" }\n')
        result = self.level()
        self.assertEqual(result.level, "standard")
        self.assertIn("pyo3 binding: floor standard", result.reasons)

    def test_maturin_backend_is_a_binding(self):
        self.write("src/app.py", _lines(1000))
        self.write("pyproject.toml", '[build-system]\nrequires = ["maturin>=1.4"]\n'
                                     'build-backend = "maturin"\n')
        self.assertEqual(self.level().level, "standard")

    def test_numeric_dependency_raises_one_step(self):
        self.write("src/app.py", _lines(1000))
        self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["numpy>=1.26"]\n')
        result = self.level()
        self.assertEqual(result.level, "standard")
        self.assertIn("numpy +1", result.reasons)

    def test_binding_and_numeric_together_reach_heavy(self):
        self.write("src/lib.rs", _lines(1000))
        self.write("Cargo.toml", '[package]\nname = "x"\n\n[dependencies]\npyo3 = "0.21"\n')
        self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["numpy"]\n')
        self.assertEqual(self.level().level, "heavy")

    def test_raise_is_capped_at_heavy(self):
        self.write("src/app.py", _lines(40000))
        self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["numpy"]\n')
        result = self.level()
        self.assertEqual(result.level, "heavy")
        self.assertEqual(result.reasons, ("40,000 source lines (python)",))

    def test_a_name_containing_a_marker_is_not_the_marker(self):
        self.write("src/app.py", _lines(1000))
        self.write("pyproject.toml", '[project]\nname = "x"\n'
                                     'dependencies = ["numpy-utils", "torchvision-lite"]\n')
        self.write("Cargo.toml", '[package]\nname = "x"\n\n[dependencies]\npyo3-log = "0.9"\n')
        self.assertEqual(self.level().level, "light")

    def test_two_languages_without_a_binding_are_not_floored(self):
        self.write("api/app.py", _lines(1500))
        self.write("web/src/App.jsx", _lines(1500))
        self.write("web/package.json", '{"dependencies": {"react": "18"}}\n')
        self.assertEqual(self.level().level, "light")

    def test_numeric_markers_in_every_manifest_form(self):
        manifests = {
            "requirements-dev.txt": "# tools\n-r requirements.txt\npandas==2.2 ; python_version > '3.9'\n",
            "setup.cfg": "[options]\ninstall_requires =\n    requests\n    scipy>=1.11\n",
            "environment.yml": "name: env\ndependencies:\n  - python=3.12\n  - conda-forge::pytorch\n",
            "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.12"\npolars = "^1.0"\n',
            "rs/Cargo.toml": '[package]\nname = "x"\n\n[target.\'cfg(unix)\'.dependencies]\nndarray = "0.15"\n',
        }
        for rel, text in manifests.items():
            with self.subTest(manifest=rel):
                for other in manifests:
                    (self.repo / other).unlink(missing_ok=True)
                self.write("src/app.py", _lines(1000))
                self.write(rel, text)
                self.assertEqual(self.level().level, "standard")

    def test_markers_in_vendored_or_test_manifests_are_ignored(self):
        self.write("src/app.py", _lines(1000))
        self.write("vendor/dep/Cargo.toml", '[package]\nname = "d"\n\n[dependencies]\npyo3 = "0.21"\n')
        self.write("tests/fixtures/pyproject.toml", '[project]\nname = "f"\ndependencies = ["numpy"]\n')
        self.assertEqual(self.level().level, "light")

    def test_a_malformed_manifest_is_skipped(self):
        self.write("src/app.py", _lines(1000))
        self.write("Cargo.toml", "[dependencies\npyo3 = \n")
        self.assertEqual(self.level().level, "light")


class TestClaudeMd(RepoTestCase):
    def test_the_line_wins_over_the_heuristic(self):
        self.write("src/app.py", _lines(40000))
        self.write("CLAUDE.md", "# Project\n\nTest rigor: light\n")
        result = self.level()
        self.assertEqual((result.level, result.reasons), ("light", ("set in CLAUDE.md",)))

    def test_list_item_bold_label_and_any_case(self):
        self.write("src/app.py", _lines(1000))
        self.write("CLAUDE.md", "## Testing\n\n- **Test rigor:** Heavy\n")
        self.assertEqual(self.level().level, "heavy")

    def test_an_unknown_value_is_an_error_not_a_fallback(self):
        self.write("src/app.py", _lines(1000))
        self.write("CLAUDE.md", "Test rigor: medium\n")
        self.track()
        with self.assertRaises(rigor.RigorError) as caught:
            rigor.project_level(self.repo)
        for word in ("medium", "light", "standard", "heavy"):
            self.assertIn(word, str(caught.exception))

    def test_cli_exits_2_on_an_unknown_value(self):
        self.write("src/app.py", _lines(1000))
        self.write("CLAUDE.md", "Test rigor: medium\n")
        proc = self.cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("medium", proc.stderr)
        self.assertEqual(proc.stdout, "")


class TestDefaults(RepoTestCase):
    def test_not_a_git_work_tree(self):
        with tempfile.TemporaryDirectory() as plain:
            result = rigor.project_level(Path(plain))
        self.assertEqual(result.level, "standard")
        self.assertIn("not a git work tree", result.reasons[0])

    def test_no_tracked_source(self):
        self.write("README.md", "# docs only\n")
        result = self.level()
        self.assertEqual(result.level, "standard")
        self.assertIn("no tracked source", result.reasons[0])

    def test_a_subdirectory_resolves_its_work_tree(self):
        self.write("src/app.py", _lines(6000))
        self.track()
        self.assertEqual(rigor.project_level(self.repo / "src").level, "standard")


class TestProjectCli(RepoTestCase):
    def test_prints_level_and_reasons(self):
        self.write("src/app.py", _lines(1000))
        self.write("pyproject.toml", '[project]\nname = "x"\ndependencies = ["numpy"]\n')
        proc = self.cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "standard: 1,000 source lines (python); numpy +1\n")


if __name__ == "__main__":
    unittest.main()
