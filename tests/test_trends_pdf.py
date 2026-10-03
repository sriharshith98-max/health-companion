"""Unit tests for Lab Trends, PDF Export, and Data Deletion (Step 12)."""

import io
import os
import tempfile
import pdfplumber
import pytest

from core.pdf_export import generate_pdf_report
from core.safety import DISCLAIMER_TEXT
from core.storage import (
    delete_all_data,
    get_case,
    init_db,
    list_cases,
    save_case,
    save_event,
    save_message,
)
from core.trends import build_lab_trend_figures


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    try:
        if os.path.exists(path):
            os.remove(path)
    except (PermissionError, OSError):
        pass


def test_two_saved_reports_show_trend_chart():
    """Acceptance Check 1: Two saved reports of the same test show a trend chart."""
    labs = [
        {"test": "hemoglobin", "value": 11.2, "unit": "g/dL", "date": "2026-09-01", "status": "LOW", "ref_low": 13.0, "ref_high": 17.5},
        {"test": "hemoglobin", "value": 12.8, "unit": "g/dL", "date": "2026-09-15", "status": "LOW", "ref_low": 13.0, "ref_high": 17.5},
        {"test": "platelets", "value": 250000, "unit": "/cumm", "date": "2026-09-01", "status": "NORMAL"},
    ]

    trend_figures = build_lab_trend_figures(labs)
    # Hemoglobin has 2 readings, platelets only 1
    assert len(trend_figures) == 1
    hb_trend = trend_figures[0]
    assert hb_trend["test"] == "hemoglobin"
    assert hb_trend["count"] == 2
    assert hb_trend["figure"] is not None


def test_pdf_contains_verdict_evidence_tests_specialist_and_disclaimer():
    """Acceptance Check 2: PDF contains the verdict, evidence, tests, specialist, and disclaimer."""
    case_state = {
        "case_id": "pdf-test-uuid-987",
        "patient": {"age": 34, "sex": "Male"},
        "doctor_dx": "regular infection",
        "events": [
            {"date": "2026-10-01", "summary": "Initial visit analyzed: ESCALATE"},
            {"date": "2026-10-05", "summary": "Follow-up update: NOT_IMPROVING"},
        ],
    }

    final_report = {
        "verdict": "ESCALATE",
        "urgency": "soon",
        "summary": "Clinical findings suggest possible tuberculosis requiring pulmonology consultation.",
        "why": ["Cough longer than 2 weeks", "Raised ESR (45 mm/hr)", "Unexplained weight loss"],
        "possible_conditions": [
            {"name": "Tuberculosis", "why_possible": "Supported by chronic cough and raised ESR", "confidence": "high"}
        ],
        "tests_to_confirm": ["Chest X-ray", "Sputum AFB smear / CBNAAT"],
        "specialist_to_consult": "Pulmonologist",
        "prescription_notes": ["Discuss antibiotic duration with your doctor or pharmacist"],
        "warning_signs": ["Blood in sputum", "Severe breathlessness"],
        "questions_for_doctor": ["Should a chest X-ray be performed?"],
        "disclaimer": DISCLAIMER_TEXT,
    }

    pdf_bytes = generate_pdf_report(case_state, final_report)
    assert len(pdf_bytes) > 1000

    # Extract text from generated PDF using pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        all_pdf_text = "\n".join(page.extract_text() for page in pdf.pages)

    assert "VERDICT: ESCALATE" in all_pdf_text
    assert "Pulmonologist" in all_pdf_text
    assert "Chest X-ray" in all_pdf_text or "Sputum" in all_pdf_text
    assert "Cough longer than 2 weeks" in all_pdf_text or "ESR" in all_pdf_text
    # Mandatory verbatim disclaimer check (normalize line wrapping in extracted PDF text)
    normalized_pdf_text = " ".join(all_pdf_text.split())
    normalized_disclaimer = " ".join(DISCLAIMER_TEXT.split())
    assert normalized_disclaimer in normalized_pdf_text


def test_delete_my_data_removes_all_stored_rows(temp_db):
    """Acceptance Check 3: 'Delete my data' removes all stored rows."""
    # 1. Insert sample cases, events, and messages
    case_state = {
        "case_id": "case-to-delete-1",
        "patient": {"age": 50, "sex": "Female"},
        "doctor_dx": "bronchitis",
    }
    save_case(case_state, db_path=temp_db)
    save_event("case-to-delete-1", "initial", "Initial analysis", {}, db_path=temp_db)
    save_message("case-to-delete-1", "user", "Hello doctor", db_path=temp_db)

    # Verify they exist
    assert len(list_cases(db_path=temp_db)) == 1
    assert get_case("case-to-delete-1", db_path=temp_db) is not None

    # 2. Invoke complete privacy wipe
    delete_all_data(db_path=temp_db)

    # 3. Verify all tables are completely empty
    assert len(list_cases(db_path=temp_db)) == 0
    assert get_case("case-to-delete-1", db_path=temp_db) is None
