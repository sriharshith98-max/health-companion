"""Unit tests for structured extraction (core/extract.py)."""

import pytest
from core.extract import (
    structure_prescription,
    structure_report,
    structure_symptoms,
)


def test_five_sample_symptom_descriptions():
    """Acceptance Check 1: 5 sample symptom descriptions yield correct flags and duration."""

    # 1. Prolonged cough with B-symptoms (TB pattern)
    tb_text = "Cough 3 weeks, evening fever, night sweats, and unexplained weight loss."
    tb_struct = structure_symptoms(tb_text)
    assert tb_struct["duration_days"] == 21
    assert tb_struct["flags"]["cough_gt_14d"] is True
    assert tb_struct["flags"]["fever"] is True
    assert tb_struct["flags"]["night_sweats"] is True
    assert tb_struct["flags"]["weight_loss"] is True
    assert tb_struct["flags"]["blood_in_sputum"] is False

    # 2. Acute viral upper respiratory infection
    viral_text = "Sore throat, mild fever, runny nose for 2 days."
    viral_struct = structure_symptoms(viral_text)
    assert viral_struct["duration_days"] == 2
    assert viral_struct["flags"]["fever"] is True
    assert viral_struct["flags"]["cough_gt_14d"] is False
    assert viral_struct["flags"]["weight_loss"] is False

    # 3. Diabetes pattern
    dm_text = "Fatigue, excessive thirst, and frequent urination for 6 weeks."
    dm_struct = structure_symptoms(dm_text)
    assert dm_struct["duration_days"] == 42
    assert dm_struct["flags"]["fatigue"] is True
    assert dm_struct["flags"]["thirst"] is True
    assert dm_struct["flags"]["frequent_urination"] is True
    assert dm_struct["flags"]["fever"] is False

    # 4. Critical emergency flag
    urgent_text = "Severe chest pain and breathlessness for 1 day."
    urgent_struct = structure_symptoms(urgent_text)
    assert urgent_struct["duration_days"] == 1
    assert urgent_struct["flags"]["chest_pain"] is True
    assert urgent_struct["flags"]["breathlessness"] is True

    # 5. Acute febrile / Dengue pattern
    dengue_text = "High fever, severe headache, and joint pain for 4 days."
    dengue_struct = structure_symptoms(dengue_text)
    assert dengue_struct["duration_days"] == 4
    assert dengue_struct["flags"]["fever"] is True
    assert dengue_struct["flags"]["headache"] is True
    assert dengue_struct["flags"]["joint_pain"] is True


def test_sample_cbc_yields_correct_rows():
    """Acceptance Check 2: A sample CBC yields correct test/value/unit/range rows."""
    cbc_report = (
        "COMPLETE BLOOD COUNT (CBC)\n"
        "Hemoglobin: 10.2 g/dL (Ref Range: 13.5 - 17.5)\n"
        "WBC Count: 8200 /cumm (Ref Range: 4000 - 11000)\n"
        "Platelet Count: 150000 /cumm (Ref Range: 150000 - 450000)\n"
        "ESR: 45 mm/hr (Ref Range: 0 - 15)\n"
    )

    extracted = structure_report(cbc_report)
    assert len(extracted) == 4

    tests_dict = {item["test"].lower(): item for item in extracted}
    
    # Check Hemoglobin
    hb = tests_dict["hemoglobin"]
    assert hb["value"] == 10.2
    assert hb["unit"] == "g/dL"
    assert hb["ref_low"] == 13.5
    assert hb["ref_high"] == 17.5

    # Check WBC
    wbc = tests_dict["wbc count"]
    assert wbc["value"] == 8200.0
    assert wbc["ref_low"] == 4000.0
    assert wbc["ref_high"] == 11000.0

    # Check Platelet
    plt = tests_dict["platelet count"]
    assert plt["value"] == 150000.0
    assert plt["ref_low"] == 150000.0
    assert plt["ref_high"] == 450000.0

    # Check ESR
    esr = tests_dict["esr"]
    assert esr["value"] == 45.0
    assert esr["unit"] == "mm/hr"
    assert esr["ref_low"] == 0.0
    assert esr["ref_high"] == 15.0


def test_sample_prescription_yields_drug_rows():
    """Acceptance Check 3: A sample prescription yields drug/dose/frequency rows."""
    rx_text = (
        "PRESCRIPTION\n"
        "1. Tab. Amoxicillin 500 mg TID for 5 days\n"
        "2. Tab. Paracetamol 650 mg SOS for 3 days\n"
    )

    items = structure_prescription(rx_text)
    assert len(items) == 2

    amox = items[0]
    assert "amoxicillin" in amox["drug"].lower()
    assert "500" in amox["dose"]
    assert amox["frequency"] is not None and "TID" in amox["frequency"].upper()
    assert amox["duration"] is not None and "5" in amox["duration"]

    pcm = items[1]
    assert "paracetamol" in pcm["drug"].lower()
    assert "650" in pcm["dose"]
    assert pcm["frequency"] is not None and "SOS" in pcm["frequency"].upper()
    assert pcm["duration"] is not None and "3" in pcm["duration"]
