"""Unit tests verifying UI logic and Streamlit components (tests/test_ui.py)."""

import os
import pytest
import pandas as pd
from core.pipeline import verify
from core.ingest import classify_document, read_file
from core.safety import DISCLAIMER_TEXT


def test_ui_template_files_present():
    """Verify ui_template directory contains reference files and style.css."""
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui_template")
    assert os.path.isdir(template_dir)
    css_file = os.path.join(template_dir, "style.css")
    assert os.path.isfile(css_file)
    with open(css_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "pulse-header" in content
    assert "verdict-banner-agree" in content
    assert "verdict-banner-escalate" in content


def test_streamlit_config_toml_configured():
    """Verify .streamlit/config.toml contains PulseAi theme configuration."""
    config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".streamlit", "config.toml")
    assert os.path.isfile(config_file)
    with open(config_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "#2563EB" in content  # primary color


def test_flow_works_with_only_symptoms_and_no_documents():
    """Acceptance Check: The flow works with only symptoms and no documents."""
    patient_input = {
        "age": 32,
        "sex": "Female",
        "symptoms_text": "Dry cough, mild sore throat for 3 days",
        "duration_days": 3,
        "doctor_dx": "viral upper respiratory infection",
        "reports": [],
        "prescription": "",
    }
    report = verify(patient_input)
    assert report["verdict"] in ("AGREE", "INCONCLUSIVE")
    assert report["disclaimer"] == DISCLAIMER_TEXT
    assert report["specialist_to_consult"] is not None


def test_removing_file_excludes_it_from_results():
    """Acceptance Check: Removing a file before analysis excludes it from the results."""
    # If lab report with high ESR is included vs excluded
    symptoms = {
        "age": 34,
        "sex": "Male",
        "symptoms_text": "Cough for 3 weeks, evening fever, night sweats",
        "duration_days": 21,
        "doctor_dx": "regular infection",
    }

    # Case A: With lab report
    input_with_lab = dict(symptoms, reports=["CLINICAL REPORT\nESR: 45 mm/hr (0 - 15)\nHemoglobin: 12.0 g/dL\n"])
    report_with_lab = verify(input_with_lab)

    # Case B: Excluded/removed lab report
    input_without_lab = dict(symptoms, reports=[])
    report_without_lab = verify(input_without_lab)

    # Verifying that the lab evidence was only accounted for when the file was included
    why_with = " ".join(report_with_lab.get("why", [])).lower()
    why_without = " ".join(report_without_lab.get("why", [])).lower()
    assert "esr" in why_with
    assert "esr" not in why_without


def test_user_edits_on_confirm_change_result():
    """Acceptance Check: User edits on the confirm page change the result."""
    from core.matcher import extract_signals, match_conditions

    # Initial state: only mild symptoms
    initial_symptoms = {
        "symptoms": ["mild headache"],
        "duration_days": 1,
        "flags": {"headache": True},
    }
    signals_initial = extract_signals(initial_symptoms, [])
    verdict_initial = match_conditions(signals_initial, "tension headache")
    assert verdict_initial["verdict"] == "INCONCLUSIVE"

    # User manually edits symptoms on the confirm page: adds sore throat and runny nose
    edited_symptoms = {
        "symptoms": ["runny nose", "sore throat", "mild fever"],
        "duration_days": 2,
        "flags": {"fever": True},
    }
    signals_edited = extract_signals(edited_symptoms, [])
    verdict_edited = match_conditions(signals_edited, "viral upper respiratory infection")
    # Changes result from inconclusive to agree with viral fever
    assert verdict_edited["verdict"] == "AGREE"
    assert verdict_edited["verdict"] != verdict_initial["verdict"]

