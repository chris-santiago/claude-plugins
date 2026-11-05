"""
triage.py — the per-task review-fix loop's routing rules, as pure functions.

`ledger.py triage` gathers the inputs from the store (reviewer findings with
their tags and flags, the coder record's evidence, the user's rulings, the
scope's earlier triage entries) and calls `derive`. Nothing here reads files,
runs git, or imports ledger: ledger.py runs as __main__, and a module that
imported it would load a second copy with its own RecordError.

A finding's tier comes from its severity and reach alone:

    S1-S2 local/class -> note       S1-S2 contract -> defer
    S3-S5 local/class -> patch      S3-S5 contract -> holistic

A coder's `root cause:` concern and a finding whose reach the coder raised
are holistic too. A contest the raising reviewer holds is held for the user.
`recurring` and `introduced_by_fix` never change a tier; they feed telemetry.
"""

from __future__ import annotations

SERIOUS = 3
MAX_FIX_ROUNDS = 2
FIX_ROUND_KINDS = ("patch", "holistic")
FIX_KINDS = ("patch", "holistic", "polish", "ruling")


def tier(finding: dict, reach_raised: set[str]) -> str:
    """note, defer, patch or holistic, from severity and (effective) reach."""
    contract = finding["reach"] == "contract" or finding["id"] in reach_raised
    if finding["severity"] < SERIOUS:
        return "defer" if contract else "note"
    return "holistic" if contract else "patch"


def _settled(prior: list[dict], waived: set[str], answers: dict[str, str]) -> set[str]:
    """Findings no longer anyone's work: waived by the user, conceded by the
    reviewer that raised them, or settled in an earlier entry."""
    earlier = {i for entry in prior for i in entry.get("settled", [])}
    conceded = {i for i, verdict in answers.items() if verdict == "concede"}
    return earlier | waived | conceded


def _held(prior: list[dict], answers: dict[str, str], settled: set[str],
          ruled: bool, raised: set[str]) -> set[str]:
    """Contests the raising reviewer held, while it still raises them,
    until the user waives them or a ruling takes them into a ruling round."""
    if ruled:
        return set()
    earlier = set(prior[-1].get("held", [])) if prior else set()
    held_now = {i for i, verdict in answers.items() if verdict == "hold"}
    return ((earlier | held_now) - settled) & raised


def _sent_notes(prior: list[dict]) -> set[str]:
    """Notes an earlier fix-kind round already handed to a coder. `check`
    holds the coder to fixing or skipping each, so they never reopen."""
    return {f["id"] for entry in prior if entry.get("kind") in FIX_KINDS
            for f in entry.get("findings", []) if f.get("tier") == "note"}


def _filed(prior: list[dict]) -> set[str]:
    return {i for entry in prior for i in entry.get("filed", [])}


def derive(*, findings: list[dict], root_causes: list[str], reach_raised: set[str],
           answers: dict[str, str], waived: set[str], prior: list[dict], ruled: bool,
           undelivered_note: bool, model: str | None,
           file_candidates: list[dict]) -> dict:
    """The next step for one scope, as a triage entry (without its type,
    task and tree, which the caller adds).

    `findings` are the reviewer and gate findings currently raised, each a
    dict with id, source, gate, severity, reach, rule, recurring and
    introduced. `root_causes` are the ids of the coder's open `root cause:`
    concerns. `answers` maps a contested finding id to the raising
    reviewer's verdict. `waived` are ids the user resolved. `prior` are the
    scope's earlier triage entries, oldest first. `ruled` says a user ruling
    was logged after the last escalate entry. `file_candidates` are coder
    deferrals (skipped notes, outside sites) as dicts with id and rule."""
    settled = _settled(prior, waived, answers)
    last_kind = prior[-1]["kind"] if prior else None
    ruling_now = ruled and last_kind == "escalate"
    held = _held(prior, answers, settled, ruling_now, {f["id"] for f in findings})
    live = [f for f in findings if f["id"] not in settled]
    tiers = {f["id"]: ("held" if f["id"] in held else tier(f, reach_raised)) for f in live}
    serious = [f for f in live if tiers[f["id"]] in ("patch", "holistic")]
    if ruling_now:
        earlier_held = set(prior[-1].get("held", [])) - settled
        serious += [f for f in live if f["id"] in earlier_held and f not in serious]
    notes = [f for f in live if tiers[f["id"]] == "note" and f["id"] not in _sent_notes(prior)]
    open_work = bool(serious or root_causes)
    rounds = sum(1 for e in prior if e.get("kind") in FIX_ROUND_KINDS)

    if open_work and ruling_now:
        kind, sent = "ruling", serious
    elif open_work and (rounds >= MAX_FIX_ROUNDS or last_kind == "ruling"):
        kind, sent = "escalate", serious
    elif open_work:
        holistic = bool(root_causes) or any(tiers[f["id"]] == "holistic" for f in serious)
        kind, sent = ("holistic" if holistic else "patch"), serious
    elif held:
        kind, sent = "escalate", []
    elif notes or undelivered_note:
        kind, sent = "polish", []
    else:
        kind, sent = "done", []

    if kind in ("patch", "holistic", "ruling", "polish"):
        sent = [*sent, *notes]
    sent_ids = {f["id"] for f in sent}
    already_filed = _filed(prior)
    defer = [{"id": f["id"], "rule": f["rule"]} for f in live
             if tiers[f["id"]] == "defer" and f["id"] not in already_filed]
    to_file = defer + [c for c in file_candidates if c["id"] not in already_filed]
    open_serious = [f for f in live if tiers[f["id"]] in ("patch", "holistic")]
    survived = sum(1 for f in open_serious if f.get("recurring"))
    previous_count = len(prior[-1].get("findings", [])) if prior else 0
    return {
        "kind": kind,
        "round": rounds + (1 if kind in FIX_ROUND_KINDS else 0),
        "recheck": _recheck(kind, sent),
        "findings": [{"id": f["id"], "tier": tiers[f["id"]], "rule": f["rule"],
                      "source": f["source"]} for f in live if f["id"] in sent_ids
                     or tiers[f["id"]] in ("defer", "held")],
        "root_causes": list(root_causes) if kind in ("holistic", "ruling", "escalate") else [],
        "held": sorted(held),
        "settled": sorted(settled),
        "filed": sorted(already_filed | {c["id"] for c in to_file}),
        "to_file": to_file,
        "model": model,
        "closed": max(previous_count - survived, 0) if prior else 0,
        "survived": survived,
        "introduced": sum(1 for f in open_serious if f.get("introduced")),
    }


def _recheck(kind: str, sent: list[dict]) -> str:
    """Who re-checks the step: the raising reviewers after a patch or a
    ruling (or just the gate, when only gate findings were sent), every
    reviewer after a holistic round, nobody otherwise."""
    if kind == "holistic":
        return "all"
    if kind in ("patch", "ruling"):
        serious = [f for f in sent if f["severity"] >= SERIOUS]
        return "gate" if serious and all(f.get("gate") for f in serious) else "raising"
    return "none"
