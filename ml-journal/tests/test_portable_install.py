# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""ml-journal works the same installed as a plugin or copied as plain skills.

Some organizations block plugin installs but allow skills in ~/.claude/skills/.
There, Claude Code substitutes ${CLAUDE_SKILL_DIR} but not ${CLAUDE_PLUGIN_ROOT}
or ${CLAUDE_PLUGIN_DATA}, and registers no hooks. So:
  1. Nothing under skills/ may use a plugin-only variable.
  2. Every script path a skill runs resolves from its own directory.
  3. A copied or symlinked skills tree runs its hooks with no plugin env.
  4. `journal_setup.py hook-config` prints settings that run those hooks.
  5. The trust store is one per-user path, chosen without plugin env.

Run with: uv run --with pytest pytest plugins/ml-journal/tests -v
"""

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import JOURNAL_SETUP, PLUGIN_ROOT, SCRIPTS_DIR, SKILLS_DIR, git, run_script

PLUGIN_ONLY = re.compile(r"CLAUDE_PLUGIN_(ROOT|DATA)")
# The one allowed use: /log-init passes the plugin root as data, so `inspect` can tell
# a plugin install (substituted) from a skills-only one (not substituted). Never a path.
PLUGIN_ROOT_PROBE = '--plugin-root "${CLAUDE_PLUGIN_ROOT}"'
SKILL_DIR_PATH = re.compile(r"\$\{CLAUDE_SKILL_DIR\}(/[^\"'\s]+)")
SCRIPT_CALL = re.compile(r"python3 -I \"([^\"]+)\"")


def _skill_files() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_skills_tree_uses_no_plugin_only_variables() -> None:
    hits = [
        f"{path.relative_to(PLUGIN_ROOT)}:{n}: {line.strip()}"
        for path in _skill_files()
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if PLUGIN_ONLY.search(line.replace(PLUGIN_ROOT_PROBE, ""))
    ]
    assert not hits, "plugin-only variables break manual installs:\n" + "\n".join(hits)


def test_every_skill_script_call_resolves_from_its_own_dir() -> None:
    calls = 0
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = skill_md.read_text()
        for script in SCRIPT_CALL.findall(text):
            assert script.startswith("${CLAUDE_SKILL_DIR}/"), f"{skill_md.parent.name}: {script}"
        for rel in SKILL_DIR_PATH.findall(text):
            calls += 1
            target = (skill_md.parent / rel.lstrip("/")).resolve()
            assert target.is_file(), f"{skill_md.parent.name}: ${{CLAUDE_SKILL_DIR}}{rel} does not exist"
    assert calls >= 10, "positive control: the skills run journal scripts via ${CLAUDE_SKILL_DIR}"


# --- Manual install: the skills tree copied or symlinked into ~/.claude/skills ---


def _copy_install(dest: Path) -> None:
    shutil.copytree(SKILLS_DIR, dest, ignore=shutil.ignore_patterns("__pycache__"))


def _symlink_install(dest: Path) -> None:
    dest.mkdir(parents=True)
    for skill in SKILLS_DIR.iterdir():
        if skill.is_dir():
            (dest / skill.name).symlink_to(skill, target_is_directory=True)


@pytest.fixture(params=[_copy_install, _symlink_install], ids=["copy", "symlink"])
def manual_skills(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A skills dir as a manual installer leaves it; the path has a space, as home dirs can."""
    dest = tmp_path / "home dir" / ".claude" / "skills"
    install: Callable[[Path], None] = request.param
    install(dest)
    return dest


def _no_plugin_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_")}


def _run(cmd: list[str], cwd: Path, stdin: str = "{}") -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, check=False, env=_no_plugin_env())


def _hook_config(skills: Path, cwd: Path) -> dict:
    result = _run([sys.executable, "-I", str(skills / "log-init" / "scripts" / "journal_setup.py"), "hook-config"], cwd)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _hook_command(config: dict, event: str) -> str:
    (group,) = config["hooks"][event]
    (handler,) = group["hooks"]
    assert handler["type"] == "command"
    return handler["command"]


