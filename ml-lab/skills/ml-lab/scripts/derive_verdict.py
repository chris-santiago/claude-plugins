# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Deterministic verdict derivation for ml-lab debate protocol.

Reads a defender rebuttal JSON object from stdin, applies derive_verdict()
rules, and writes the verdict JSON to stdout.

Usage (from ml-lab.md orchestrator):
    echo '<defender_json>' | uv run derive_verdict.py

Input shape:
    {
      "rebuttals": [
        {
          "finding_id": "F1",
          "rebuttal_type": "REBUT-DESIGN",
          "original_severity": 8,
          "adjusted_severity": 4
        },
        ...
      ]
    }

Output shape:
    {
      "point_verdicts": [
        {
          "finding_id": "F1",
          "adjusted_severity": 4,
          "rebuttal_type": "REBUT-DESIGN",
          "point_verdict": "empirical_test_agreed",
          "rule_applied": "..."
        }
      ],
      "case_verdict": "empirical_test_agreed",
      "case_rationale": "..."
    }

Implementation must stay in sync with:
  - experiments/self_debate_experiment_v8/tests/test_derive_verdict.py
  - The ml-lab.md Stage B.3 rules table (documentation only — this script is authoritative)

DO NOT add the FATAL DEFER backstop (DEFER + orig_sev >= 7 + adj_sev >= 6 → critique_wins).
It was reverted after canary_run3 catastrophe. The correct mechanism is question 4
in the defender prompts.
"""

import json
import sys


def derive_verdict(defender_output: dict) -> dict:
    """
    Deterministic verdict derivation from defender rebuttal output.

    Rules (applied per finding):
      1. adj_sev <= 3                        → defense_wins  (regardless of type)
      2. CONCEDE + adj_sev > 3               → critique_wins
      3. DEFER + adj_sev > 3                 → empirical_test_agreed
      4. REBUT* + adj_sev >= 7               → empirical_test_agreed  (high residual)
      5. REBUT* + orig_sev >= 7 + adj_sev 4-6 → empirical_test_agreed (FATAL not cleared)
      6. REBUT* + orig_sev < 7 + adj_sev <= 6 → defense_wins
      7. unknown rebuttal_type               → critique_wins  (conservative)

    Constitutional overrides (applied after main rules):
      CONCEDE + adj_sev >= 7  → critique_wins
      DEFER   + adj_sev <= 3  → defense_wins

    Case aggregation: critique_wins > empirical_test_agreed > defense_wins
    """
    rebuttals = defender_output.get("rebuttals", [])
    point_verdicts = []

    for rb in rebuttals:
        adj_sev = rb.get("adjusted_severity", 0)
        orig_sev = rb.get("original_severity", adj_sev)
        rtype = rb.get("rebuttal_type", "CONCEDE")
        fid = rb.get("finding_id", "?")

        if adj_sev <= 3:
            pv = "defense_wins"
            rule = f"adj_sev={adj_sev} ≤ 3 → defense_wins"
        elif rtype == "CONCEDE":
            pv = "critique_wins"
            rule = f"adj_sev={adj_sev}, CONCEDE → critique_wins"
        elif rtype == "DEFER":
            pv = "empirical_test_agreed"
            rule = f"adj_sev={adj_sev}, DEFER → empirical_test_agreed"
        elif rtype.startswith("REBUT") or rtype == "EXONERATE":
            if adj_sev >= 7:
                pv = "empirical_test_agreed"
                rule = f"adj_sev={adj_sev} ≥ 7, {rtype} → empirical_test_agreed (high residual)"
            elif orig_sev >= 7:
                pv = "empirical_test_agreed"
                rule = (f"adj_sev={adj_sev} (4-6), orig_sev={orig_sev} ≥ 7, {rtype} → "
                        f"empirical_test_agreed (FATAL not fully cleared)")
            else:
                pv = "defense_wins"
                rule = f"adj_sev={adj_sev}, orig_sev={orig_sev} < 7, {rtype} → defense_wins"
        else:
            pv = "critique_wins"
            rule = f"adj_sev={adj_sev}, unknown rebuttal_type={rtype} → critique_wins (conservative)"

        # Constitutional overrides
        if rtype == "CONCEDE" and adj_sev >= 7:
            pv = "critique_wins"
            rule = f"constitutional: CONCEDE + adj_sev={adj_sev} ≥ 7 → critique_wins"
        elif rtype == "DEFER" and adj_sev <= 3:
            pv = "defense_wins"
            rule = f"constitutional: DEFER + adj_sev={adj_sev} ≤ 3 → defense_wins"

        point_verdicts.append({
            "finding_id": fid,
            "adjusted_severity": adj_sev,
            "rebuttal_type": rtype,
            "point_verdict": pv,
            "rule_applied": rule,
        })

    if any(pv["point_verdict"] == "critique_wins" for pv in point_verdicts):
        n = sum(1 for pv in point_verdicts if pv["point_verdict"] == "critique_wins")
        case_verdict = "critique_wins"
        rationale = f"{n} point(s) reached critique_wins"
    elif any(pv["point_verdict"] == "empirical_test_agreed" for pv in point_verdicts):
        n = sum(1 for pv in point_verdicts if pv["point_verdict"] == "empirical_test_agreed")
        case_verdict = "empirical_test_agreed"
        rationale = f"{n} point(s) deferred; no critique_wins"
    else:
        case_verdict = "defense_wins"
        rationale = "all points resolved to defense_wins" if point_verdicts else "no advancing findings"

    return {
        "point_verdicts": point_verdicts,
        "case_verdict": case_verdict,
        "case_rationale": rationale,
    }


if __name__ == "__main__":
    try:
        defender_output = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}), file=sys.stderr)
        sys.exit(1)

    result = derive_verdict(defender_output)
    print(json.dumps(result, indent=2))
