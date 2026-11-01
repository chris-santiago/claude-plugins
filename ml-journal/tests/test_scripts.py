# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for the plugin's journal scripts, the only journal code that runs.

Run with: uv run --with pytest pytest plugins/ml-journal/tests -v
"""

import importlib.util
import shutil
from pathlib import Path

import pytest
from conftest import JOURNAL_LOG, JOURNAL_QUERY, journal_entries, run_script


# --- Field validation (ported from ml-lab commit 782506d) --------------------


def test_log_rejects_field_not_valid_for_type(journal_repo: Path) -> None:
    result = run_script(
        JOURNAL_LOG, journal_repo,
        "--type", "issue", "--description", "x", "--severity", "high", "--verdict", "confirmed",
    )
    assert result.returncode != 0
    assert "not valid for type 'issue'" in result.stderr
    assert "verdict" in result.stderr
    assert journal_entries(journal_repo) == []


def test_log_accepts_valid_fields(journal_repo: Path) -> None:
    result = run_script(
        JOURNAL_LOG, journal_repo,
        "--type", "issue", "--description", "x", "--severity", "high", "--tags", "a,b",
    )
    assert result.returncode == 0, result.stderr
    (entry,) = journal_entries(journal_repo)
    assert entry["tags"] == ["a", "b"]


# --- Symlink refusal ---------------------------------------------------------


def _symlink_journal(repo: Path, target: Path) -> None:
    journal = repo / ".project-log" / "journal.jsonl"
    journal.unlink()
    journal.symlink_to(target)


def _symlink_log_dir(repo: Path, target: Path) -> Path:
    (target.parent / "journal.jsonl").write_text("")
    shutil.rmtree(repo / ".project-log")
    (repo / ".project-log").symlink_to(target.parent)
    return target.parent / "journal.jsonl"


@pytest.mark.parametrize("layout", ["journal", "log_dir"])
def test_log_refuses_symlinked_journal(journal_repo: Path, outside_file: Path, layout: str) -> None:
    if layout == "journal":
        _symlink_journal(journal_repo, outside_file)
        watched = outside_file
    else:
        watched = _symlink_log_dir(journal_repo, outside_file)
    before = watched.read_text()

    result = run_script(JOURNAL_LOG, journal_repo, "--type", "memo", "--description", "x")
    assert result.returncode != 0
    assert "Refusing to use symlinked" in result.stderr
    assert watched.read_text() == before


@pytest.mark.parametrize("layout", ["journal", "log_dir"])
def test_query_refuses_symlinked_journal(journal_repo: Path, outside_file: Path, layout: str) -> None:
    if layout == "journal":
        _symlink_journal(journal_repo, outside_file)
    else:
        _symlink_log_dir(journal_repo, outside_file)

    result = run_script(JOURNAL_QUERY, journal_repo, "--status")
    assert result.returncode != 0
    assert "Refusing to use symlinked" in result.stderr


def test_append_entry_does_not_follow_symlink(tmp_path: Path, outside_file: Path) -> None:
    """O_NOFOLLOW guards the write itself, independent of the path check before it."""
    spec = importlib.util.spec_from_file_location("journal_log_under_test", JOURNAL_LOG)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    link = tmp_path / "journal.jsonl"
    link.symlink_to(outside_file)
    with pytest.raises(OSError):
        module.append_entry(str(link), {"id": "x"})
    assert outside_file.read_text() == "# untouched\n"


# --- Legacy-layout notice (works without hooks) --------------------------------


_QUERY_AND_LOG = [
    (JOURNAL_QUERY, ("--status",)),
    (JOURNAL_LOG, ("--type", "memo", "--description", "x")),
]


@pytest.mark.parametrize(("script", "args"), _QUERY_AND_LOG, ids=["query", "log"])
def test_scripts_warn_legacy_repo_on_stderr(journal_repo: Path, script: Path, args: tuple[str, ...]) -> None:
    """Orgs that block hooks never see the SessionStart note, so every skill call carries it."""
    (journal_repo / ".project-log" / "journal_query.py").write_text("# old copy\n")
    result = run_script(script, journal_repo, *args)
    assert result.returncode == 0, result.stderr
    assert "legacy ml-journal layout" in result.stderr and "/log-init" in result.stderr
    assert "legacy" not in result.stdout, "the note goes to stderr so stdout stays parseable"


@pytest.mark.parametrize(("script", "args"), _QUERY_AND_LOG, ids=["query", "log"])
def test_scripts_quiet_in_current_repo(journal_repo: Path, script: Path, args: tuple[str, ...]) -> None:
    result = run_script(script, journal_repo, *args)
    assert result.returncode == 0, result.stderr
    assert "legacy" not in result.stderr


def test_query_missing_journal_points_at_log_init(repo: Path) -> None:
    result = run_script(JOURNAL_QUERY, repo, "--status")
    assert result.returncode != 0
    assert "/log-init" in result.stderr
