# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest"]
# ///
"""
Faithfulness tests for derive_verdict() — Phase 1 port validation.

Tests encode v8's final verdict logic as executable specifications.
No API calls — pure logic. Self-contained: includes the implementation
so tests work standalone in both:
  - experiments/self_debate_experiment_v8/tests/  (development)
  - plugins/ml-lab/tests/                         (post-port)

Run with: uv run --with pytest pytest test_derive_verdict.py -v

The implementation below must stay in sync with:
  - experiments/self_debate_experiment_v8/scripts/run_multiround.py derive_verdict()
  - The ported ml-lab orchestration logic

If you change derive_verdict() rules, update both the implementation
and the corresponding test docstrings to reflect the new intended behavior.
"""


# ── Reference implementation (ported from run_multiround.py) ─────────────────

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

    NOTE: DEFER + orig_sev >= 7 + adj_sev >= 6 → critique_wins backstop
    was tested in canary_run3 and reverted. DO NOT add it back.
    The correct mechanism is question 4 at the prompt level.

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_output(*rebuttals):
    """Build a minimal defender_output dict.

    Each tuple: (finding_id, rebuttal_type, original_severity, adjusted_severity)
    """
    return {
        "rebuttals": [
            {
                "finding_id": fid,
                "rebuttal_type": rtype,
                "original_severity": orig_sev,
                "adjusted_severity": adj_sev,
            }
            for fid, rtype, orig_sev, adj_sev in rebuttals
        ]
    }


def case_verdict(output):
    return derive_verdict(output)["case_verdict"]


def point_verdicts(output):
    return {pv["finding_id"]: pv["point_verdict"]
            for pv in derive_verdict(output)["point_verdicts"]}


# ── Section 1: adj_sev ≤ 3 floor ─────────────────────────────────────────────

class TestAdjSevFloor:
    """adj_sev ≤ 3 → defense_wins regardless of rebuttal_type."""

    def test_concede_adj3(self):
        out = make_output(("F1", "CONCEDE", 8, 3))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_defer_adj3(self):
        # Constitutional override: DEFER + adj_sev <= 3 → defense_wins, not ETA
        out = make_output(("F1", "DEFER", 7, 3))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_rebut_design_adj3(self):
        out = make_output(("F1", "REBUT-DESIGN", 8, 3))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_rebut_adj0(self):
        out = make_output(("F1", "REBUT-EVIDENCE", 9, 0))
        assert point_verdicts(out)["F1"] == "defense_wins"


# ── Section 2: CONCEDE ────────────────────────────────────────────────────────

class TestConcede:
    """CONCEDE + adj_sev > 3 → critique_wins."""

    def test_concede_adj4(self):
        out = make_output(("F1", "CONCEDE", 5, 4))
        assert point_verdicts(out)["F1"] == "critique_wins"

    def test_concede_adj7_constitutional(self):
        """Constitutional: CONCEDE + adj_sev >= 7 → critique_wins."""
        out = make_output(("F1", "CONCEDE", 9, 7))
        assert point_verdicts(out)["F1"] == "critique_wins"

    def test_concede_adj8(self):
        out = make_output(("F1", "CONCEDE", 9, 8))
        assert point_verdicts(out)["F1"] == "critique_wins"


# ── Section 3: DEFER ──────────────────────────────────────────────────────────

class TestDefer:
    """DEFER + adj_sev > 3 → empirical_test_agreed."""

    def test_defer_adj5(self):
        out = make_output(("F1", "DEFER", 8, 5))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_defer_adj7(self):
        out = make_output(("F1", "DEFER", 9, 7))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_defer_adj4_fatal_orig(self):
        """DEFER on FATAL finding at adj_sev=4 → ETA (not backstop)."""
        out = make_output(("F1", "DEFER", 8, 4))
        # DO NOT add backstop: orig_sev>=7 + adj_sev>=6 → critique_wins was reverted.
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_defer_adj6_fatal_orig(self):
        """DEFER + orig_sev>=7 + adj_sev=6 → ETA (backstop DO NOT PORT)."""
        out = make_output(("F1", "DEFER", 8, 6))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"


# ── Section 4: REBUT* rules ───────────────────────────────────────────────────

class TestRebutFatalNotFullyCleared:
    """REBUT* + orig_sev >= 7 + adj_sev 4-6 → empirical_test_agreed."""

    def test_rebut_design_fatal_adj4(self):
        out = make_output(("F1", "REBUT-DESIGN", 8, 4))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_rebut_scope_fatal_adj6(self):
        out = make_output(("F1", "REBUT-SCOPE", 7, 6))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_rebut_evidence_fatal_adj5(self):
        out = make_output(("F1", "REBUT-EVIDENCE", 9, 5))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"


class TestRebutHighResidual:
    """REBUT* + adj_sev >= 7 → empirical_test_agreed (high residual)."""

    def test_rebut_design_adj7(self):
        out = make_output(("F1", "REBUT-DESIGN", 9, 7))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_rebut_evidence_adj8(self):
        out = make_output(("F1", "REBUT-EVIDENCE", 9, 8))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"


