"""Unit tests for safety filters and validation invariants (core/safety.py)."""

import pytest
from core.safety import (
    DISCLAIMER_TEXT,
    review_safety,
    sanitize_text,
)


def test_banned_phrases_removed_or_rewritten():
    """Acceptance Check 1: Banned phrases are removed or rewritten."""
    # 1. Prohibited diagnosis assertion: "you have <disease>"
    text_diag = "Based on our review, you have tuberculosis and you suffer from chronic fever."
    sanitized_diag = sanitize_text(text_diag)
    assert "you have" not in sanitized_diag.lower()
    assert "you suffer from" not in sanitized_diag.lower()
    assert "may be consistent with" in sanitized_diag.lower()

    # 2. Prohibited doctor opposition: "your doctor is wrong"
    text_opp = "Your doctor is wrong about the diagnosis of a routine cold."
    sanitized_opp = sanitize_text(text_opp)
    assert "your doctor is wrong" not in sanitized_opp.lower()
    assert "not fully explained by the current diagnosis" in sanitized_opp.lower()

    # 3. Prohibited medication cessation: "stop taking your medicine"
    text_med = "You should stop taking your amoxicillin immediately."
    sanitized_med = sanitize_text(text_med)
    assert "stop taking" not in sanitized_med.lower()
    assert "doctor or pharmacist" in sanitized_med.lower()

    # 4. Prohibited dosage prescription: "take 500mg daily"
    text_dose = "We recommend you take 500mg daily for relief."
    sanitized_dose = sanitize_text(text_dose)
    assert "take 500mg" not in sanitized_dose.lower()
    assert "doctor or pharmacist" in sanitized_dose.lower()


def test_disclaimer_is_always_present_verbatim():
    """Acceptance Check 2: Disclaimer is always present and matches verbatim text."""
    raw_report = {
        "verdict": "AGREE",
        "summary": "Everything looks standard.",
        "why": [],
        "disclaimer": "Some custom inaccurate disclaimer.",
    }
    evidence_context = {
        "verdict_data": {"verdict": "AGREE", "urgency": "routine", "top_candidates": []},
    }

    reviewed = review_safety(raw_report, evidence_context)
    assert reviewed["disclaimer"] == DISCLAIMER_TEXT


def test_urgency_always_matches_rule_engine():
    """Acceptance Check 4: Urgency always matches the rule engine, regardless of LLM output."""
    # Case where LLM tried to output "routine", but rule engine found critical alert ("urgent")
    raw_report_downgrade_attempt = {
        "verdict": "ESCALATE",
        "summary": "Evaluation recommended.",
        "urgency": "routine",  # Discrepant LLM output
        "specialist_to_consult": "Pulmonologist",
        "tests_to_confirm": ["Chest X-ray"],
    }
    evidence_context = {
        "verdict_data": {
            "verdict": "ESCALATE",
            "urgency": "urgent",  # True rule engine urgency
            "top_candidates": [{"name": "tuberculosis", "specialist": "Pulmonologist"}],
        },
    }

    reviewed = review_safety(raw_report_downgrade_attempt, evidence_context)
    assert reviewed["urgency"] == "urgent"
    assert reviewed["verdict"] == "ESCALATE"
