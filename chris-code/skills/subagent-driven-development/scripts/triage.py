"""
triage.py — the review-fix loop's rules, as pure functions, for a task and
for the completion close.

Every finding is its own run of entries in the progress log; its current
state is its latest entry. `ledger.py triage` reads the states and the
scope's records and calls three functions here:

- `first_state`: a finding's state the first time triage sees it.
- `observe`: what the records' re-checks change (a sent finding fixed,
  still raised, conceded or held).
- `step`: the next step from the states, and the state changes it makes
  (findings sent, notes noted, spent findings put to the user).
- `unchecked` and `awaiting`: the records a fix round still waits on for
  its re-check; ledger.py takes no new step while any is outstanding.

Nothing here reads files, runs git, or imports ledger: ledger.py runs as
__main__, and a module that imported it would load a second copy with its
own RecordError.

In a task, a finding's tier comes from its severity and reach alone:

    S1-S2 local/class -> note       S1-S2 contract -> defer (filed)
    S3-S5 local/class -> patch      S3-S5 contract -> holistic

At the close, an intent not-met, a failing commit gate or S4 and worse is
fix, and everything else waits for the user. A coder's `root cause:`
concern and a reach the coder raised are holistic. `recurring` and
`introduced_by_fix` never change a state; they feed telemetry.

A patch, polish or ruling step whose every finding is one site of S3 or
less is `inline`: the user may have the orchestrator fix it instead of a
coder. The round, its cap and its re-checks are the same either way.
"""

from __future__ import annotations

SERIOUS = 3
BLOCKING_SEVERITY = 4
MAX_FIX_ROUNDS = 2
FIX_ROUND_KINDS = ("patch", "holistic")
FIX_KINDS = ("patch", "holistic", "polish", "ruling")
# Steps the orchestrator may fix itself when every finding is small.
INLINE_KINDS = ("patch", "polish", "ruling")
INLINE_MAX_SEVERITY = 3
STATES = ("fix", "sent", "held", "waiting", "note", "noted", "filed", "fixed", "dropped")
# States no record can change: only a user's ruling (or nothing) moves them.
FINAL_STATES = ("noted", "filed", "fixed", "dropped")
# Findings no longer anyone's work; a re-check gets them as settled.
SETTLED_STATES = ("fixed", "dropped", "filed")
# What a finding entry keeps of a raised finding: enough to fix, file or
# rule it after its record has been rewritten.
FINDING_DATA = ("source", "gate", "severity", "reach", "rule", "sites", "claim", "not_met")


def tier(finding: dict, reach_raised: set[str]) -> str:
    """A task finding's tier: note, defer, patch or holistic, from severity
    and (effective) reach."""
    contract = finding["reach"] == "contract" or finding["id"] in reach_raised
    if finding["severity"] < SERIOUS:
        return "defer" if contract else "note"
    return "holistic" if contract else "patch"


def blocks_close(finding: dict) -> bool:
    return bool(finding.get("not_met") or finding.get("gate")
                or finding["severity"] >= BLOCKING_SEVERITY)


def first_state(finding: dict, close: bool) -> str:
    """The state of a finding triage sees for the first time."""
    if close:
        return "fix" if blocks_close(finding) else "waiting"
    return {"note": "note", "defer": "filed"}.get(tier(finding, set()), "fix")


