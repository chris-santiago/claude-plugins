# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""Relapse guard: nothing in the plugin may point at journal scripts inside a repo.

The plugin's own scripts are the only journal code that runs. The legacy layout
copied them into .project-log/ and every skill called those copies, which let a
repo supply the code and let the copies drift. A new skill, doc, or hook that
references `.project-log/journal_*.py` would reintroduce that, so fail on it.

Run with: uv run --with pytest pytest plugins/ml-journal/tests -v
"""

import re
from pathlib import Path

from conftest import PLUGIN_ROOT

LEGACY_REF = re.compile(r"\.project-log/journal_\w+\.py")
_SKIP_DIRS = {"tests", "__pycache__"}


def find_offenders(root: Path) -> list[str]:
    """Every line under `root` (outside tests/) that references a repo-local journal script."""
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += [
            f"{path.relative_to(root)}:{n}: {line.strip()}"
            for n, line in enumerate(text.splitlines(), 1)
            if LEGACY_REF.search(line)
        ]
    return hits


def test_scan_catches_planted_references(tmp_path: Path) -> None:
    """Positive control: the scan flags both legacy call forms in a planted skill file."""
    skill = tmp_path / "skills" / "planted" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "ok line\n"
        "python3 <repo-root>/.project-log/journal_log.py --type memo\n"
        "python3 .project-log/journal_query.py --status\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "ignored.py").write_text("'.project-log/journal_log.py'\n")
    assert find_offenders(tmp_path) == [
        "skills/planted/SKILL.md:2: python3 <repo-root>/.project-log/journal_log.py --type memo",
        "skills/planted/SKILL.md:3: python3 .project-log/journal_query.py --status",
    ]


def test_plugin_has_no_repo_local_script_references() -> None:
    assert (PLUGIN_ROOT / "skills" / "log-init" / "SKILL.md").is_file(), "PLUGIN_ROOT is wrong"
    offenders = find_offenders(PLUGIN_ROOT)
    assert not offenders, "repo-local journal script references:\n" + "\n".join(offenders)
