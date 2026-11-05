"""
store_state.py — what a store holds, and what to do with it, as pure functions.

`ledger.py run-state` gathers the facts from the progress log and calls
`classify`, which returns one verdict and the next action:

    fresh        nothing has run: start at the plan's first task
    resume       this plan's run, not yet closed: its first incomplete task
    remediation  a close-gate remediation plan is running on this store
    finished     this plan's run has closed
    foreign      another plan's store
    ambiguous    the store can't say; the user decides

Nothing here reads files, runs git, or imports ledger.
"""

from __future__ import annotations

import re
from typing import Literal

Verdict = Literal["fresh", "resume", "remediation", "finished", "foreign", "ambiguous"]

CLOSE_ROUND_CAP = 2
REMEDIATION_NOTE_PREFIX = "close-gate remediation r1:"
# The skills whose close resumes after round 2 (verification's remediation note).
FRONT_ENDS = ("remediating-issues", "coherent-change")
_NOTE_FIELD_RE = re.compile(r"\b(?P<key>plan|front-end)\s+(?P<value>[^,\s]+)")
# The note is free text the orchestrator wrote, and its fields come back as
# instructions in `Next:`, so only a plain Markdown path counts as a plan.
_PLAN_PATH_RE = re.compile(r"^[A-Za-z0-9._/+-]+\.md$")


def parse_remediation_note(note: str) -> dict | None:
    """The plan and front-end a close-gate remediation note names, or None
    when the note isn't one or its plan isn't a plain `.md` path. A front-end
    other than a known skill (`none` included) is None."""
    if not note.strip().lower().startswith(REMEDIATION_NOTE_PREFIX):
        return None
    fields = {m["key"]: m["value"] for m in _NOTE_FIELD_RE.finditer(note)}
    if not _PLAN_PATH_RE.match(fields.get("plan", "")):
        return None
    front_end = fields.get("front-end")
    return {"plan": fields["plan"], "front_end": front_end if front_end in FRONT_ENDS else None}


def classify(*, has_entries: bool, plans: list[str], plan: str | None,
             plan_first_index: int | None, completed: set[str], plan_tasks: list[int],
             close_round_indices: list[int], remediation: dict | None) -> tuple[Verdict, str]:
    """The store's verdict for `plan` and the next action, first matching
    rule winning. `plan_first_index` is the log position of the plan's first
    `plan` entry (None when it has none); `close_round_indices` are the log
    positions of the close-round entries; `remediation` is the parsed note."""
    if not has_entries:
        return "fresh", _start(plan_tasks)
    if not plans:
        if not completed and not close_round_indices:
            return "fresh", _start(plan_tasks)
        return "ambiguous", ("the store holds work but records no plan (it predates plan "
                             "recording): read it with `read` and ask the user before clearing")
    if plan not in plans or plan_first_index is None:
        return "foreign", _clear("another plan's store")
    if not close_round_indices:
        return "resume", _next_task(plan_tasks, completed, done=(
            "every task is complete: run the whole-change gate, then "
            "verification-before-completion"))
    if len(close_round_indices) >= CLOSE_ROUND_CAP:
        return "finished", _clear("this run has closed")
    is_remediation_plan = remediation is not None and remediation["plan"] == plan
    if plan_first_index > close_round_indices[0] and not is_remediation_plan:
        return "finished", _clear("the close round belongs to an earlier, closed run")
    if remediation is not None:
        if not is_remediation_plan:
            return "remediation", (f"this run's close handed off to {remediation['plan']}: "
                                   "run that plan instead, on this store")
        return "remediation", _next_task(plan_tasks, completed, done="every remediation task is "
                                         "complete") + "; " + _after_remediation(remediation)
    return "ambiguous", ("close round 1 has no remediation note (a close interrupted before "
                         "its note, or one that needed no remediation): ask the user before "
                         "clearing")


def _start(plan_tasks: list[int]) -> str:
    return f"start at task {plan_tasks[0]}" if plan_tasks else "start at the plan's first task"


def _next_task(plan_tasks: list[int], completed: set[str], *, done: str) -> str:
    remaining = [t for t in plan_tasks if str(t) not in completed]
    return f"resume at task {remaining[0]}" if remaining else done


def _after_remediation(remediation: dict) -> str:
    front_end = remediation.get("front_end")
    after = (f", then {front_end}'s close" if front_end else "")
    return ("when its last task completes: the whole-change gate (final-r2 records), then "
            f"verification's round 2 (`close-round --expect 2`){after}")


def _clear(why: str) -> str:
    return (f"{why}: `clear` it before starting (show the user `report` first when "
            "anything is open; `clear` refuses without --discard-open)")
