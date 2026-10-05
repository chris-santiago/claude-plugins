#!/usr/bin/env python3
"""
Regression guard: skill prose must call SDD's scripts through
`$SDD_SCRIPTS`, never a repo-relative `scripts/...` path.

A skill runs from the user's project, while its scripts live at the plugin
install path (`~/.claude/plugins/cache/.../skills/subagent-driven-development/scripts/`).
A bare `scripts/ledger.py` resolves against the project's working directory,
where it is missing or, worse, an unrelated script. Development inside this
repo masks the bug, because there the relative path happens to exist.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

# Lowercase `scripts/` followed by one of SDD's entry points. The sanctioned
# form `$SDD_SCRIPTS/ledger.py` never matches: the variable is uppercase.
BARE_SCRIPT_CALL = re.compile(r"scripts/(ledger\.py|task_brief\.py|review-package)\b")

MIN_EXPECTED_FILE_COUNT = 20


class TestSkillsUseSddScriptsVariable(unittest.TestCase):
    def test_no_skill_prose_calls_scripts_by_relative_path(self):
        files = sorted(SKILLS_DIR.rglob("*.md"))
        # An empty scan (a moved skills dir) must fail, not pass green.
        if len(files) < MIN_EXPECTED_FILE_COUNT:
            raise RuntimeError(f"scanned only {len(files)} skill files under {SKILLS_DIR}")
        offenders = [
            f"{path.relative_to(SKILLS_DIR)}:{lineno}: {line.strip()[:100]}"
            for path in files
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if BARE_SCRIPT_CALL.search(line)
        ]
        self.assertEqual(offenders, [], "use $SDD_SCRIPTS:\n" + "\n".join(offenders))

    def test_pattern_spares_the_sanctioned_form(self):
        self.assertIsNone(BARE_SCRIPT_CALL.search('python3 "$SDD_SCRIPTS/ledger.py" read'))
        self.assertIsNotNone(BARE_SCRIPT_CALL.search("python3 scripts/ledger.py read"))
        self.assertIsNotNone(BARE_SCRIPT_CALL.search("subagent-driven-development/scripts/review-package"))


if __name__ == "__main__":
    unittest.main()
