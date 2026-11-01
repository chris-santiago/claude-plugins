# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Tests for journal_setup.py: data-only init and upgrade from the legacy layout.

Run with: uv run --with pytest pytest plugins/ml-journal/tests -v
"""

import importlib.util
import json
from pathlib import Path

import pytest
from conftest import SCRIPTS_DIR, git, run_script

SETUP = SCRIPTS_DIR / "journal_setup.py"
TEMPLATE = SCRIPTS_DIR.parent / "assets" / "claude-md-sections.md"
LEGACY = ("journal_log.py", "journal_query.py")
HEADINGS = (
    "## Journal — Consultation Before Planning",
    "## Journal — Committing",
    "## Journal — Proactive Logging",
)

STALE_CONSULTATION = """## Journal — Consultation Before Planning

Before drafting any non-trivial plan, query the journal:
1. `python3 .project-log/journal_query.py --unresolved-issues` — surface active blockers
"""
UNMANAGED_REF = "Run `python3 .project-log/journal_query.py --status` by hand."


def _setup(repo: Path, *args: str):
    return run_script(SETUP, repo, *args)


def _inspect(repo: Path) -> dict:
    result = _setup(repo, "inspect")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _template_section(heading: str) -> str:
    text = TEMPLATE.read_text()
    start = text.index(heading)
    nxt = [text.index(h) for h in HEADINGS if h != heading and text.index(h) > start]
    return text[start : min(nxt)] if nxt else text[start:]


def _line_of(path: Path, needle: str) -> int:
    return next(n for n, line in enumerate(path.read_text().splitlines(), 1) if needle in line)


def _files(repo: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}


@pytest.fixture
def legacy_repo(journal_repo: Path) -> Path:
    log_dir = journal_repo / ".project-log"
    for name in LEGACY:
        (log_dir / name).write_text("# old copy\n")
    (log_dir / "journal.jsonl").write_text('{"id": "abc", "type": "memo"}\n')
    (journal_repo / "CLAUDE.md").write_text(
        "# Project\n\nIntro.\n\n" + STALE_CONSULTATION + f"\n## Other\n\n{UNMANAGED_REF}\n"
    )
    return journal_repo


# --- init -------------------------------------------------------------------


def test_init_creates_only_journal(repo: Path) -> None:
    result = _setup(repo, "init")
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (repo / ".project-log").iterdir()) == ["journal.jsonl"]


def test_init_never_truncates_existing_journal(journal_repo: Path) -> None:
    journal = journal_repo / ".project-log" / "journal.jsonl"
    journal.write_text('{"id": "keep"}\n')
    assert _setup(journal_repo, "init").returncode == 0
    assert journal.read_text() == '{"id": "keep"}\n'


def test_init_does_not_follow_symlink_even_past_path_check(
    repo: Path, outside_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O_NOFOLLOW in init guards the open itself, independent of journal_path()'s check."""
    spec = importlib.util.spec_from_file_location("journal_setup_under_test", SETUP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    log_dir = repo / ".project-log"
    log_dir.mkdir()
    link = log_dir / "journal.jsonl"
    link.symlink_to(outside_file)
    monkeypatch.setattr(module, "journal_path", lambda root: str(link))
    with pytest.raises(OSError):
        module.cmd_init(str(repo), None)
    assert outside_file.read_text() == "# untouched\n"


def test_init_refuses_symlinked_log_dir(repo: Path, outside_file: Path) -> None:
    (repo / ".project-log").symlink_to(outside_file.parent)
    result = _setup(repo, "init")
    assert result.returncode != 0
    assert "Refusing to use symlinked" in result.stderr
    assert not (outside_file.parent / "journal.jsonl").exists()


# --- inspect ----------------------------------------------------------------


def test_inspect_fresh_repo(repo: Path) -> None:
    report = _inspect(repo)
    assert report["journal_exists"] is False
    assert report["legacy_copies"] == []
    assert report["claude_md"]["exists"] is False


def test_inspect_legacy_repo(legacy_repo: Path) -> None:
    report = _inspect(legacy_repo)
    assert report["journal_exists"] is True
    assert sorted(report["legacy_copies"]) == sorted(LEGACY)
    md = report["claude_md"]
    assert md["stale_sections"] == [HEADINGS[0]]
    assert sorted(md["absent_sections"]) == sorted(HEADINGS[1:])
    (ref,) = md["unmanaged_refs"]
    assert ref["line"] == _line_of(legacy_repo / "CLAUDE.md", "--status")
    assert report["needs_upgrade"] is True


def test_inspect_recognizes_heading_with_trailing_spaces(journal_repo: Path) -> None:
    section = _template_section(HEADINGS[1]).replace(HEADINGS[1], HEADINGS[1] + "   ", 1)
    (journal_repo / "CLAUDE.md").write_text("# P\n\n" + section)
    assert HEADINGS[1] not in _inspect(journal_repo)["claude_md"]["absent_sections"]


def test_inspect_handles_mixed_fence_markers(journal_repo: Path) -> None:
    """A ``` line inside a ~~~ block does not close it; the real heading after it counts."""
    body = "# P\n\n~~~text\n```\n~~~\n\n" + STALE_CONSULTATION
    (journal_repo / "CLAUDE.md").write_text(body)
    assert _inspect(journal_repo)["claude_md"]["stale_sections"] == [HEADINGS[0]]


def test_inspect_requires_closing_fence_at_least_as_long(journal_repo: Path) -> None:
    """A ``` line does not close a ```` fence, so a heading after it is still fenced."""
    body = "# P\n\n````md\n```\n" + STALE_CONSULTATION + "````\n"
    (journal_repo / "CLAUDE.md").write_text(body)
    assert _inspect(journal_repo)["claude_md"]["stale_sections"] == []


def test_dry_run_diff_keeps_lines_apart_without_final_newline(journal_repo: Path) -> None:
    (journal_repo / "CLAUDE.md").write_text("# P\n\n" + STALE_CONSULTATION.rstrip("\n"))
    out = _setup(journal_repo, "upgrade", "--dry-run").stdout
    assert "surface active blockers\n" in out, "the last removed line ends with its own newline"
    assert "surface active blockers+" not in out


# --- upgrade ----------------------------------------------------------------


def test_upgrade_dry_run_changes_nothing_and_shows_diff(legacy_repo: Path) -> None:
    before = _files(legacy_repo)
    result = _setup(legacy_repo, "upgrade", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "journal_log.py" in result.stdout and HEADINGS[0] in result.stdout
    assert "-1. `python3 .project-log/journal_query.py --unresolved-issues`" in result.stdout, "diff shows removed line"
    assert "+1. `/log-list issue`" in result.stdout, "diff shows added line"
    assert _files(legacy_repo) == before


def test_upgrade_removes_copies_and_rewrites_stale_sections(legacy_repo: Path) -> None:
    journal = legacy_repo / ".project-log" / "journal.jsonl"
    journal_before = journal.read_bytes()

    result = _setup(legacy_repo, "upgrade")
    assert result.returncode == 0, result.stderr

    assert sorted(p.name for p in (legacy_repo / ".project-log").iterdir()) == ["journal.jsonl"]
    assert journal.read_bytes() == journal_before, "upgrade must not touch journal data"

    claude_md = (legacy_repo / "CLAUDE.md").read_text()
    expected = "# Project\n\nIntro.\n\n" + _template_section(HEADINGS[0]).rstrip() + f"\n\n## Other\n\n{UNMANAGED_REF}\n"
    assert claude_md == expected, "only the stale section changes, with one blank line before the next heading"
    assert f"line {_line_of(legacy_repo / 'CLAUDE.md', '--status')}" in result.stdout, "unmanaged reference is reported"


def test_upgrade_leaves_customized_sections_alone(journal_repo: Path) -> None:
    """A managed section that differs from the template but runs no legacy script is the user's."""
    custom = _template_section(HEADINGS[1]).rstrip() + "\n\n### Team notes\n\nAlways run make lint first!\n"
    (journal_repo / "CLAUDE.md").write_text("# P\n\n" + custom)
    report = _inspect(journal_repo)
    assert report["claude_md"]["customized_sections"] == [HEADINGS[1]]
    assert report["needs_upgrade"] is False

    before = (journal_repo / "CLAUDE.md").read_text()
    result = _setup(journal_repo, "upgrade")
    assert result.returncode == 0, result.stderr
    assert (journal_repo / "CLAUDE.md").read_text() == before


def test_upgrade_rewrites_adjacent_and_duplicate_stale_sections(journal_repo: Path) -> None:
    stale_commit = HEADINGS[1] + "\n\nLog with `python3 .project-log/journal_log.py`.\n"
    (journal_repo / "CLAUDE.md").write_text(
        "# P\n\n" + STALE_CONSULTATION + "\n" + stale_commit + "\n" + STALE_CONSULTATION
    )
    assert _setup(journal_repo, "upgrade").returncode == 0
    text = (journal_repo / "CLAUDE.md").read_text()
    assert ".project-log/journal_" not in text
    assert text.count(HEADINGS[0]) == 2
    assert _inspect(journal_repo)["needs_upgrade"] is False


def test_upgrade_preserves_crlf_line_endings(journal_repo: Path) -> None:
    path = journal_repo / "CLAUDE.md"
    path.write_bytes(("# P\r\n\r\n" + STALE_CONSULTATION.replace("\n", "\r\n") + "\r\n## Other\r\n\r\nkeep\r\n").encode())
    assert _setup(journal_repo, "upgrade").returncode == 0
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "every line keeps CRLF"
    assert b"## Other\r\n\r\nkeep\r\n" in raw


def test_upgrade_is_idempotent(legacy_repo: Path) -> None:
    assert _setup(legacy_repo, "upgrade").returncode == 0
    snapshot = (legacy_repo / "CLAUDE.md").read_text()
    second = _setup(legacy_repo, "upgrade")
    assert second.returncode == 0
    assert (legacy_repo / "CLAUDE.md").read_text() == snapshot
    assert _inspect(legacy_repo)["needs_upgrade"] is False


def test_upgrade_already_current_message(journal_repo: Path) -> None:
    result = _setup(journal_repo, "upgrade")
    assert result.returncode == 0
    assert "Already current" in result.stdout


def test_upgrade_with_only_unmanaged_refs_changes_nothing(journal_repo: Path) -> None:
    (journal_repo / "CLAUDE.md").write_text(f"# P\n\n{UNMANAGED_REF}\n")
    before = _files(journal_repo)
    result = _setup(journal_repo, "upgrade")
    assert result.returncode == 0
    assert "Nothing to change" in result.stdout and "line 3" in result.stdout
    assert _files(journal_repo) == before


def test_upgrade_rewrites_section_at_eof(journal_repo: Path) -> None:
    (journal_repo / "CLAUDE.md").write_text("# P\n\n" + STALE_CONSULTATION)
    assert _setup(journal_repo, "upgrade").returncode == 0
    text = (journal_repo / "CLAUDE.md").read_text()
    assert text == "# P\n\n" + _template_section(HEADINGS[0]).rstrip() + "\n"


def test_upgrade_ignores_headings_inside_code_fences(journal_repo: Path) -> None:
    fenced = "# P\n\n```markdown\n" + STALE_CONSULTATION + "```\n"
    (journal_repo / "CLAUDE.md").write_text(fenced)
    assert _inspect(journal_repo)["claude_md"]["stale_sections"] == []
    assert _setup(journal_repo, "upgrade").returncode == 0
    assert (journal_repo / "CLAUDE.md").read_text() == fenced


@pytest.mark.parametrize("target", ["outside", "git_config", "git_config_case", "journal", "dangling"])
def test_upgrade_skips_symlinked_claude_md(legacy_repo: Path, outside_file: Path, target: str) -> None:
    """A symlinked CLAUDE.md is never read or written, wherever it points; copies still go."""
    victim = {
        "outside": outside_file,
        "git_config": legacy_repo / ".git" / "config",
        "git_config_case": legacy_repo / ".GIT" / "config",  # same file on case-insensitive filesystems
        "journal": legacy_repo / ".project-log" / "journal.jsonl",
        "dangling": legacy_repo / "missing.md",
    }[target]
    victim_before = victim.read_bytes() if victim.exists() else None
    (legacy_repo / "CLAUDE.md").unlink()
    (legacy_repo / "CLAUDE.md").symlink_to(victim)

    assert _inspect(legacy_repo)["claude_md"]["symlinked"] is True
    result = _setup(legacy_repo, "upgrade")
    assert result.returncode == 0, result.stderr
    assert "symlink" in result.stdout
    assert sorted(p.name for p in (legacy_repo / ".project-log").iterdir()) == ["journal.jsonl"]
    added = _setup(legacy_repo, "add-sections")
    assert added.returncode == 0 and "skip CLAUDE.md" in added.stdout
    if victim_before is not None:
        assert victim.read_bytes() == victim_before
    else:
        assert not victim.exists()


def test_upgrade_keeps_customized_section_while_rewriting_stale_one(legacy_repo: Path) -> None:
    """The old bug: rewriting every section that differs from the template deleted user content."""
    custom = _template_section(HEADINGS[1]).rstrip() + "\n\n### Team notes\n\nKEEP-ME: run make lint first.\n"
    path = legacy_repo / "CLAUDE.md"
    path.write_text(path.read_text() + "\n" + custom)

    assert _setup(legacy_repo, "upgrade").returncode == 0
    text = path.read_text()
    assert "KEEP-ME: run make lint first." in text and "### Team notes" in text
    assert _template_section(HEADINGS[0]).strip() in text, "the stale section was still rewritten"


# --- add-sections -----------------------------------------------------------


def test_add_sections_appends_only_absent(journal_repo: Path) -> None:
    present = _template_section(HEADINGS[1])
    (journal_repo / "CLAUDE.md").write_text("# P\n\n" + present)
    assert _setup(journal_repo, "add-sections").returncode == 0
    text = (journal_repo / "CLAUDE.md").read_text()
    for heading in HEADINGS:
        assert text.count(heading) == 1
    expected_tail = "\n\n".join(_template_section(h).rstrip() for h in (HEADINGS[0], HEADINGS[2])) + "\n"
    assert text == "# P\n\n" + present.rstrip() + "\n\n" + expected_tail, "sections separated by one blank line"


def test_template_references_skills_not_scripts() -> None:
    text = TEMPLATE.read_text()
    assert ".project-log/journal_" not in text
    for heading in HEADINGS:
        assert heading in text


# --- Trust list --------------------------------------------------------------


def _store(data_dir: Path) -> dict:
    return json.loads((data_dir / "trusted-repos.json").read_text())


def _is_trusted(repo: Path, data_dir: Path) -> bool:
    return _inspect_with(repo, data_dir)["trusted"]


def _inspect_with(repo: Path, data_dir: Path) -> dict:
    result = _setup(repo, "--data-dir", str(data_dir), "inspect")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_init_new_journal_trusts_repo(repo: Path, plugin_data: Path) -> None:
    result = _setup(repo, "--data-dir", str(plugin_data), "init")
    assert result.returncode == 0, result.stderr
    assert "trusted" in result.stdout
    assert _is_trusted(repo, plugin_data)
    (entry,) = _store(plugin_data)["repos"].values()
    assert entry["worktree"] == str(repo.resolve()) or entry["worktree"] == str(repo)
    assert entry["trusted_at"]


def test_init_existing_journal_does_not_trust(journal_repo: Path, plugin_data: Path) -> None:
    result = _setup(journal_repo, "--data-dir", str(plugin_data), "init")
    assert result.returncode == 0, result.stderr
    assert not (plugin_data / "trusted-repos.json").exists()
    assert not _is_trusted(journal_repo, plugin_data)


def test_init_does_not_auto_trust_when_history_has_a_journal(repo: Path, plugin_data: Path) -> None:
    """A journal on another branch would arrive with a checkout, so trust must be asked for, not implied."""
    git(repo, "switch", "-q", "-c", "other")
    (repo / ".project-log").mkdir()
    (repo / ".project-log" / "journal.jsonl").write_text("{}\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "journal on another branch")
    git(repo, "switch", "-q", "main")
    assert not (repo / ".project-log").exists()
    result = _setup(repo, "--data-dir", str(plugin_data), "init")
    assert result.returncode == 0, result.stderr
    assert "created" in result.stdout and "not trusted" in result.stdout
    assert not _is_trusted(repo, plugin_data)


def test_trust_refuses_borrowed_git_dir(journal_repo: Path, plugin_data: Path, tmp_path: Path) -> None:
    """Trusting a tree whose .git file points at another repo's git dir would record that repo's key."""
    hostile = tmp_path / "hostile"
    (hostile / ".project-log").mkdir(parents=True)
    (hostile / ".project-log" / "journal.jsonl").write_text("")
    (hostile / ".git").write_text(f"gitdir: {journal_repo / '.git'}\n")
    result = _setup(hostile, "--data-dir", str(plugin_data), "trust")
    assert result.returncode != 0
    assert "not a registered worktree" in result.stderr
    assert not (plugin_data / "trusted-repos.json").exists()


def test_init_without_data_dir_creates_but_does_not_trust(repo: Path) -> None:
    result = _setup(repo, "init")
    assert result.returncode == 0, result.stderr
    assert (repo / ".project-log" / "journal.jsonl").exists()
    assert "auto-load" in result.stdout and "plugin data directory" in result.stdout


def test_trust_subcommand_new_then_already(journal_repo: Path, plugin_data: Path) -> None:
    first = _setup(journal_repo, "--data-dir", str(plugin_data), "trust")
    assert first.returncode == 0 and first.stdout.startswith("trusted")
    second = _setup(journal_repo, "trust", "--data-dir", str(plugin_data))
    assert second.returncode == 0 and second.stdout.startswith("already trusted")
    assert len(_store(plugin_data)["repos"]) == 1


def test_trust_requires_journal(repo: Path, plugin_data: Path) -> None:
    result = _setup(repo, "--data-dir", str(plugin_data), "trust")
    assert result.returncode != 0 and "/log-init" in result.stderr
    assert not (plugin_data / "trusted-repos.json").exists()


@pytest.mark.parametrize("data_dir", [[], ["--data-dir", ""]])
def test_trust_requires_data_dir(journal_repo: Path, data_dir: list[str]) -> None:
    result = _setup(journal_repo, *data_dir, "trust")
    assert result.returncode != 0 and "no plugin data directory" in result.stderr


def test_trust_refuses_symlinked_journal(journal_repo: Path, outside_file: Path, plugin_data: Path) -> None:
    journal = journal_repo / ".project-log" / "journal.jsonl"
    journal.unlink()
    journal.symlink_to(outside_file)
    result = _setup(journal_repo, "--data-dir", str(plugin_data), "trust")
    assert result.returncode != 0 and "symlink" in result.stderr
    assert not (plugin_data / "trusted-repos.json").exists()


def test_trust_creates_missing_data_dir(journal_repo: Path, tmp_path: Path) -> None:
    data = tmp_path / "fresh" / "data"
    assert _setup(journal_repo, "--data-dir", str(data), "trust").returncode == 0
    assert (data / "trusted-repos.json").exists()


def test_inspect_reports_trusted(journal_repo: Path, plugin_data: Path) -> None:
    assert _inspect_with(journal_repo, plugin_data)["trusted"] is False
    _setup(journal_repo, "--data-dir", str(plugin_data), "trust")
    assert _inspect_with(journal_repo, plugin_data)["trusted"] is True
    assert _inspect(journal_repo)["trusted"] is False, "no --data-dir means no trust"
