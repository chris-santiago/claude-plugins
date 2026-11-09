"""
store_state.py — what a store holds, and what to do with it, as pure functions.

`ledger.py run-state` gathers the facts from the progress log and calls
`classify`, which returns one verdict and the next action:

    fresh        nothing has run: start at the plan's first task
    resume       this plan's run, not yet closed: its first incomplete task
    closing      this plan's close has started and not reached done
    finished     this plan's run has closed
    foreign      another plan's store
    ambiguous    the store can't say; the user decides

Nothing here reads files, runs git, or imports ledger.
"""

from __future__ import annotations

from typing import Literal

Verdict = Literal["fresh", "resume", "closing", "finished", "foreign", "ambiguous"]


def classify(*, has_entries: bool, plans: list[str], plan: str | None,
             plan_first_index: int | None, completed: set[str], plan_tasks: list[int],
             close_start_index: int | None, close_step: str | None) -> tuple[Verdict, str]:
    """The store's verdict for `plan` and the next action, first matching
    rule winning. `plan_first_index` is the log position of the plan's first
    `plan` entry (None when it has none); `close_start_index` is the
    position of the latest close start (None before any); `close_step` is
    the kind of the close's latest triage step (None before its first)."""
    if not has_entries:
        return "fresh", _start(plan_tasks)
    if not plans:
        if not completed and close_start_index is None:
            return "fresh", _start(plan_tasks)
        return "ambiguous", ("the store holds work but records no plan (it predates plan "
                             "recording): read it with `read` and ask the user before clearing")
    if plan not in plans or plan_first_index is None:
        return "foreign", _clear("another plan's store")
    if close_start_index is None:
        return "resume", _next_task(plan_tasks, completed, done=(
            "every task is complete: run the whole-change gate, then "
            "verification-before-completion"))
    if plan_first_index > close_start_index:
        return "finished", _clear("the close belongs to an earlier, closed run")
    if close_step == "done":
        return "finished", _clear("this run has closed")
    if close_step is None:
        return "closing", ("the close has started: dispatch its gates, then run "
                           "`triage --task close`")
    return "closing", (f"resume the close: its latest step is {close_step}; act on it, and run "
                       "`triage --task close` again after each re-check")


def _start(plan_tasks: list[int]) -> str:
    return f"start at task {plan_tasks[0]}" if plan_tasks else "start at the plan's first task"


def _next_task(plan_tasks: list[int], completed: set[str], *, done: str) -> str:
    if not plan_tasks:
        # An unknown task list must never read as a finished one.
        return ("couldn't read the plan's tasks (is the plan file there, with `Task N` "
                "headings?): fix that, then run `run-state --plan` again before resuming")
    remaining = [t for t in plan_tasks if str(t) not in completed]
    return f"resume at task {remaining[0]}" if remaining else done


def _clear(why: str) -> str:
    return (f"{why}: `clear` it before starting (show the user `report` first when "
            "anything is open; `clear` refuses without --discard-open)")
