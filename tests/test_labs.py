"""Unit tests for lab normalization and flagging (core/labs.py)."""

import pytest
from core.labs import flag_values, normalize_test_name


def test_alias_normalization():
    """Verify standard clinical test aliases map to canonical identifiers."""
    assert normalize_test_name("Hb") == "hemoglobin"
    assert normalize_test_name("Hgb") == "hemoglobin"
    assert normalize_test_name("Total Leukocyte Count") == "wbc"
    assert normalize_test_name("TLC") == "wbc"
    assert normalize_test_name("Platelet Count") == "platelets"
    assert normalize_test_name("Plt") == "platelets"
    assert normalize_test_name("Fasting Blood Sugar") == "fasting_glucose"
    assert normalize_test_name("FBS") == "fasting_glucose"
    assert normalize_test_name("Serum Creatinine") == "creatinine"
    assert normalize_test_name("ESR") == "esr"


def test_unknown_test_flagged_with_report_own_range():
    """Acceptance Check 2: Unknown tests are still flagged using the report's own range."""
    lab_results = [
        {"test": "NovelBiomarkerX", "value": 25.0, "unit": "ng/mL", "ref_low": 10.0, "ref_high": 20.0},
        {"test": "NovelBiomarkerY", "value": 5.0, "unit": "ng/mL", "ref_low": 10.0, "ref_high": 20.0},
        {"test": "NovelBiomarkerZ", "value": 15.0, "unit": "ng/mL", "ref_low": 10.0, "ref_high": 20.0},
    ]

    flagged = flag_values(lab_results)
    assert len(flagged) == 3

    assert flagged[0]["status"] == "HIGH"
    assert flagged[0]["is_critical"] is False
    assert flagged[0]["effective_ref_high"] == 20.0

    assert flagged[1]["status"] == "LOW"
    assert flagged[1]["is_critical"] is False
    assert flagged[1]["effective_ref_low"] == 10.0

    assert flagged[2]["status"] == "NORMAL"
    assert flagged[2]["is_critical"] is False


def test_fallback_to_reference_file_when_report_range_missing():
    """Verify fallback to data/lab_reference.json when the report omits reference intervals."""
    lab_results = [
        {"test": "Hb", "value": 9.5, "unit": None, "ref_low": None, "ref_high": None},
        {"test": "ESR", "value": 45.0, "unit": None, "ref_low": None, "ref_high": None},
        {"test": "Platelets", "value": 250000.0, "unit": None, "ref_low": None, "ref_high": None},
    ]

    flagged = flag_values(lab_results)
    assert flagged[0]["normalized_test"] == "hemoglobin"
    assert flagged[0]["status"] == "LOW"  # 9.5 < 13.0
    assert flagged[0]["effective_ref_low"] == 13.0

    assert flagged[1]["normalized_test"] == "esr"
    assert flagged[1]["status"] == "HIGH"  # 45 > 15.0
    assert flagged[1]["effective_ref_high"] == 15.0

    assert flagged[2]["normalized_test"] == "platelets"
    assert flagged[2]["status"] == "NORMAL"  # 150000 <= 250000 <= 450000


def test_critical_threshold_sets_critical_marker():
    """Acceptance Check 3: Critical values set a critical marker and CRITICAL status."""
    critical_cases = [
        # Platelets < 50,000 (Dengue hemorrhagic / acute thrombocytopenia risk)
        {"test": "Platelet Count", "value": 25000.0, "unit": "/cumm", "ref_low": 150000.0, "ref_high": 450000.0},
        # Fasting Glucose > 400 mg/dL (DKA / HHS risk)
        {"test": "Fasting Blood Sugar", "value": 450.0, "unit": "mg/dL", "ref_low": 70.0, "ref_high": 99.0},
        # Hemoglobin < 7.0 g/dL (Severe anemia requiring transfusion evaluation)
        {"test": "Hb", "value": 6.2, "unit": "g/dL", "ref_low": 13.0, "ref_high": 17.5},
        # Creatinine > 3.5 mg/dL (Severe acute or chronic renal failure)
        {"test": "Creatinine", "value": 4.1, "unit": "mg/dL", "ref_low": 0.6, "ref_high": 1.2},
    ]

    flagged = flag_values(critical_cases)
    for res in flagged:
        assert res["status"] == "CRITICAL"
        assert res["is_critical"] is True
