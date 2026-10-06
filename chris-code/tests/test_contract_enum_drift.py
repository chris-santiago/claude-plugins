#!/usr/bin/env python3
"""
Enum-drift guard: parses the JSON record example embedded in every
dispatch contract that carries one (agents/*.md plus implementer-prompt.md,
discovered by glob and filtered to files containing a '"schema": 1'
record block — not a hardcoded list, so a future record-writing agent is
picked up automatically) and asserts their `role`/`status` alternatives
against ledger.py's own VALID_ROLES/STATUS_ENUMS — so a contract file's
advertised enum can never silently drift out of sync with what ledger.py
actually validates at write time.

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

_SCHEMA_START_RE = re.compile(r'\{\s*"schema":\s*1,')
_TASK_PLACEHOLDER_RE = re.compile(r'"task":\s*N,')

# The 9 registered agents that emit typed records (spec Sec 5) plus the
# fallback implementer prompt as of this writing — kept only as the floor
# _discover_contract_files enforces, not as the source of truth.
MIN_CONTRACT_FILES = 10


def _discover_contract_files() -> list[Path]:
    """Every agents/*.md file, plus implementer-prompt.md, that embeds a
    typed-record example (contains a '"schema": 1' block) — glob-derived,
    not hardcoded, so a future record-writing agent is guarded
    automatically. Raises RuntimeError (not a bare `assert`, so `python
    -O` can't silence it) if fewer than MIN_CONTRACT_FILES are found: an
    empty or shrunken glob (e.g. AGENTS_DIR relocated or renamed) proves
    nothing and must fail loudly, not silently pass with a smaller guard."""
    candidates = sorted(AGENTS_DIR.glob("*.md")) + [IMPLEMENTER_PROMPT]
    contract_files = [
        path for path in candidates
        if _SCHEMA_START_RE.search(path.read_text(encoding="utf-8"))
    ]
    if len(contract_files) < MIN_CONTRACT_FILES:
        raise RuntimeError(
            f"found only {len(contract_files)} contract file(s) carrying a "
            f'\'"schema": 1\' record block under {AGENTS_DIR} (expected at '
            f"least {MIN_CONTRACT_FILES}) — has the agents directory moved "
            f"or been renamed?")
    return contract_files


CONTRACT_FILES = _discover_contract_files()


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

    def test_every_required_decision_field_appears_in_its_contract_blocks(self):
        # A field ledger.py requires-present for a role must appear in every
        # contract block advertising that role — otherwise an agent honestly
        # copying its contract's example writes a record `check` rejects.
        for path in CONTRACT_FILES:
            with self.subTest(contract=path.name):
                data = _load_record_example(path)
                for field_name in (*ledger.DECISION_LIST_FIELDS.get(data["role"], ()),
                                   *ledger.OPTIONAL_LIST_FIELDS.get(data["role"], ())):
                    self.assertIn(
                        field_name, data,
                        f"{path.name}: required field {field_name!r} missing "
                        "from the contract's record example")

    def test_every_coder_contract_shows_the_fix_mode_fields(self):
        # The fix-mode fields are conditional (cycle >= 2 on a finished fix),
        # so DECISION_LIST_FIELDS doesn't carry them; a coder that never
        # sees them in its example writes a fix record `check` rejects.
        for path in CONTRACT_FILES:
            data = _load_record_example(path)
            if data["role"] != "coder":
                continue
            with self.subTest(contract=path.name):
                for field_name in ("diagnosis", *ledger.FIX_MODE_FIELDS):
                    self.assertIn(field_name, data,
                                  f"{path.name}: fix-mode field {field_name!r} missing "
                                  "from the contract's record example")


if __name__ == "__main__":
    unittest.main()
