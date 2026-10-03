"""Unit tests for the condition matcher and verdict engine (core/matcher.py)."""

import pytest
from core.matcher import extract_signals, match_conditions


def test_viral_fever_case_agrees():
    """Acceptance Check 1: Viral fever case -> AGREE."""
    # Case 1: 28 F. Sore throat, mild fever, runny nose, 2 days.
    # Doctor: "viral upper respiratory infection"
    symptoms = {
        "symptoms": ["sore throat", "mild fever", "runny nose"],
        "duration_days": 2,
        "flags": {
            "fever": True,
            "weight_loss": False,
            "night_sweats": False,
            "blood_in_sputum": False,
            "cough_gt_14d": False,
            "breathlessness": False,
            "chest_pain": False,
        },
    }
    flagged_labs = []
    doctor_dx = "viral upper respiratory infection"

    signals = extract_signals(symptoms, flagged_labs)
    result = match_conditions(signals, doctor_dx, flagged_labs, symptoms)

    assert result["verdict"] == "AGREE"
    assert result["urgency"] == "routine"
    assert result["doctor_dx_matched"] == "viral_upper_respiratory_infection"
    assert len(result["top_candidates"]) > 0
    assert result["top_candidates"][0]["name"] == "viral_upper_respiratory_infection"


def test_tb_pattern_case_escalates():
    """Acceptance Check 2: TB-pattern case with 'regular infection' dx -> ESCALATE, specialist = Pulmonologist."""
    # Case 2: 34 M. Cough 3 weeks, evening fever, night sweats, weight loss.
    # Doctor: "regular infection". Labs: ESR high.
    symptoms = {
        "symptoms": ["cough", "evening fever", "night sweats", "weight loss"],
        "duration_days": 21,
        "flags": {
            "fever": True,
            "weight_loss": True,
            "night_sweats": True,
            "blood_in_sputum": False,
            "cough_gt_14d": True,
            "breathlessness": False,
            "chest_pain": False,
        },
    }
    flagged_labs = [
        {
            "test": "ESR",
            "normalized_test": "esr",
            "value": 45.0,
            "unit": "mm/hr",
            "status": "HIGH",
            "is_critical": False,
        }
    ]
    doctor_dx = "regular infection"

    signals = extract_signals(symptoms, flagged_labs)
    result = match_conditions(signals, doctor_dx, flagged_labs, symptoms)

    assert result["verdict"] == "ESCALATE"
    assert result["urgency"] in ("soon", "urgent")
    assert len(result["top_candidates"]) > 0

    top_candidate = result["top_candidates"][0]
    assert top_candidate["name"] == "tuberculosis"
    assert "Pulmonologist" in top_candidate["specialist"]
    assert "Chest X-ray" in top_candidate["confirmatory_tests"]

    # Verify unexplained findings list night sweats, weight loss, etc.
    assert len(result["unexplained_findings"]) > 0
    assert any("night sweats" in u.lower() for u in result["unexplained_findings"])


def test_diabetes_pattern_case_escalates():
    """Acceptance Check 3: Diabetes-pattern case -> ESCALATE, specialist = Endocrinologist."""
    # Case 3: 45 M. Fatigue, excessive thirst, frequent urination, slow-healing wound, 6 weeks.
    # Doctor: "weakness, vitamin deficiency". Labs: fasting glucose 138 mg/dL.
    symptoms = {
        "symptoms": ["fatigue", "excessive thirst", "frequent urination", "slow-healing wound"],
        "duration_days": 42,
        "flags": {
            "fever": False,
            "weight_loss": False,
            "night_sweats": False,
            "blood_in_sputum": False,
            "cough_gt_14d": False,
            "fatigue": True,
            "thirst": True,
            "frequent_urination": True,
        },
    }
    flagged_labs = [
        {
            "test": "Fasting Blood Sugar",
            "normalized_test": "fasting_glucose",
            "value": 138.0,
            "unit": "mg/dL",
            "status": "HIGH",
            "is_critical": False,
        }
    ]
    doctor_dx = "weakness, vitamin deficiency"

    signals = extract_signals(symptoms, flagged_labs)
    result = match_conditions(signals, doctor_dx, flagged_labs, symptoms)

    assert result["verdict"] == "ESCALATE"
    top_candidate = result["top_candidates"][0]
    assert top_candidate["name"] == "diabetes"
    assert "Endocrinologist" in top_candidate["specialist"]
    assert "HbA1c (Glycated Hemoglobin)" in top_candidate["confirmatory_tests"]


def test_sparse_input_inconclusive():
    """Acceptance Check 4: Sparse input -> INCONCLUSIVE."""
    symptoms = {
        "symptoms": ["mild headache"],
        "duration_days": 1,
        "flags": {
            "headache": True,
            "fever": False,
            "weight_loss": False,
            "night_sweats": False,
            "blood_in_sputum": False,
            "cough_gt_14d": False,
        },
    }
    flagged_labs = []
    doctor_dx = "tension headache"

    signals = extract_signals(symptoms, flagged_labs)
    result = match_conditions(signals, doctor_dx, flagged_labs, symptoms)

    assert result["verdict"] == "INCONCLUSIVE"


def test_urgent_trigger_sets_urgency_urgent():
    """Acceptance Check 5: Urgent trigger sets urgency = 'urgent'."""
    # Test symptom urgent trigger: blood in sputum
    symptoms_urgent = {
        "symptoms": ["cough", "blood in sputum"],
        "duration_days": 5,
        "flags": {
            "blood_in_sputum": True,
            "fever": False,
            "weight_loss": False,
            "night_sweats": False,
            "cough_gt_14d": False,
        },
    }
    signals_urgent = extract_signals(symptoms_urgent, [])
    res_urgent = match_conditions(signals_urgent, "bronchitis", [], symptoms_urgent)
    assert res_urgent["urgency"] == "urgent"

    # Test critical lab trigger: platelet count = 25,000 (critical dengue / thrombocytopenia)
    symptoms_fever = {
        "symptoms": ["high fever", "body ache"],
        "duration_days": 3,
        "flags": {"fever": True, "joint_pain": True},
    }
    critical_lab = [
        {
            "test": "Platelet Count",
            "normalized_test": "platelets",
            "value": 25000.0,
            "unit": "/cumm",
            "status": "CRITICAL",
            "is_critical": True,
        }
    ]
    signals_fever = extract_signals(symptoms_fever, critical_lab)
    res_crit_lab = match_conditions(signals_fever, "viral fever", critical_lab, symptoms_fever)
    assert res_crit_lab["urgency"] == "urgent"