class TestRebutMaterialCleared:
    """REBUT* + orig_sev < 7 + adj_sev <= 6 → defense_wins."""

    def test_rebut_design_material_adj4(self):
        out = make_output(("F1", "REBUT-DESIGN", 5, 4))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_rebut_scope_minor_adj2(self):
        out = make_output(("F1", "REBUT-SCOPE", 3, 2))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_rebut_immaterial_minor(self):
        out = make_output(("F1", "REBUT-IMMATERIAL", 2, 1))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_exonerate_adj2(self):
        out = make_output(("F1", "EXONERATE", 5, 2))
        assert point_verdicts(out)["F1"] == "defense_wins"


# ── Section 5: Case-level aggregation ────────────────────────────────────────

class TestCaseLevelAggregation:
    """critique_wins > empirical_test_agreed > defense_wins."""

    def test_one_critique_wins_beats_defense(self):
        out = make_output(
            ("F1", "CONCEDE", 8, 8),
            ("F2", "REBUT-DESIGN", 3, 2),
            ("F3", "REBUT-DESIGN", 4, 3),
        )
        assert case_verdict(out) == "critique_wins"

    def test_one_eta_beats_defense(self):
        out = make_output(
            ("F1", "DEFER", 7, 5),
            ("F2", "REBUT-DESIGN", 3, 2),
        )
        assert case_verdict(out) == "empirical_test_agreed"

    def test_critique_wins_beats_eta(self):
        out = make_output(
            ("F1", "CONCEDE", 8, 5),
            ("F2", "DEFER", 7, 5),
        )
        assert case_verdict(out) == "critique_wins"

    def test_all_defense(self):
        out = make_output(
            ("F1", "REBUT-DESIGN", 6, 3),
            ("F2", "REBUT-SCOPE", 4, 2),
            ("F3", "REBUT-IMMATERIAL", 2, 1),
        )
        assert case_verdict(out) == "defense_wins"

    def test_two_critique_wins_counted_in_rationale(self):
        out = make_output(
            ("F1", "CONCEDE", 8, 8),
            ("F2", "CONCEDE", 7, 7),
            ("F3", "REBUT-DESIGN", 5, 3),
        )
        result = derive_verdict(out)
        assert result["case_verdict"] == "critique_wins"
        assert "2 point(s)" in result["case_rationale"]


# ── Section 6: Short-circuit ──────────────────────────────────────────────────

class TestShortCircuit:
    """Empty rebuttals → defense_wins (no advancing findings)."""

    def test_empty_rebuttals(self):
        out = {"rebuttals": []}
        assert case_verdict(out) == "defense_wins"
        result = derive_verdict(out)
        assert result["case_rationale"] == "no advancing findings"

    def test_missing_rebuttals_key(self):
        out = {}
        assert case_verdict(out) == "defense_wins"


# ── Section 7: v8 faithfulness checklist ─────────────────────────────────────

class TestV8Faithfulness:
    """
    Specific v8 calibration findings encoded as non-regression specs.
    Each test documents a concrete finding from the canary runs or Sonnet probe.
    """

    def test_fatal_rebut_to_adj4_is_eta_not_defense(self):
        """
        FATAL finding (orig >= 7) rebutted to adj 4-6 → ETA, not defense_wins.
        Rule: FATAL not fully cleared. Partial REBUT on FATAL signals real uncertainty.
        Sourced from: Opus 852 probe — REBUT-EVIDENCE on F1 (adj=4) with orig=8.
        """
        out = make_output(("F1", "REBUT-EVIDENCE", 8, 4))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_defer_adj3_constitutional_defense(self):
        """
        DEFER on a finding the debate resolved to low severity → defense_wins.
        Constitutional override prevents DEFER from producing ETA on minor concerns.
        """
        out = make_output(("F1", "DEFER", 7, 2))
        assert point_verdicts(out)["F1"] == "defense_wins"

    def test_one_concede_fatal_beats_multiple_deferreds(self):
        """
        One undeniable FATAL CONCEDE overrides any number of valid DEFERs.
        Captures eval_scenario_812 Sonnet probe: F1 metric mismatch CONCEDE (adj=8)
        alongside other findings the defender could DEFER.
        """
        out = make_output(
            ("F1", "CONCEDE", 9, 8),
            ("F2", "DEFER", 7, 5),
            ("F3", "REBUT-SCOPE", 5, 3),
        )
        assert case_verdict(out) == "critique_wins"

    def test_backstop_not_implemented(self):
        """
        DEFER + orig_sev >= 7 + adj_sev >= 6 must NOT trigger critique_wins.
        The backstop was reverted after canary_run3 catastrophe — it over-fired
        on ETA cases (eval_scenario_862 went 3/3 critique_wins).
        The correct mechanism is question 4 at the prompt level.

        If this test fails, the backstop was re-added. Remove it.
        """
        out = make_output(("F1", "DEFER", 8, 6))
        assert point_verdicts(out)["F1"] == "empirical_test_agreed"

    def test_all_deferreds_case_is_eta_not_critique(self):
        """
        A case with all DEFERs (and adj_sev > 3) → ETA, not critique_wins.
        Captures Opus probe behavior: Opus 4.6 correctly DEFERred FATAL findings
        with valid 3-question settling experiments → ETA is the right verdict.
        """
        out = make_output(
            ("F1", "DEFER", 8, 5),
            ("F2", "DEFER", 7, 6),
            ("F3", "DEFER", 7, 5),
        )
        assert case_verdict(out) == "empirical_test_agreed"
