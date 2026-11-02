"""Shared fixtures for ml-journal tests: scratch git repos with and without a journal."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PLUGIN_ROOT / "skills"
SCRIPTS_DIR = SKILLS_DIR / "log-init" / "scripts"
HOOKS_DIR = SKILLS_DIR / "log-init" / "hooks"
JOURNAL_LOG = SCRIPTS_DIR / "journal_log.py"
JOURNAL_QUERY = SCRIPTS_DIR / "journal_query.py"
JOURNAL_SETUP = SCRIPTS_DIR / "journal_setup.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def run_script(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a plugin script the way skills do: isolated interpreter, cwd inside the repo."""
    return subprocess.run(
        [sys.executable, "-I", str(script), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def journal_entries(repo: Path) -> list[dict]:
    lines = (repo / ".project-log" / "journal.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(autouse=True)
def _isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the user's global/system git config (signing, fsmonitor, renames) out of the tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def claude_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty Claude config dir, so `inspect` never reads the user's real settings."""
    config = tmp_path / "claude-config"
    config.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    return config


@pytest.fixture(autouse=True)
def trust_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The default trust store dir, moved into tmp via XDG_DATA_HOME so the user's real one never leaks in.

    CLAUDE_PLUGIN_DATA is removed: plugin and manual installs share one store, so nothing may depend on it.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    data = tmp_path / "xdg" / "ml-journal"
    data.mkdir(parents=True)
    return data


@pytest.fixture
def trust(trust_dir: Path) -> Callable[[Path], None]:
    """Trust a repo's journal on this machine, the way /log-init does (default store, no --data-dir)."""

    def _trust(repo: Path) -> None:
        result = run_script(JOURNAL_SETUP, repo, "trust")
        assert result.returncode == 0, result.stderr

    return _trust


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo on main with one commit and no journal."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    (root / "plain.txt").write_text("plain\n")
    (root / "tracked.txt").write_text("tracked\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def journal_repo(repo: Path) -> Path:
    """The repo initialized the current way: journal data only, no scripts."""
    log_dir = repo / ".project-log"
    log_dir.mkdir()
    (log_dir / "journal.jsonl").write_text("")
    return repo


@pytest.fixture
def write_checkpoint() -> Callable[[Path, str], None]:
    def _write(repo: Path, in_progress: str) -> None:
        result = run_script(JOURNAL_LOG, repo, "--type", "checkpoint", "--in-progress", in_progress)
        assert result.returncode == 0, result.stderr

    return _write


@pytest.fixture
def outside_file(tmp_path: Path) -> Path:
    """A file outside the repo that a hostile symlink points at (stands in for ~/.bashrc)."""
    target = tmp_path / "outside" / "victim-rc"
    target.parent.mkdir()
    target.write_text("# untouched\n")
    return target