def observe(states: dict[str, dict], raised: list[dict], answers: dict[str, str],
            versions: dict[str, str], close: bool) -> list[dict]:
    """The state changes the records make, each {id, state, from} (and
    `data` on a first sighting). `states` maps an id to its current state
    entry ({state, data, seen, ...}); `raised` are the findings the scope's
    records raise now; `answers` the raising reviewers' contest verdicts;
    `versions` each record's current version, which changes on every write.
    Only a re-check changes a finding: its raising record written since
    the finding was sent or held (its version moved past `seen`), even
    with the same content. Then a sent finding is fixed when
    gone, held on a hold and fix again when still raised, and a concede
    fixes a sent or held one. Records never change any other state, and a
    final one raised again is ignored (a `reopens` finding has an id of its
    own)."""
    changes = []
    raised_ids = set()
    for finding in raised:
        fid = finding["id"]
        raised_ids.add(fid)
        current = states.get(fid)
        if current is None:
            changes.append({"id": fid, "state": first_state(finding, close), "from": None,
                            "data": {k: finding.get(k) for k in FINDING_DATA}})
            continue
        state, verdict = current["state"], answers.get(fid)
        if state not in ("sent", "held") or not _rechecked(current, versions):
            continue
        if verdict == "concede":
            changes.append({"id": fid, "state": "fixed", "from": state})
        elif state == "sent":
            changes.append({"id": fid, "state": "held" if verdict == "hold" else "fix",
                            "from": state})
    for fid, current in states.items():
        if current["state"] == "sent" and fid not in raised_ids and _rechecked(current, versions):
            changes.append({"id": fid, "state": "fixed", "from": "sent"})
    return changes


def _rechecked(current: dict, versions: dict[str, str]) -> bool:
    return versions.get(_source(current)) != current.get("seen")


def unchecked(states: dict[str, dict], versions: dict[str, str]) -> list[str]:
    """The raising records of sent findings not re-checked since the send:
    a round lasts until each finding it sent has been re-checked."""
    return sorted({_source(s) or "" for s in states.values()
                   if s["state"] == "sent" and not _rechecked(s, versions)})


def awaiting(awaited: dict[str, str | None], versions: dict[str, str]) -> list[str]:
    """The records a fix round still waits on: each it named for its
    re-check (`awaited`, a record's version when the round was sent) that
    hasn't been written since."""
    return sorted(stem for stem, seen in awaited.items() if versions.get(stem) == seen)


def _source(current: dict) -> str | None:
    return (current.get("data") or {}).get("source")


def apply(states: dict[str, dict], changes: list[dict]) -> dict[str, dict]:
    """The states after `changes`, without touching `states`. A change is
    triage's unless it says otherwise (`by`)."""
    after = {fid: dict(entry) for fid, entry in states.items()}
    for change in changes:
        entry = after.setdefault(change["id"], {})
        entry["state"] = change["state"]
        entry["by"] = change.get("by", "triage")
        if "data" in change:
            entry["data"] = change["data"]
    return after


