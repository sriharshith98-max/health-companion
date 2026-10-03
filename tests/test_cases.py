"""End-to-end integration tests for Demo Cases 1, 2, and 3 (tests/test_cases.py).

Verifies SPEC.md Section 6 demo cases against the complete verification pipeline.
"""

import pytest
from core.pipeline import verify
from core.safety import DISCLAIMER_TEXT

REQUIRED_FINAL_REPORT_KEYS = {
    "verdict",
    "summary",
    "why",
    "possible_conditions",
    "tests_to_confirm",
    "specialist_to_consult",
    "prescription_notes",
    "warning_signs",
    "questions_for_doctor",
    "urgency",
    "disclaimer",
}


def test_case_1_viral_fever_agree():
    """Demo Case 1: Viral fever (expected: AGREE, routine).

    - 28 F. Sore throat, mild fever, runny nose, 2 days.
    - Doctor: 'viral upper respiratory infection'. Rx: paracetamol, rest, fluids.
    - Expected: AGREE, routine, warning signs listed.
    """
    patient_input = {
        "age": 28,
        "sex": "Female",
        "symptoms_text": "Sore throat, mild fever, runny nose",
        "duration_days": 2,
        "doctor_dx": "viral upper respiratory infection",
        "reports": [],
        "prescription": "Tab. Paracetamol 650 mg SOS, rest, oral fluids",
    }

    report = verify(patient_input)

    # Schema validation
    assert REQUIRED_FINAL_REPORT_KEYS.issubset(report.keys())
    assert report["verdict"] == "AGREE"
    assert report["urgency"] == "routine"
    assert report["disclaimer"] == DISCLAIMER_TEXT
    assert len(report["warning_signs"]) > 0
    assert len(report["questions_for_doctor"]) > 0
    # No diagnosis assertions
    assert "you have" not in report["summary"].lower()


def test_case_2_prolonged_cough_escalate():
    """Demo Case 2: Prolonged cough (expected: ESCALATE, Pulmonologist, soon).

    - 34 M. Cough 3 weeks, evening fever, night sweats, weight loss.
    - Doctor: 'regular infection'. Rx: antibiotic course (Amoxicillin 500mg).
    - Labs: ESR high (45 mm/hr).
    - Expected: ESCALATE, tuberculosis among top candidates, tests: chest X-ray, sputum AFB/CBNAAT, CBC/ESR. Specialist: Pulmonologist. Urgency: soon.
    """
    patient_input = {
        "age": 34,
        "sex": "Male",
        "symptoms_text": "Cough for 3 weeks, evening fever, night sweats, unexplained weight loss",
        "duration_days": 21,
        "doctor_dx": "regular infection",
        "reports": [
            "CLINICAL LABORATORY REPORT\nHemoglobin: 11.8 g/dL (13.5 - 17.5)\nESR: 45 mm/hr (0 - 15)\nPlatelet Count: 280000 /cumm\n"
        ],
        "prescription": "Tab. Amoxicillin 500 mg TID for 5 days",
    }

    report = verify(patient_input)

    # Schema validation
    assert REQUIRED_FINAL_REPORT_KEYS.issubset(report.keys())
    assert report["verdict"] == "ESCALATE"
    assert report["urgency"] in ("soon", "urgent")
    assert report["disclaimer"] == DISCLAIMER_TEXT

    # Verify specialist referral
    assert "Pulmonologist" in report["specialist_to_consult"]

    # Verify confirmatory tests include X-ray or Sputum
    tests_str = " ".join(report["tests_to_confirm"]).lower()
    assert "chest x-ray" in tests_str or "x-ray" in tests_str or "sputum" in tests_str

    # Verify candidate conditions include Tuberculosis
    cand_names = [c["name"].lower() for c in report["possible_conditions"]]
    assert any("tuberculosis" in name for name in cand_names)

    # Verify safety framing
    assert "you have" not in report["summary"].lower()
    assert "your doctor is wrong" not in report["summary"].lower()


def test_case_3_fatigue_and_thirst_escalate():
    """Demo Case 3: Fatigue and thirst (expected: ESCALATE, Endocrinologist, soon).

    - 45 M. Fatigue, excessive thirst, frequent urination, slow-healing wound, 6 weeks.
    - Doctor: 'weakness, vitamin deficiency'. Rx: multivitamins.
    - Labs: fasting glucose 138 mg/dL, hemoglobin 12.
    - Expected: ESCALATE, diabetes among top candidates, tests: fasting glucose, HbA1c, post-meal glucose. Specialist: Endocrinologist or General Physician.
    """
    patient_input = {
        "age": 45,
        "sex": "Male",
        "symptoms_text": "Fatigue, excessive thirst, frequent urination, slow-healing cut on foot for 6 weeks",
        "duration_days": 42,
        "doctor_dx": "weakness, vitamin deficiency",
        "reports": [
            "BIOCHEMISTRY REPORT\nFasting Blood Sugar: 138 mg/dL (70 - 99)\nHemoglobin: 12.0 g/dL (13.0 - 17.5)\n"
        ],
        "prescription": "Cap. Multivitamins once daily",
    }

    report = verify(patient_input)

    # Schema validation
    assert REQUIRED_FINAL_REPORT_KEYS.issubset(report.keys())
    assert report["verdict"] == "ESCALATE"
    assert report["urgency"] in ("soon", "urgent")
    assert report["disclaimer"] == DISCLAIMER_TEXT

    # Verify specialist referral
    assert "Endocrinologist" in report["specialist_to_consult"] or "Diabetologist" in report["specialist_to_consult"]

    # Verify candidate conditions include Diabetes
    cand_names = [c["name"].lower() for c in report["possible_conditions"]]
    assert any("diabetes" in name for name in cand_names)

    # Verify confirmatory tests include HbA1c or Glucose
    tests_str = " ".join(report["tests_to_confirm"]).lower()
    assert "hba1c" in tests_str or "glucose" in tests_str or "fpg" in tests_str