def test_hook_config_matches_plugin_hooks_json(tmp_path: Path) -> None:
    """Both registrations name the same events and scripts; only the root differs."""
    plugin = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    printed = _hook_config(SKILLS_DIR, tmp_path)
    assert set(printed["hooks"]) == set(plugin["hooks"])
    for event in plugin["hooks"]:
        plugin_script = _hook_command(plugin, event).rsplit("/", 1)[-1]
        printed_script = _hook_command(printed, event).rsplit("/", 1)[-1].strip("'\"")
        assert printed_script == plugin_script


def test_hook_config_runs_outside_a_git_repo(tmp_path: Path) -> None:
    assert "SessionStart" in _hook_config(SKILLS_DIR, tmp_path)["hooks"]


def test_manual_install_session_start_loads_trusted_checkpoint(manual_skills: Path, journal_repo: Path) -> None:
    scripts = manual_skills / "log-init" / "scripts"
    assert _run([sys.executable, "-I", str(scripts / "journal_setup.py"), "trust"], journal_repo).returncode == 0
    logged = _run(
        [sys.executable, "-I", str(scripts / "journal_log.py"), "--type", "checkpoint", "--in-progress", "MARKER-manual"],
        journal_repo,
    )
    assert logged.returncode == 0, logged.stderr

    command = _hook_command(_hook_config(manual_skills, journal_repo), "SessionStart")
    result = _run(["bash", "-c", command], journal_repo)
    assert result.returncode == 0, result.stderr
    assert "MARKER-manual" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def test_manual_install_precompact_writes_checkpoint(manual_skills: Path, journal_repo: Path) -> None:
    git(journal_repo, "switch", "-q", "-c", "feature")
    command = _hook_command(_hook_config(manual_skills, journal_repo), "PreCompact")
    result = _run(["bash", "-c", command], journal_repo, stdin='{"trigger": "manual"}')
    assert result.returncode == 0, result.stderr
    lines = (journal_repo / ".project-log" / "journal.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["type"] == "checkpoint"


# --- Trust store location -------------------------------------------------------


@pytest.fixture
def journal_common(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPTS_DIR))
    return importlib.import_module("journal_common")


def test_default_store_honors_absolute_xdg_data_home(journal_common, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-abs"))
    assert journal_common.default_data_dir() == str(tmp_path / "xdg-abs" / "ml-journal")


@pytest.mark.parametrize("xdg", [None, "", "relative/share"])
def test_default_store_falls_back_to_local_share(
    journal_common, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg: str | None
) -> None:
    """XDG_DATA_HOME must be absolute to count (XDG spec); otherwise ~/.local/share."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    if xdg is None:
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", xdg)
    assert journal_common.default_data_dir() == str(tmp_path / "home" / ".local" / "share" / "ml-journal")


# --- Hook registration report (inspect) -----------------------------------------


def _hooks_report(repo: Path, *args: str) -> dict:
    result = run_script(JOURNAL_SETUP, repo, "inspect", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hooks"]


def test_log_init_probes_plugin_root() -> None:
    assert PLUGIN_ROOT_PROBE in (SKILLS_DIR / "log-init" / "SKILL.md").read_text()


@pytest.mark.parametrize(("args", "plugin"), [([], False), (["--plugin-root", ""], False), (["--plugin-root", "/x/ml-journal"], True)])
def test_inspect_reports_plugin_install(journal_repo: Path, args: list[str], plugin: bool) -> None:
    assert _hooks_report(journal_repo, *args) == {"plugin": plugin, "settings": []}


@pytest.mark.parametrize("where", ["user", "user-local", "project", "project-local"])
def test_inspect_finds_hooks_registered_in_settings(
    journal_repo: Path, claude_config: Path, manual_skills: Path, where: str
) -> None:
    files = {
        "user": claude_config / "settings.json",
        "user-local": claude_config / "settings.local.json",
        "project": journal_repo / ".claude" / "settings.json",
        "project-local": journal_repo / ".claude" / "settings.local.json",
    }
    target = files[where]
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(_hook_config(manual_skills, journal_repo)))
    assert _hooks_report(journal_repo)["settings"] == [str(target)]