def step(states: dict[str, dict], *, close: bool, prior: list[dict], root_causes: list[str],
         reach_raised: set[str], unclear: list[str], override: bool,
         undelivered_note: bool) -> dict:
    """The scope's next step from its finding states (after `observe`), as
    a triage entry without its type, task and tree, plus `changes`: the
    state changes the step makes (fix findings sent, notes noted, spent
    findings put to the user as waiting). `prior` are the scope's earlier
    entries; `override` (a task only) says the user overrode an open choice
    since the last entry; `unclear` (the close only) are the intent
    statements still can't-tell. A fix finding whose latest entry is the
    user's was ruled fix: right after the user was asked, or once the
    scope's rounds are spent, it starts a ruling round, and other fix
    findings past the cap wait for the user instead."""
    by_state = {s: sorted(fid for fid, e in states.items() if e["state"] == s) for s in STATES}
    steps = [e for e in prior if e.get("kind") != "clarify"]
    last_kind = steps[-1]["kind"] if steps else None
    rounds = sum(1 for e in prior if e.get("kind") in FIX_ROUND_KINDS)
    ask = "decide" if close else "escalate"
    fix, held, waiting = by_state["fix"], by_state["held"], by_state["waiting"]
    ruled = [fid for fid in fix if states[fid].get("by") == "user"]
    notes = [] if close else by_state["note"]
    changes: list[dict] = []
    open_work = bool(fix or root_causes)
    spent = rounds >= MAX_FIX_ROUNDS or last_kind == "ruling"

    if close and last_kind == "done":
        kind = "done"
    elif close and unclear:
        kind = "clarify"
    elif ruled and (spent or last_kind == ask):
        kind = "ruling"
        if spent:
            rest = [fid for fid in fix if fid not in ruled]
            changes += [{"id": fid, "state": "waiting", "from": "fix"} for fid in rest]
            waiting = sorted({*waiting, *rest})
            fix = ruled
    elif not close and override and last_kind in ("escalate", "done"):
        kind = "ruling"
    elif open_work and spent:
        kind = ask
        changes += [{"id": fid, "state": "waiting", "from": "fix"} for fid in fix]
        waiting = sorted({*waiting, *fix})
        fix = []
    elif open_work:
        contract = bool(root_causes) or any(
            (states[fid].get("data") or {}).get("reach") == "contract" or fid in reach_raised
            for fid in fix)
        kind = "holistic" if contract else "patch"
    elif held or waiting:
        kind = ask
    elif notes or undelivered_note:
        kind = "polish"
    else:
        kind = "done"

    sent = fix if kind in ("patch", "holistic", "ruling") else []
    tier_of = "holistic" if kind == "holistic" else "patch"
    shown = [_shown(fid, states[fid], tier_of) for fid in sent]
    changes += [{"id": fid, "state": "sent", "from": "fix"} for fid in sent]
    if kind in FIX_KINDS and not close:
        shown += [_shown(fid, states[fid], "note") for fid in notes]
        changes += [{"id": fid, "state": "noted", "from": "note"} for fid in notes]
    after = apply(states, changes)
    inline = kind in INLINE_KINDS and not root_causes and inline_eligible(
        [states[f["id"]].get("data") or {} for f in shown],
        {f["id"] for f in shown} & reach_raised)
    if close:
        recheck = "intent" if kind == "clarify" else ("raising" if sent else "none")
    else:
        recheck = _recheck(kind, [f for f in shown if f["tier"] != "note"])
    return {
        "kind": kind,
        "inline": inline,
        "round": rounds + (1 if kind in FIX_ROUND_KINDS else 0),
        "recheck": recheck,
        "findings": shown,
        "changes": changes,
        "root_causes": list(root_causes) if kind in ("holistic", "ruling", ask) else [],
        "unclear": list(unclear) if kind == "clarify" else [],
        "held": held,
        "waiting": waiting,
        "settled": sorted(fid for fid, e in after.items() if e["state"] in SETTLED_STATES),
    }


def inline_eligible(findings: list[dict], raised_reach: set[str]) -> bool:
    """Whether the orchestrator may fix a step's findings itself, if the
    user chooses: there are some, and each is one site (reach local, not
    raised by the coder) of S3 or less, neither a gate's nor an intent
    not-met. Anything bigger keeps its coder."""
    return bool(findings) and not raised_reach and all(
        f.get("reach") == "local" and (f.get("severity") or SERIOUS) <= INLINE_MAX_SEVERITY
        and not f.get("gate") and not f.get("not_met") for f in findings)


def _shown(fid: str, entry: dict, tier_name: str) -> dict:
    data = entry.get("data") or {}
    return {"id": fid, "tier": tier_name, "rule": data.get("rule", ""),
            "source": data.get("source", ""), "severity": data.get("severity", SERIOUS),
            "gate": bool(data.get("gate"))}


def _recheck(kind: str, sent: list[dict]) -> str:
    """Who re-checks a task's step: the raisers of every finding sent after
    a patch or a ruling (just the gate, when only gate findings were sent),
    the spec reviewer after a ruling that sent no finding (an overridden
    behavior choice), every reviewer after a holistic round, nobody
    otherwise. Notes are never re-checked."""
    if kind == "holistic":
        return "all"
    if kind in ("patch", "ruling"):
        if not sent:
            return "spec"
        return "gate" if all(f.get("gate") for f in sent) else "raising"
    return "none"
