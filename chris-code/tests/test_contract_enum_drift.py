#!/usr/bin/env python3
"""
Enum-drift guard: parses the JSON record example embedded in each of the
10 dispatch contracts (the 9 registered agents plus the implementer-prompt.md
fallback template) and asserts their `role`/`status` alternatives against
ledger.py's own VALID_ROLES/STATUS_ENUMS — so a contract file's advertised
enum can never silently drift out of sync with what ledger.py actually
validates at write time.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

CHRIS_CODE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = CHRIS_CODE_DIR / "skills" / "subagent-driven-development" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import ledger  # noqa: E402

AGENTS_DIR = CHRIS_CODE_DIR / "agents"
IMPLEMENTER_PROMPT = (CHRIS_CODE_DIR / "skills" / "subagent-driven-development"
                       / "implementer-prompt.md")

# The 9 registered agents that emit typed records (spec Sec 5), plus the
# fallback implementer prompt, which carries the coder contract.
CONTRACT_FILES = [
    AGENTS_DIR / f"{name}.md" for name in (
        "python-coder", "pytorch-coder", "rust-coder", "spec-reviewer",
        "python-quality-reviewer", "pytorch-quality-reviewer", "rust-quality-reviewer",
        "python-review-lite", "rust-review-lite",
    )
] + [IMPLEMENTER_PROMPT]

_SCHEMA_START_RE = re.compile(r'\{\s*"schema":\s*1,')
_TASK_PLACEHOLDER_RE = re.compile(r'"task":\s*N,')


def _extract_record_block(text: str) -> str:
    """The first JSON-object-shaped block whose first key is "schema": 1
    — brace-matched from that point, quote-aware so a literal "{"/"}"
    inside a string value never miscounts. Every contract file embeds its
    typed-record example this way, whether inside a ```json fence (the 9
    agent files) or inline within a larger ``` prompt-template fence
    (implementer-prompt.md) — one extraction rule covers both, rather than
    a special case per file."""
    match = _SCHEMA_START_RE.search(text)
    if match is None:
        raise AssertionError('no \'{"schema": 1,\' record block found')
    start = match.start()
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("record block's braces never balance")


def _load_record_example(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    block = _extract_record_block(text)
    # implementer-prompt.md's block uses a literal "N" placeholder for
    # `task` (a real task number isn't known in a template) instead of an
    # integer, which json.loads rejects; normalize it before parsing. A
    # no-op everywhere else, since only the template writes "N".
    block = _TASK_PLACEHOLDER_RE.sub('"task": 0,', block)
    return json.loads(block)


class TestContractEnumsMatchLedger(unittest.TestCase):
    """Every dispatch contract's role is one ledger.py validates, and
    every '|'-separated status alternative it advertises is exactly that
    role's real enum — neither missing an alternative ledger.py accepts
    nor claiming one it doesn't. Catches contract drift here, in a fast
    test, instead of in an agent's own context at write-time `check`."""

    def test_every_contract_role_and_status_match_ledger_enums(self):
        for path in CONTRACT_FILES:
            with self.subTest(contract=path.name):
                data = _load_record_example(path)
                role = data["role"]
                self.assertIn(role, ledger.VALID_ROLES,
                               f"{path.name}: role {role!r} not in ledger.VALID_ROLES")
                alternatives = {s.strip() for s in data["status"].split("|")}
                allowed = ledger.STATUS_ENUMS[role]
                self.assertEqual(
                    alternatives, allowed,
                    f"{path.name}: status alternatives {sorted(alternatives)} != "
                    f"ledger.STATUS_ENUMS[{role!r}] = {sorted(allowed)}")


if __name__ == "__main__":
    unittest.main()
