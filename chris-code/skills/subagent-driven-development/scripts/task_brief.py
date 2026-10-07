#!/usr/bin/env python3
"""
task_brief.py — assemble a per-task dispatch brief for subagent-driven-development.

Extracts one task's plan entry (fence-aware "Task N" heading match, same
semantics as the retired bash `task-brief`), requires a non-empty
`--intent`, resolves every `Consumes:` pointer in the entry, and writes a
brief that always carries the shared-shapes section from `ledger.py`.

Philosophy (spec Sec 4/6/7): a task brief cannot be produced without a
stated intent, and a stale `Consumes:` pointer stops the brief from being
written at all — the gate fires at brief-build time, against the actor who
can fix it (the orchestrator writing the dispatch), instead of staying
prose someone has to remember. On any failure, nothing is written.

`Consumes:` pointer detection extracts spans directly from each bullet's
raw text (backticked spans, §-ref spans, then bare path-shaped runs in
what's left) rather than classifying whitespace-split tokens — span
extraction is immune to glued punctuation (an arrow, a comma, a §-ref
with no space) by construction, where token classification needed an
ever-growing set of punctuation apologies. See find_consumes_pointers.

Every task entry must also carry a `Cases:` line (the cases its rule
covers, or `n/a — <reason>`); the brief carries it verbatim with the entry.

Exit codes: 2 usage (bad args, missing files, task not found, --spec
required but absent), 3 missing/empty --intent, a stale Consumes:
pointer (naming each), or a missing/empty Cases: line.

Usage: python3 task_brief.py PLAN_FILE TASK_N --intent TEXT
           [--note TEXT]... [--spec PATH] [--constraints-from PLAN]
           [--store DIR] [-o OUT]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
# The one sanctioned sys.path hack in this codebase: this script is
# invoked directly as `python3 task_brief.py` (stdlib only, no installed
# package), so ledger.py's directory must be added to sys.path explicitly
# to import it as a sibling module.
sys.path.insert(0, str(SCRIPTS_DIR))
import ledger  # noqa: E402

__all__ = [
    "EXIT_USAGE", "EXIT_INVALID",
    "UsageError", "BriefValidationError",
    "ConsumesPointer", "ConsumesFindings", "BriefRequest",
    "extract_task_entry", "extract_section", "heading_section_numbers",
    "find_consumes_pointers", "validate_consumes",
    "build_brief", "run", "build_parser", "main",
]

EXIT_USAGE = 2
EXIT_INVALID = 3

TASK_ANY_RE = re.compile(r"^#+[ \t]+Task[ \t]+[0-9]+(?:[^0-9]|$)")
CONSUMES_LINE_RE = re.compile(r"^\s*[-*+]\s*Consumes:\s*(.*)$")
CASES_LINE_RE = re.compile(r"^\s*[-*+]\s*Cases:\s*(.*)$")
# "n/a" must carry a reason after a dash: the planner has to decide a task
# has no input domain, not skip the question.
CASES_NA_RE = re.compile(r"^n/a\b\s*(?:[—–-]\s*(?P<reason>.*))?$", re.IGNORECASE)
HEADING_NUMBER_RE = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)?)\.?(?=\s|$)")

# A backtick pair unambiguously delimits its content; extracted straight
# from a bullet's raw text regardless of what's glued outside it.
BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")
# A §-ref span, including a chained run like "§6/§7" matched as ONE span
# so it can be removed as a unit — otherwise the "/" between "§6" and
# "§7" would be left stranded and misread as a trailing-slash pointer.
SECTION_REF_SPAN_RE = re.compile(r"§\d+(?:\.\d+)?(?:/§\d+(?:\.\d+)?)*")
SECTION_NUMBER_RE = re.compile(r"§(\d+(?:\.\d+)?)")
# A run of path/symbol characters. Includes "." and "_" without regard to
# position (leading or not), so "./x/y.py", "../x/y.py", and "_pkg/y.py"
# match in full, unstripped, starting exactly where the author wrote them.
PATH_RUN_RE = re.compile(r"[A-Za-z0-9_./:-]+")


class UsageError(Exception):
    """Bad invocation: exit 2."""


class BriefValidationError(Exception):
    """Missing/empty --intent or a stale Consumes: pointer: exit 3."""


def _read_text(path: Path, *, error_cls: type[Exception], label: str) -> str:
    """Read a UTF-8 text file, mapping an unreadable/undecodable file to a
    corrective error_cls instead of a bare traceback (same convention as
    ledger.py's own read guards)."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise error_cls(f"cannot read {label}: {e}") from e


@dataclass
class ConsumesPointer:
    raw: str
    path: str
    symbol: str = ""


@dataclass
class ConsumesFindings:
    section_refs: list[str] = field(default_factory=list)
    pointers: list[ConsumesPointer] = field(default_factory=list)


@dataclass(frozen=True)
class BriefRequest:
    """run()'s explicit contract, so a caller (main(), a test) states its
    intent in named fields instead of building an argparse.Namespace just
    to hand run() something with the right attribute names. main()
    translates the parsed CLI args into one of these; nothing about run()
    depends on argparse. `note` is a tuple, not a list: frozen is only a
    real guarantee if every field is itself immutable — a list field
    would let a caller mutate it after construction despite the frozen
    dataclass."""
    plan_file: str
    task_n: str
    intent: str | None
    note: tuple[str, ...] = ()
    spec: str | None = None
    constraints_from: str | None = None
    store: str | None = None
    output: str | None = None


def _iter_fence_aware(lines: list[str]):
    """Yield (line, in_fence) pairs. in_fence reflects the state *after*
    toggling on the current line — matching the retired bash task-brief's
    awk ordering (toggle, then match), so a fenced code block's comments
    (e.g. a Python "# Task 3" line) never pose as a real heading."""
    infence = False
    for line in lines:
        if line.startswith("```"):
            infence = not infence
        yield line, infence


def extract_task_entry(plan_text: str, task_n: str) -> str:
    """Extract one task's plan entry: from its any-level 'Task N' heading
    through the next 'Task <number>' heading of any number, fence-aware.
    Preserves the retired bash task-brief's awk semantics verbatim,
    including its quirk that only Task-N headings (not other headings,
    e.g. '## Acceptance checks') close a section."""
    this_task_re = re.compile(r"^#+[ \t]+Task[ \t]+" + re.escape(task_n) + r"(?:[^0-9]|$)")
    out: list[str] = []
    intask = False
    for line, infence in _iter_fence_aware(plan_text.splitlines(keepends=True)):
        if not infence and TASK_ANY_RE.match(line):
            intask = bool(this_task_re.match(line))
        if intask:
            out.append(line)
    entry = "".join(out)
    if not entry.strip():
        raise UsageError(
            f"task {task_n} not found in plan (no heading matching 'Task {task_n}')")
    return entry


def extract_section(text: str, heading_word: str) -> str:
    """The first heading whose text contains heading_word as a whole word,
    through the next heading at the same or shallower level, fence-aware.
    Used for --constraints-from's verbatim 'Constraints' section."""
    heading_re = re.compile(r"^(#{1,6})\s+.*\b" + re.escape(heading_word) + r"\b")
    other_heading_re = re.compile(r"^(#{1,6})\s")
    out: list[str] = []
    level: int | None = None
    for line, infence in _iter_fence_aware(text.splitlines(keepends=True)):
        if infence:
            if level is not None:
                out.append(line)
            continue
        if level is None:
            m = heading_re.match(line)
            if m:
                level = len(m.group(1))
                out.append(line)
            continue
        m = other_heading_re.match(line)
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    if level is None:
        raise UsageError(f"no {heading_word!r} heading found")
    return "".join(out)


def heading_section_numbers(spec_text: str) -> set[str]:
    """Leading section numbers of every fence-aware heading in a spec
    file, e.g. '## 6. Canonical interfaces' -> '6'."""
    numbers = set()
    for line, infence in _iter_fence_aware(spec_text.splitlines(keepends=True)):
        if infence:
            continue
        m = HEADING_NUMBER_RE.match(line)
        if m:
            numbers.add(m.group(1))
    return numbers


def _is_url(token: str) -> bool:
    return "://" in token


def _is_file_shaped(token: str) -> bool:
    """A bare path-character run counts as a file-path pointer only if it
    contains a "/" and looks like an actual path: a dot in its final
    "/"-segment (a file extension), or the run itself ends with "/" (a
    directory reference). Slashed prose with no dot in the final segment —
    "store/records", "read/write", "Task 1/2" — stays prose. A slashless
    run — "e.g", "3.9", "v1.2", a bare filename like "ledger.py" — is
    never file-shaped: without a "/" it can't be told apart from an
    abbreviation, a version number, or a filename mentioned in passing,
    and this also matches the backticked rule (see
    _extract_backticked_pointers), where a slashless span is never a
    pointer either (it needs "/" or "::"), so a slashless filename is
    consistently non-pointer in both forms."""
    if token.endswith("/"):
        return True
    if "/" not in token:
        return False
    return "." in token.rsplit("/", 1)[-1]


def _split_path_symbol(token: str) -> tuple[str, str] | None:
    """Split on the first "::", but only if BOTH halves are non-empty AND
    the path half looks like a file (contains "/" or a dot) — symmetric
    across bare and backticked forms. "::" alone isn't decisive: this
    repo also ships Rust agents, and "std::vector"/"serde::Deserialize"
    are scope-resolution syntax, not a path pointer, in either form.
    "note::" (empty symbol) and "::1" (empty path — the IPv6 loopback
    shorthand, plausible near a "git@..." remote mention) are excluded
    the same way."""
    if "::" not in token:
        return None
    path, symbol = token.split("::", 1)
    if not path or not symbol:
        return None
    if "/" not in path and "." not in path:
        return None
    return path, symbol


def _pointer_from_token(token: str, split: tuple[str, str] | None) -> ConsumesPointer:
    """Precondition: split IS _split_path_symbol(token), computed once by
    the caller's classify step and passed through to avoid a redundant
    second call. Nothing checks it — pass anything else and raw and
    path/symbol disagree."""
    if split is not None:
        path, symbol = split
        return ConsumesPointer(raw=token, path=path, symbol=symbol)
    return ConsumesPointer(raw=token, path=token)


def _extract_backticked_pointers(text: str) -> list[ConsumesPointer]:
    """Every path/symbol-shaped word inside a backticked span is a
    pointer. A backticked span may contain whitespace — a shell command
    is idiomatic in this repo's plans (e.g.
    "`python3 scripts/ledger.py check`") — so each whitespace-separated
    part is shape-tested independently by the backticked rule ("/" or a
    valid "::" split) rather than the whole span being treated as one
    token; "python3" and "check" are skipped as non-path words while the
    real path buried in the command is recovered and validated. The
    backticks themselves unambiguously delimit the author's content, so
    this reads spans straight out of the raw text — whatever is glued
    directly outside a backtick pair (an arrow, a comma, a §-ref) never
    matters."""
    pointers = []
    for span in BACKTICK_SPAN_RE.findall(text):
        for word in span.split():
            if _is_url(word):
                continue
            split = _split_path_symbol(word)
            if "/" in word or split is not None:
                pointers.append(_pointer_from_token(word, split))
    return pointers


def _unwrap_emphasis(token: str) -> str:
    """Strip a markdown underscore-emphasis wrapper — "_..._" (italic) or
    "__..__" (bold) — from a bare path-character run, but only when the
    leading and trailing underscore runs match in count: "_chris-code/x.py_"
    and "__x.py__" unwrap to the clean inner path. A leading-only
    underscore ("_pkg/y.py", a real path segment — there's no matching
    close) is left untouched, since "_" is also a legitimate path
    character and asterisk emphasis ("**x.py**") never enters this
    function at all (PATH_RUN_RE's character class excludes "*", so a
    "**"-wrapped run is already bounded correctly by the regex match)."""
    lead = len(token) - len(token.lstrip("_"))
    trail = len(token) - len(token.rstrip("_"))
    if lead and lead == trail and len(token) > 2 * lead:
        return token[lead:len(token) - trail]
    return token


def _extract_bare_pointers(text: str) -> list[ConsumesPointer]:
    """Every path-shaped or "::"-bearing run of path characters in text
    that has already had backticked spans and §-ref spans masked out (see
    find_consumes_pointers) — so backtick content isn't double-scanned and
    a stray "/" from a removed §-ref chain never leaks through. A run with
    a valid path::symbol split (see _split_path_symbol) is a pointer
    regardless of whether the path half also satisfies _is_file_shaped
    (e.g. "ledger.py::list_shapes" — no "/" in "ledger.py", but the dot
    in the path half is enough); a run with no valid "::" split is a
    pointer only if _is_file_shaped. Trailing "." characters are rstripped
    first (sentence-final punctuation with no space before it — "...in
    scripts/tools."), then a matched-pair underscore-emphasis wrapper is
    unwrapped (see _unwrap_emphasis) — but nothing is ever trimmed from
    the front on its own, so "./x/y.py", "../x/y.py", and a genuinely
    leading-only "_pkg/y.py" resolve exactly as written."""
    pointers = []
    for match in PATH_RUN_RE.finditer(text):
        token = match.group(0).rstrip(".")
        token = _unwrap_emphasis(token)
        if not token or _is_url(token):
            continue
        split = _split_path_symbol(token)
        if split is not None or _is_file_shaped(token):
            pointers.append(_pointer_from_token(token, split))
    return pointers


def find_consumes_pointers(task_entry: str) -> ConsumesFindings:
    """Every §-ref, and every pointer, across all 'Consumes:' bullets in
    the task entry — by extracting spans directly from each bullet's raw
    text rather than classifying whitespace-split tokens (spec Sec 6):
    token classification needed an ever-growing set of punctuation
    apologies — glued arrows, glued §-refs, markdown wrappers — that span
    extraction sidesteps structurally, since a regex match's boundary is
    never "wrong whitespace", only a character outside its class.

    Per bullet: (1) §-ref spans (e.g. "§6", the chained "§6/§7") are
    pulled out first, as combined runs, so a chain is removed as one
    unit and never leaves a stray "/" behind. (2) Backticked spans are
    then extracted straight from the untouched original text (see
    _extract_backticked_pointers) — independent of step 1, since a
    backtick pair delimits its own content regardless of what's glued
    around it. (3) Whatever's left, with the §-ref and backtick spans
    masked out to a single space each (so surrounding words never fuse),
    is scanned for bare pointers (see _extract_bare_pointers)."""
    findings = ConsumesFindings()
    for line in task_entry.splitlines():
        m = CONSUMES_LINE_RE.match(line)
        if not m:
            continue
        text = m.group(1)

        for span in SECTION_REF_SPAN_RE.findall(text):
            findings.section_refs += SECTION_NUMBER_RE.findall(span)

        findings.pointers += _extract_backticked_pointers(text)

        remaining = SECTION_REF_SPAN_RE.sub(" ", text)
        remaining = BACKTICK_SPAN_RE.sub(" ", remaining)
        findings.pointers += _extract_bare_pointers(remaining)
    return findings


def _require_spec_for_section_refs(section_refs: list[str], spec_path: str | None) -> None:
    """Raise UsageError (exit 2) if the entry names a §-ref but --spec was
    not given. Kept separate from _validate_section_refs on purpose: that
    function takes spec_path as a required str, not Optional, so it has
    no None case to reason about — the usage bucket (this function) and
    the validation bucket (_validate_section_refs) are each one function,
    and the split removes the "unreachable None" a static analyzer used
    to have to prove around a single function juggling both."""
    if section_refs and spec_path is None:
        refs = ", ".join(f"§{r}" for r in sorted(set(section_refs)))
        raise UsageError(f"task entry references {refs} but --spec was not provided")


def _dedupe_pointers(pointers: list[ConsumesPointer]) -> list[ConsumesPointer]:
    """Collapse pointers naming identical raw text, keeping first-seen
    order — a path mentioned twice in one entry (once bare, once repeated
    in a second Consumes: bullet, say) produces one failure, not two.
    path/symbol derive deterministically from raw, so keying by raw loses
    nothing."""
    return list({pointer.raw: pointer for pointer in pointers}.values())


def _validate_pointers(pointers: list[ConsumesPointer]) -> list[str]:
    """One failure message per stale path/path::symbol pointer, deduped
    by raw text first so a twice-named path errors once."""
    failures: list[str] = []
    for pointer in _dedupe_pointers(pointers):
        path = Path(pointer.path)
        if not path.exists():
            failures.append(f"Consumes: path does not exist: `{pointer.raw}`")
            continue
        if pointer.symbol:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                failures.append(f"Consumes: cannot read `{pointer.path}` to check symbol: {e}")
                continue
            if pointer.symbol not in content:
                failures.append(
                    f"Consumes: symbol {pointer.symbol!r} not found in `{pointer.path}`")
    return failures


def _validate_section_refs(section_refs: list[str], spec_path: str) -> list[str]:
    """One failure message per §-ref that doesn't resolve to a heading in
    spec_path. spec_path is required (str, not Optional): call this only
    after _require_spec_for_section_refs has confirmed one was given."""
    if not section_refs:
        return []
    spec_text = _read_text(Path(spec_path), error_cls=UsageError, label=f"spec file {spec_path}")
    available = heading_section_numbers(spec_text)
    return [f"Consumes: §{ref} not found as a heading in {spec_path}"
            for ref in sorted(set(section_refs)) if ref not in available]


def validate_consumes(task_entry: str, spec_path: str | None) -> None:
    """Raise UsageError if the entry needs --spec and none was given;
    raise BriefValidationError naming every stale pointer otherwise."""
    findings = find_consumes_pointers(task_entry)
    _require_spec_for_section_refs(findings.section_refs, spec_path)

    failures = _validate_pointers(findings.pointers)
    if spec_path is not None:
        failures += _validate_section_refs(findings.section_refs, spec_path)

    if failures:
        raise BriefValidationError("; ".join(failures))


def validate_cases(task_entry: str) -> None:
    """Raise BriefValidationError unless the entry carries a 'Cases:'
    bullet (outside a code fence) listing the cases its rule covers, or
    'n/a — <reason>'. Coders given only the cited behavior patch only it,
    and sibling cases (size=None, size<0) then surface one review cycle at
    a time; the case list is the planner's call, made up front."""
    values = [m.group(1).strip()
              for line, in_fence in _iter_fence_aware(task_entry.splitlines())
              if not in_fence and (m := CASES_LINE_RE.match(line))]
    if not values:
        raise BriefValidationError(
            "missing 'Cases:' line: list the cases the task's rule covers (the case, "
            "its siblings, boundary inputs), or 'Cases: n/a — <reason>'")
    for value in values:
        if not value:
            raise BriefValidationError("empty 'Cases:' line: list the cases, or 'n/a — <reason>'")
        na = CASES_NA_RE.match(value)
        if na and not (na.group("reason") or "").strip():
            raise BriefValidationError(
                f"'Cases: {value}' needs a reason: write 'Cases: n/a — <why this task "
                "has no input domain>'")


def build_brief(*, task_n: str, task_entry: str, intent: str, notes: tuple[str, ...],
                 constraints: str | None, shapes_text: str) -> str:
    """Assemble the brief markdown (spec Sec 4): the task's plan entry,
    the intent, orchestrator cross-task notes, the verbatim Constraints
    section (only when --constraints-from was given), and the
    always-present shared-shapes section (no flag disables it)."""
    parts = [f"# Task {task_n} brief", "", "## Task entry", "", task_entry.rstrip("\n"), ""]
    parts += ["## Intent", "", intent, ""]
    parts += ["## Cross-task notes", ""]
    parts += [f"- {note}" for note in notes] if notes else ["(none)"]
    parts.append("")
    if constraints is not None:
        parts += ["## Constraints", "", constraints.rstrip("\n"), ""]
    parts += ["## Shared shapes already built", "", shapes_text, ""]
    return "\n".join(parts).rstrip("\n") + "\n"


def _require_existing_file(path_str: str, label: str) -> Path:
    """The one existence check every file-taking input shares; raises the
    same UsageError message shape for each of them."""
    path = Path(path_str)
    if not path.is_file():
        raise UsageError(f"no such {label}: {path_str}")
    return path


def run(request: BriefRequest) -> Path:
    """Build and write the brief; return its path. Raises UsageError
    (exit 2) or BriefValidationError (exit 3) on any failure — nothing is
    written until every check passes."""
    plan_path = _require_existing_file(request.plan_file, "plan file")
    plan_text = _read_text(plan_path, error_cls=UsageError, label=f"plan file {request.plan_file}")
    task_entry = extract_task_entry(plan_text, request.task_n)

    intent = (request.intent or "").strip()
    if not intent:
        raise BriefValidationError(
            "missing/empty --intent: a task brief cannot be produced without a stated intent")

    if request.spec is not None:
        _require_existing_file(request.spec, "spec file")
    validate_consumes(task_entry, request.spec)
    validate_cases(task_entry)

    constraints = None
    if request.constraints_from is not None:
        constraints_path = _require_existing_file(
            request.constraints_from, "plan file for --constraints-from")
        constraints_text = _read_text(
            constraints_path, error_cls=UsageError,
            label=f"--constraints-from file {request.constraints_from}")
        constraints = extract_section(constraints_text, "Constraints")

    try:
        store_dir = ledger.get_store_dir(request.store)
    except RuntimeError as e:
        raise UsageError(str(e)) from e
    shapes_text = ledger.render_shapes(ledger.list_shapes(ledger.load_records(store_dir)))

    brief = build_brief(task_n=request.task_n, task_entry=task_entry, intent=intent,
                         notes=request.note, constraints=constraints, shapes_text=shapes_text)

    try:
        if request.output is not None:
            out_path = Path(request.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            ledger.ensure_store(store_dir)
            out_path = store_dir / f"task-{request.task_n}-brief.md"
        out_path.write_text(brief, encoding="utf-8")
    except OSError as e:
        raise UsageError(f"cannot write brief: {e}") from e

    return out_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble a per-task dispatch brief for subagent-driven-development.")
    parser.add_argument("plan_file", help="path to the plan markdown file")
    parser.add_argument("task_n", help="task number/label as it appears in the Task heading")
    parser.add_argument(
        "--intent", default=None,
        help="required: the observable outcome this task must produce")
    parser.add_argument(
        "--note", action="append", default=[],
        help="repeatable orchestrator cross-task note")
    parser.add_argument(
        "--spec", default=None,
        help="design spec path; required iff the task entry contains a §-ref")
    parser.add_argument(
        "--constraints-from", default=None, metavar="PLAN",
        help="plan file to pull the verbatim Constraints section from")
    parser.add_argument(
        "--store", default=None,
        help="override the ledger store directory (default: .sdd/ at the repo toplevel)")
    parser.add_argument(
        "-o", "--output", default=None,
        help="output path (default: <store>/task-<N>-brief.md)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    request = BriefRequest(
        plan_file=args.plan_file, task_n=args.task_n, intent=args.intent,
        note=tuple(args.note), spec=args.spec, constraints_from=args.constraints_from,
        store=args.store, output=args.output,
    )
    try:
        out_path = run(request)
    except UsageError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except BriefValidationError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(EXIT_INVALID)
    print(out_path)


if __name__ == "__main__":
    main()
