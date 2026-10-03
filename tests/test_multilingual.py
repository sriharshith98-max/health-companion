"""Unit and integration tests for Multilingual Output (Step 13.1).

Tests English, Telugu, and Hindi translations, disclaimers, and pipeline integration.
"""

import pytest

from core.pipeline import verify
from core.report import generate_grounded_report_fallback, generate_report
from core.safety import DISCLAIMER_MAP, DISCLAIMER_TEXT, review_safety


def test_disclaimer_map_entries():
    """Verify that DISCLAIMER_MAP contains English, Telugu, and Hindi disclaimers."""
    assert "English" in DISCLAIMER_MAP
    assert "Telugu" in DISCLAIMER_MAP
    assert "Hindi" in DISCLAIMER_MAP

    assert DISCLAIMER_MAP["English"] == DISCLAIMER_TEXT
    assert "ఈ సాధనం సాధారణ ఆరోగ్య సమాచారాన్ని అందిస్తుంది" in DISCLAIMER_MAP["Telugu"]
    assert "यह उपकरण सामान्य स्वास्थ्य जानकारी प्रदान करता है" in DISCLAIMER_MAP["Hindi"]


def test_safety_review_respects_language():
    """Verify review_safety injects the appropriate localized disclaimer."""
    sample_report = {
        "verdict": "AGREE",
        "urgency": "routine",
        "summary": "Sample summary",
        "specialist_to_consult": "General Physician",
    }
    evidence_context_telugu = {
        "verdict_data": {"verdict": "AGREE", "urgency": "routine"},
        "patient_input": {"language": "Telugu"},
    }
    evidence_context_hindi = {
        "verdict_data": {"verdict": "AGREE", "urgency": "routine"},
        "patient_input": {"language": "Hindi"},
    }
    evidence_context_english = {
        "verdict_data": {"verdict": "AGREE", "urgency": "routine"},
        "patient_input": {"language": "English"},
    }

    res_te = review_safety(sample_report, evidence_context_telugu)
    assert res_te["disclaimer"] == DISCLAIMER_MAP["Telugu"]

    res_hi = review_safety(sample_report, evidence_context_hindi)
    assert res_hi["disclaimer"] == DISCLAIMER_MAP["Hindi"]

    res_en = review_safety(sample_report, evidence_context_english)
    assert res_en["disclaimer"] == DISCLAIMER_MAP["English"]


def test_fallback_report_telugu():
    """Verify generate_grounded_report_fallback outputs Telugu text when requested."""
    verdict_data = {
        "verdict": "ESCALATE",
        "urgency": "same_day",
        "top_candidates": [
            {
                "name": "tuberculosis",
                "score": 0.8,
                "evidence": ["cough > 3 weeks", "night chills"],
                "specialist": "Pulmonologist",
                "confirmatory_tests": ["Chest X-Ray"],
            }
        ],
        "unexplained_findings": ["cough duration 21 days"],
    }
    patient_input = {
        "age": 42,
        "sex": "Male",
        "duration_days": 21,
        "doctor_dx": "regular bronchitis",
        "symptoms_text": "persistent cough for 3 weeks",
        "language": "Telugu",
    }

    report = generate_grounded_report_fallback(verdict_data, patient_input, [], [])

    assert report["verdict"] == "ESCALATE"
    assert report["urgency"] == "same_day"
    assert report["disclaimer"] == DISCLAIMER_MAP["Telugu"]
    assert "నిర్ధారణ" in report["summary"] or "క్లినికల్" in report["summary"]
    # Check warning signs in Telugu
    assert any("శ్వాస" in w for w in report["warning_signs"])
    assert any("దగ్గులో రక్తం" in w for w in report["warning_signs"])


def test_fallback_report_hindi():
    """Verify generate_grounded_report_fallback outputs Hindi text when requested."""
    verdict_data = {
        "verdict": "AGREE",
        "urgency": "routine",
        "top_candidates": [
            {
                "name": "viral_upper_respiratory",
                "score": 0.7,
                "evidence": ["runny nose", "sore throat"],
                "specialist": "General Physician",
                "confirmatory_tests": ["Clinical Observation"],
            }
        ],
        "unexplained_findings": [],
    }
    patient_input = {
        "age": 28,
        "sex": "Female",
        "duration_days": 3,
        "doctor_dx": "viral infection",
        "symptoms_text": "runny nose, sore throat for 3 days",
        "language": "Hindi",
    }

    report = generate_grounded_report_fallback(verdict_data, patient_input, [], [])

    assert report["verdict"] == "AGREE"
    assert report["urgency"] == "routine"
    assert report["disclaimer"] == DISCLAIMER_MAP["Hindi"]
    assert "निष्कर्ष और नैदानिक साक्ष्य" in report["summary"]
    # Check warning signs in Hindi
    assert any("सांस लेने में कठिनाई" in w for w in report["warning_signs"])


def test_verify_pipeline_telugu_end_to_end():
    """Verify complete verify() pipeline with Telugu language input."""
    patient_input = {
        "age": 28,
        "sex": "Female",
        "symptoms_text": "Fever, headache, chills for 3 days",
        "duration_days": 3,
        "doctor_dx": "viral fever",
        "language": "Telugu",
    }
    report = verify(patient_input)

    assert report["verdict"] in ("AGREE", "ESCALATE", "INCONCLUSIVE")
    assert report["disclaimer"] == DISCLAIMER_MAP["Telugu"]
    assert "summary" in report
    assert isinstance(report["warning_signs"], list)
    assert len(report["warning_signs"]) > 0


def test_verify_pipeline_hindi_end_to_end():
    """Verify complete verify() pipeline with Hindi language input."""
    patient_input = {
        "age": 45,
        "sex": "Male",
        "symptoms_text": "Cough for 4 weeks with evening fever and weight loss",
        "duration_days": 28,
        "doctor_dx": "simple cold",
        "language": "Hindi",
    }
    report = verify(patient_input)

    assert report["verdict"] == "ESCALATE"
    assert report["disclaimer"] == DISCLAIMER_MAP["Hindi"]
    assert "summary" in report
    assert isinstance(report["questions_for_doctor"], list)
    assert len(report["questions_for_doctor"]) > 0
