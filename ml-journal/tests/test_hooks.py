# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Regression tests for the ml-journal hook scripts and their plugin packaging.

Run with: uv run --with pytest pytest plugins/ml-journal/tests -v

Covers:
  1. SessionStart emits hookSpecificOutput.additionalContext with real newlines.
  2. PreCompact records changed paths whole (new name for renames, spaces intact).
  3. hooks/hooks.json registers both hooks via ${CLAUDE_PLUGIN_ROOT}.
  4. The hooks fire in every repo, so they never execute code from the working
     tree and never write through a symlinked journal.
  5. Repos still on the legacy layout (scripts copied into .project-log/) are
     told to upgrade.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import PLUGIN_ROOT, git, journal_entries

_HOOKS_DIR = PLUGIN_ROOT / "hooks"
_SESSION_START = _HOOKS_DIR / "journal-session-start.sh"
_PRECOMPACT = _HOOKS_DIR / "journal-precompact.sh"
_LEGACY_SCRIPTS = ("journal_log.py", "journal_query.py")

WriteCheckpoint = Callable[[Path, str], None]


def _run_hook(
    script: Path, cwd: Path, stdin: str = "{}", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)], cwd=cwd, input=stdin, capture_output=True, text=True, check=False, env=env
    )


def _context(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "additionalContext" not in payload, "top-level additionalContext is not in the hook schema"
    specific = payload["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    return specific["additionalContext"]


def _modified_paths(git_state: str) -> list[str]:
    _, _, modified = git_state.partition("modified: ")
    return modified.split(",") if modified else []


@pytest.fixture
def legacy_repo(journal_repo: Path) -> Path:
    """A journal repo set up the old way, with script copies in .project-log/.

    The copies are hostile: each drops a sentinel file if executed.
    """
    for name in _LEGACY_SCRIPTS:
        sentinel = journal_repo / f"PWNED-{name}"
        (journal_repo / ".project-log" / name).write_text(f"open({str(sentinel)!r}, 'w').write('ran')\n")
    return journal_repo


def _assert_nothing_ran(repo: Path) -> None:
    assert not list(repo.glob("PWNED-*")), "hook executed a repo-local script"


# --- SessionStart -----------------------------------------------------------


def test_session_start_silent_without_journal(repo: Path) -> None:
    result = _run_hook(_SESSION_START, repo)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_session_start_silent_without_checkpoint(journal_repo: Path) -> None:
    result = _run_hook(_SESSION_START, journal_repo)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_session_start_injects_checkpoint(journal_repo: Path, write_checkpoint: WriteCheckpoint) -> None:
    write_checkpoint(journal_repo, "MARKER-wiring the encoder")
    context = _context(_run_hook(_SESSION_START, journal_repo))
    assert "MARKER-wiring the encoder" in context
    assert "legacy" not in context.lower()


def test_session_start_context_has_real_newlines(journal_repo: Path, write_checkpoint: WriteCheckpoint) -> None:
    write_checkpoint(journal_repo, "MARKER")
    context = _context(_run_hook(_SESSION_START, journal_repo))
    assert "\\n" not in context, "literal backslash-n leaked into the context"
    assert "\n\n" in context


def test_session_start_keeps_checkpoint_mentioning_sentinel_phrase(
    journal_repo: Path, write_checkpoint: WriteCheckpoint
) -> None:
    write_checkpoint(journal_repo, "No checkpoint found in the old cache, rebuilding")
    assert "rebuilding" in _context(_run_hook(_SESSION_START, journal_repo))


def test_session_start_silent_without_jq(
    journal_repo: Path, tmp_path: Path, write_checkpoint: WriteCheckpoint
) -> None:
    """jq is optional: without it the hook must exit quietly, not error in every journaled repo."""
    write_checkpoint(journal_repo, "MARKER")
    shim = tmp_path / "bin-no-jq"
    shim.mkdir()
    for tool in ("bash", "git", "python3", "dirname"):
        found = shutil.which(tool)
        assert found, f"{tool} not on PATH"
        (shim / tool).symlink_to(found)
    result = _run_hook(_SESSION_START, journal_repo, env={**os.environ, "PATH": str(shim)})
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


# --- Legacy layout ----------------------------------------------------------


def test_session_start_tells_legacy_repo_to_upgrade(legacy_repo: Path, write_checkpoint: WriteCheckpoint) -> None:
    write_checkpoint(legacy_repo, "MARKER-legacy")
    context = _context(_run_hook(_SESSION_START, legacy_repo))
    assert "/log-init" in context and "legacy" in context.lower()
    assert "MARKER-legacy" in context, "checkpoint must come from the plugin script, not the repo copy"
    _assert_nothing_ran(legacy_repo)


def test_session_start_upgrade_notice_without_checkpoint(legacy_repo: Path) -> None:
    context = _context(_run_hook(_SESSION_START, legacy_repo))
    assert "/log-init" in context
    _assert_nothing_ran(legacy_repo)


def test_precompact_never_runs_legacy_copies(legacy_repo: Path) -> None:
    result = _run_hook(_PRECOMPACT, legacy_repo, json.dumps({"trigger": "auto"}))
    assert result.returncode == 0, result.stderr
    _assert_nothing_ran(legacy_repo)
    assert journal_entries(legacy_repo)[-1]["in_progress"].startswith("Auto-captured at PreCompact")


# --- PreCompact -------------------------------------------------------------


def test_precompact_records_whole_paths(journal_repo: Path) -> None:
    git(journal_repo, "mv", "plain.txt", "renamed.txt")
    (journal_repo / "a with space.txt").write_text("x\n")
    (journal_repo / "tracked.txt").write_text("changed\n")

    stdin = json.dumps({"trigger": "manual", "custom_instructions": "keep it short"})
    result = _run_hook(_PRECOMPACT, journal_repo, stdin)
    assert result.returncode == 0, result.stderr

    checkpoint = journal_entries(journal_repo)[-1]
    assert checkpoint["type"] == "checkpoint"
    assert "trigger: manual" in checkpoint["in_progress"]
    assert "keep it short" in checkpoint["in_progress"]

    paths = _modified_paths(checkpoint["git_state"])
    assert "renamed.txt" in paths, "a rename must record the new name"
    assert "plain.txt" not in paths, "a rename must not record the old name"
    assert "a with space.txt" in paths, "paths with spaces must come through whole and unquoted"
    assert "tracked.txt" in paths


def test_precompact_records_worktree_rename(journal_repo: Path) -> None:
    """An unstaged rename (intent-to-add) puts R in the Y column, not X."""
    (journal_repo / "plain.txt").rename(journal_repo / "ren.txt")
    git(journal_repo, "add", "-N", "ren.txt")
    _run_hook(_PRECOMPACT, journal_repo)
    paths = _modified_paths(journal_entries(journal_repo)[-1]["git_state"])
    assert "ren.txt" in paths
    assert "plain.txt" not in paths


def test_precompact_names_detached_head(journal_repo: Path) -> None:
    git(journal_repo, "checkout", "-q", "--detach")
    _run_hook(_PRECOMPACT, journal_repo)
    git_state = journal_entries(journal_repo)[-1]["git_state"]
    assert git_state.startswith("branch: detached@"), git_state


@pytest.mark.parametrize("stdin", ["", "not json", "{}"])
def test_precompact_defaults_trigger_to_auto(journal_repo: Path, stdin: str) -> None:
    result = _run_hook(_PRECOMPACT, journal_repo, stdin)
    assert result.returncode == 0, result.stderr
    assert "(trigger: auto)" in journal_entries(journal_repo)[-1]["in_progress"]


def test_precompact_noop_without_journal(repo: Path) -> None:
    result = _run_hook(_PRECOMPACT, repo, json.dumps({"trigger": "auto"}))
    assert result.returncode == 0
    assert not (repo / ".project-log").exists()


# --- Untrusted working tree -------------------------------------------------


_OUTSIDE_CHECKPOINT = json.dumps({
    "id": "0" * 36, "timestamp": "2026-11-01T00:00:00+00:00", "type": "checkpoint",
    "project": "elsewhere", "session_id": "1", "in_progress": "OUTSIDE-MARKER",
}) + "\n"


@pytest.mark.parametrize("layout", ["journal", "log_dir"])
def test_session_start_never_reads_through_symlink(journal_repo: Path, tmp_path: Path, layout: str) -> None:
    """A symlinked journal pointing at a real checkpoint elsewhere must not be injected."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "journal.jsonl").write_text(_OUTSIDE_CHECKPOINT)
    if layout == "journal":
        (journal_repo / ".project-log" / "journal.jsonl").unlink()
        (journal_repo / ".project-log" / "journal.jsonl").symlink_to(elsewhere / "journal.jsonl")
    else:
        shutil.rmtree(journal_repo / ".project-log")
        (journal_repo / ".project-log").symlink_to(elsewhere)

    result = _run_hook(_SESSION_START, journal_repo)
    assert result.returncode == 0
    assert "OUTSIDE-MARKER" not in result.stdout


def test_hooks_refuse_symlinked_journal(journal_repo: Path, outside_file: Path) -> None:
    journal = journal_repo / ".project-log" / "journal.jsonl"
    journal.unlink()
    journal.symlink_to(outside_file)

    assert _run_hook(_PRECOMPACT, journal_repo).returncode == 0
    assert outside_file.read_text() == "# untouched\n", "PreCompact wrote through a symlinked journal"
    result = _run_hook(_SESSION_START, journal_repo)
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_refuse_symlinked_log_dir(journal_repo: Path, outside_file: Path) -> None:
    (outside_file.parent / "journal.jsonl").write_text("")
    shutil.rmtree(journal_repo / ".project-log")
    (journal_repo / ".project-log").symlink_to(outside_file.parent)

    assert _run_hook(_PRECOMPACT, journal_repo).returncode == 0
    assert (outside_file.parent / "journal.jsonl").read_text() == "", "PreCompact wrote through a symlinked .project-log"
    result = _run_hook(_SESSION_START, journal_repo)
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize("hook", [_SESSION_START, _PRECOMPACT], ids=["session_start", "precompact"])
def test_hooks_ignore_pythonpath(
    journal_repo: Path, tmp_path: Path, write_checkpoint: WriteCheckpoint, hook: Path
) -> None:
    """Scripts run under `python3 -I`, so a PYTHONPATH module cannot shadow the stdlib."""
    write_checkpoint(journal_repo, "MARKER")
    evil = tmp_path / "evil"
    evil.mkdir()
    sentinel = tmp_path / "PWNED-pythonpath"
    (evil / "json.py").write_text(f"open({str(sentinel)!r}, 'w').write('ran')\n")
    _run_hook(hook, journal_repo, env={**os.environ, "PYTHONPATH": str(evil)})
    assert not sentinel.exists(), "a PYTHONPATH module was imported by a journal script"


def test_precompact_ignores_repo_fsmonitor(journal_repo: Path) -> None:
    """A repo-local core.fsmonitor names a command git would run during `git status`."""
    sentinel = journal_repo / "PWNED-fsmonitor"
    monitor = journal_repo / ".git" / "evil-monitor"
    monitor.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
    monitor.chmod(0o755)
    git(journal_repo, "config", "core.fsmonitor", str(monitor))

    _run_hook(_PRECOMPACT, journal_repo)
    assert not sentinel.exists(), "git status ran the repo's fsmonitor command"


# --- Plugin packaging -------------------------------------------------------


def test_hooks_json_registers_both_hooks_in_nested_shape() -> None:
    config = json.loads((_HOOKS_DIR / "hooks.json").read_text())
    events = config["hooks"]
    expected = {"PreCompact": _PRECOMPACT, "SessionStart": _SESSION_START}
    assert set(events) == set(expected)

    for event, script in expected.items():
        (group,) = events[event]
        (handler,) = group["hooks"]
        assert handler["type"] == "command"
        command = handler["command"]
        assert '"${CLAUDE_PLUGIN_ROOT}"' in command, "plugin root must be quoted for paths with spaces"
        resolved = command.replace('"${CLAUDE_PLUGIN_ROOT}"', str(PLUGIN_ROOT))
        assert Path(resolved) == script
        assert os.access(script, os.X_OK), f"{script.name} must be executable"
