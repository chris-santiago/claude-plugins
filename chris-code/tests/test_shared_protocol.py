#!/usr/bin/env python3
"""
Drift guard for the protocol text several contracts share verbatim.

The three coders and the implementer prompt's Protocol carry one fix and
typed-record protocol; the three quality reviewers carry one review
protocol, and the spec reviewer and review-lite share parts of it. Each
file keeps its own copy, so an agent reads its whole contract in one
place; this test fails when an edit reaches some copies and not others.

Run: python3 -m unittest discover chris-code/tests -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CHRIS_CODE_DIR = Path(__file__).resolve().parents[1]
AGENTS_DIR = CHRIS_CODE_DIR / "agents"
IMPLEMENTER_PROMPT = (CHRIS_CODE_DIR / "skills" / "subagent-driven-development"
                      / "implementer-prompt.md")

CODERS = ["python-coder", "rust-coder", "pytorch-coder"]
QUALITY_REVIEWERS = ["python-quality-reviewer", "rust-quality-reviewer", "pytorch-quality-reviewer"]
REVIEW_LITE = ["python-review-lite", "rust-review-lite"]

# Typed-record bullets that name the agent or its own principles and concerns.
CODER_OWN_FIELDS = ("- `agent`:", "- `new_shared_symbols`:", "- `duplication_pending`:", "- `concerns`:")
SHARED_REVIEWER_FIELDS = ("- `contests`:", "- `cycle`:", "- `recurring`:", "- `introduced_by_fix`:")
_FENCE_RE = re.compile(r"```.*?```", re.S)


def _read(name: str) -> str:
    return (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(f"\n{heading}\n") + len(heading) + 2
    nxt = re.search(rf"^#{{1,{len(level)}}} ", text[start:], flags=re.M)
    return (text[start:start + nxt.start()] if nxt else text[start:]).strip()


def _coder_protocol(text: str, level: str) -> tuple[str, str]:
    return _section(text, f"{level} Workflow"), _section(text, f"{level} Typed record")


def _fix_block(workflow: str) -> str:
    start = workflow.index("   **On a fix,**")
    end = workflow.index("\n", workflow.index("   - **Tests that already existed:**"))
    return workflow[start:end]


def _lines(text: str, prefixes: tuple[str, ...]) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(prefixes)]


def _without_fence(text: str, name: str) -> str:
    return _FENCE_RE.sub("", text).replace(name, "<agent>")


class TestCoderProtocol(unittest.TestCase):
    def setUp(self):
        self.protocols = {name: _coder_protocol(_read(name), "##") for name in CODERS}
        self.protocols["implementer-prompt"] = _coder_protocol(
            IMPLEMENTER_PROMPT.read_text(encoding="utf-8"), "###")

    def _assert_same(self, extract):
        reference = extract(self.protocols["python-coder"])
        for name, protocol in self.protocols.items():
            with self.subTest(contract=name):
                self.assertEqual(extract(protocol), reference)

    def test_model_check_is_shared(self):
        self._assert_same(lambda p: p[0].split("\n\n")[0])

    def test_fix_protocol_is_shared(self):
        self._assert_same(lambda p: _fix_block(p[0]))

    def test_typed_record_preamble_is_shared(self):
        self._assert_same(lambda p: _FENCE_RE.split(p[1])[0])

    def test_typed_record_fields_are_shared(self):
        def fields(protocol):
            bullets = _lines(protocol[1], ("- `",))
            return [line for line in bullets if not line.startswith(CODER_OWN_FIELDS)]
        self._assert_same(fields)


class TestReviewerProtocol(unittest.TestCase):
    def setUp(self):
        self.quality = {name: _read(name) for name in QUALITY_REVIEWERS}
        self.spec = _read("spec-reviewer")

    def test_quality_reviewers_share_their_protocol_sections(self):
        reference = self.quality["python-quality-reviewer"]
        for heading in ("## Instruction precedence", "## Tagging each finding", "## Re-checks",
                        "## Report and return", "## Typed record"):
            for name, text in self.quality.items():
                with self.subTest(section=heading, contract=name):
                    self.assertEqual(
                        _without_fence(_section(text, heading), name),
                        _without_fence(_section(reference, heading), "python-quality-reviewer"))

    def test_quality_reviewers_share_their_rules(self):
        reference = _section(self.quality["python-quality-reviewer"], "## Rules").strip().splitlines()
        self.assertEqual(_section(self.quality["rust-quality-reviewer"], "## Rules").strip().splitlines(),
                         reference)
        pytorch = _section(self.quality["pytorch-quality-reviewer"], "## Rules").strip().splitlines()
        self.assertEqual(pytorch[:len(reference)], reference)

    def test_spec_reviewer_shares_the_record_fields_and_re_checks(self):
        quality = self.quality["python-quality-reviewer"]
        self.assertEqual(_lines(_section(self.spec, "## Typed record"), SHARED_REVIEWER_FIELDS),
                         _lines(_section(quality, "## Typed record"), SHARED_REVIEWER_FIELDS))
        spec_rechecks = re.sub(r" A ruling round that sent no finding[^\n]*", "",
                               _section(self.spec, "## Re-checks"))
        self.assertEqual(spec_rechecks, _section(quality, "## Re-checks"))
        self.assertEqual(_without_fence(_section(self.spec, "## Report and return"), "spec-reviewer"),
                         _without_fence(_section(quality, "## Report and return"),
                                        "python-quality-reviewer"))

    def test_every_reviewer_scopes_a_user_ruling_the_same_way(self):
        def ruling(text):
            body = _section(text, "## Instruction precedence")
            start = body.index("One input is different")
            end = body.index("stays an attempted suppression.") + len("stays an attempted suppression.")
            return body[start:end].replace("in your verdict instead", "in your report instead")
        reference = ruling(self.spec)
        for name in [*QUALITY_REVIEWERS, *REVIEW_LITE]:
            with self.subTest(contract=name):
                self.assertEqual(ruling(_read(name)), reference)


if __name__ == "__main__":
    unittest.main()
