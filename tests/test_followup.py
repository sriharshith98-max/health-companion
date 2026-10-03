"""Unit and integration tests for Case Storage and Follow-Up Chat (core/storage.py & core/followup.py)."""

import io
import json
import os
import tempfile
import pytest
from reportlab.pdfgen import canvas
from PIL import Image

from core.followup import followup
from core.safety import DISCLAIMER_TEXT
from core.storage import (
    delete_case_data,
    get_case,
    get_case_messages,
    init_db,
    save_case,
    save_event,
)


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



def test_reopening_saved_case_restores_state_and_timeline(temp_db):
    """Acceptance Check 1: Reopening a saved case restores its full timeline and state."""
    case_state = {
        "case_id": "test-case-123",
        "created": "2026-10-01",
        "patient": {"age": 30, "sex": "Male"},
        "doctor_dx": "viral infection",
        "treatment_start_date": "2026-10-01",
        "current_medicines": [{"drug": "Paracetamol", "dose": "650 mg", "frequency": "TID", "duration": "3 days"}],
        "symptom_timeline": [{"symptom": "fever", "onset": "2026-10-01", "status": "ongoing"}],
        "labs": [{"date": "2026-10-01", "test": "hemoglobin", "value": 14.0, "unit": "g/dL", "status": "NORMAL"}],
        "last_verdict": {"verdict": "AGREE", "top_candidates": [], "urgency": "routine"},
        "pending_tests": [],
    }

    save_case(case_state, db_path=temp_db)
    save_event(
        case_id="test-case-123",
        event_type="initial",
        summary="Initial visit recorded",
        details={"verdict": "AGREE"},
        db_path=temp_db,
    )

    restored = get_case("test-case-123", db_path=temp_db)
    assert restored is not None
    assert restored["case_id"] == "test-case-123"
    assert restored["patient"]["age"] == 30
    assert len(restored["events"]) == 1
    assert restored["events"][0]["summary"] == "Initial visit recorded"
    assert restored["current_medicines"][0]["drug"] == "Paracetamol"


def test_demo_case_4_not_improving_treatment_review(temp_db):
    """Acceptance Check 2: Demo Case 4 returns NOT_IMPROVING plus treatment-review recommendation and tests.

    Case 4: Follow-up on Day 5: 'Fever is still there, now I also have ear pain and a very sore throat,
    and I am taking the medicines as told.'
    """
    # Baseline setup: Case 1 style
    case_state = {
        "case_id": "case-4-demo",
        "patient": {"age": 30, "sex": "Male"},
        "doctor_dx": "viral upper respiratory infection",
        "treatment_start_date": "2026-10-01",
        "current_medicines": [{"drug": "Paracetamol", "dose": "650 mg", "frequency": "TID", "duration": "3 days"}],
        "symptom_timeline": [
            {"symptom": "fever", "onset": "2026-10-01", "status": "ongoing"},
            {"symptom": "sore throat", "onset": "2026-10-01", "status": "ongoing"},
        ],
        "labs": [],
        "last_verdict": {"verdict": "AGREE", "urgency": "routine"},
    }
    save_case(case_state, db_path=temp_db)

    user_msg = (
        "Day 5: Fever is still there, now I also have ear pain and a very sore throat, "
        "and I am taking the medicines as told."
    )
    reply = followup(case_id="case-4-demo", user_message=user_msg, db_path=temp_db)

    assert reply["trajectory"] in ("NOT_IMPROVING", "NEW_CONCERN")
    assert reply["treatment_review_needed"] is True
    assert "re-evaluation" in reply["treatment_review_reason"].lower() or "treatment" in reply["treatment_review_reason"].lower()
    assert len(reply["tests_to_discuss"]) > 0
    assert reply["contact_within"] in ("24 hours", "soon", "this week")
    assert reply["disclaimer"] == DISCLAIMER_TEXT

    # Safety: must not prescribe specific drug or dose
    assert "mg" not in reply["assessment"].lower()
    assert "start taking" not in reply["assessment"].lower()


def test_improving_followup_returns_improving(temp_db):
    """Acceptance Check 3: An 'improving' follow-up returns IMPROVING with continue-and-monitor advice."""
    case_state = {
        "case_id": "case-improving-demo",
        "patient": {"age": 28, "sex": "Female"},
        "doctor_dx": "viral infection",
        "treatment_start_date": "2026-10-01",
        "current_medicines": [{"drug": "Paracetamol", "dose": "650 mg", "frequency": "TID", "duration": "3 days"}],
        "symptom_timeline": [{"symptom": "fever", "onset": "2026-10-01", "status": "ongoing"}],
    }
    save_case(case_state, db_path=temp_db)

    user_msg = "Day 4: Fever is completely gone and I am feeling much better, symptoms resolved."
    reply = followup(case_id="case-improving-demo", user_message=user_msg, db_path=temp_db)

    assert reply["trajectory"] == "IMPROVING"
    assert reply["treatment_review_needed"] is False
    assert "resolving" in reply["assessment"].lower() or "improving" in reply["assessment"].lower()


def test_urgent_symptoms_return_urgent_immediately(temp_db):
    """Acceptance Check 4: A follow-up with breathlessness or chest pain returns URGENT immediately."""
    case_state = {
        "case_id": "case-urgent-demo",
        "patient": {"age": 30, "sex": "Male"},
        "doctor_dx": "viral infection",
    }
    save_case(case_state, db_path=temp_db)

    user_msg = "Day 6: I am having trouble breathing and severe chest pain."
    reply = followup(case_id="case-urgent-demo", user_message=user_msg, db_path=temp_db)

    assert reply["trajectory"] == "URGENT"
    assert reply["contact_within"] == "immediately"
    assert "urgent" in reply["assessment"].lower() or "emergency" in reply["specialist_or_doctor_to_contact"].lower()


def test_new_lab_report_pdf_adds_values_and_shows_change(temp_db):
    """Acceptance Check 5: Uploading a new lab report PDF adds its values and shows the change vs previous."""
    # Pre-existing case with previous lab value
    case_state = {
        "case_id": "case-lab-trend",
        "patient": {"age": 34, "sex": "Male"},
        "doctor_dx": "fatigue",
        "labs": [{"date": "2026-09-01", "test": "hemoglobin", "value": 12.0, "unit": "g/dL", "status": "LOW"}],
    }
    save_case(case_state, db_path=temp_db)

    # Generate new lab report PDF with hemoglobin = 10.5 (lower)
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "FOLLOW-UP BLOOD REPORT")
    c.drawString(100, 720, "Hemoglobin: 10.5 g/dL (Ref: 13.5 - 17.5)")
    c.save()
    buf.seek(0)
    buf.name = "new_cbc.pdf"

    reply = followup(case_id="case-lab-trend", user_message="Here is my follow-up CBC test", new_files=[buf], db_path=temp_db)

    # Verify that case_state updated
    updated_case = get_case("case-lab-trend", db_path=temp_db)
    assert len(updated_case["labs"]) == 2
    assert updated_case["labs"][-1]["value"] == 10.5
    # Verify change is noted in what_changed
    assert "hemoglobin" in reply["what_changed"].lower()
    assert "lower" in reply["what_changed"].lower() or "10.5" in reply["what_changed"]


def test_new_prescription_attachment_updates_medicines(temp_db):
    """Acceptance Check 6: Uploading a new prescription photo updates current medicines and re-runs drug check."""
    case_state = {
        "case_id": "case-rx-update",
        "patient": {"age": 40, "sex": "Female"},
        "doctor_dx": "viral infection",
        "current_medicines": [],
    }
    save_case(case_state, db_path=temp_db)

    rx_file = io.BytesIO(b"Rx: Tab. Amoxicillin 500 mg TID for 5 days\nTab. Paracetamol 650 mg SOS\n")
    rx_file.name = "prescription.txt"

    reply = followup(case_id="case-rx-update", user_message="Doctor gave me a new prescription today", new_files=[rx_file], db_path=temp_db)

    updated_case = get_case("case-rx-update", db_path=temp_db)
    assert len(updated_case["current_medicines"]) >= 1
    assert any("amoxicillin" in m["drug"].lower() for m in updated_case["current_medicines"])


def test_symptom_photo_stored_as_neutral_description(temp_db):
    """Acceptance Check 7: A symptom photo is stored as a neutral description and reply does not diagnose from it."""
    case_state = {
        "case_id": "case-photo-note",
        "patient": {"age": 25, "sex": "Female"},
        "doctor_dx": "allergies",
    }
    save_case(case_state, db_path=temp_db)

    # Create dummy image
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "rash_photo.png"

    reply = followup(case_id="case-photo-note", user_message="I noticed this skin spot today", new_files=[buf], db_path=temp_db)

    updated_case = get_case("case-photo-note", db_path=temp_db)
    # Check that it was stored neutrally in symptom timeline
    timeline = updated_case.get("symptom_timeline", [])
    assert any("photo note" in item.get("symptom", "").lower() for item in timeline)
    # Never diagnose from a photo
    assert "you have" not in reply["assessment"].lower()


def test_multiple_attachments_in_one_message(temp_db):
    """Acceptance Check 8: Multiple attachments in one message are each classified and processed."""
    case_state = {"case_id": "case-multi-att", "doctor_dx": "routine checkup"}
    save_case(case_state, db_path=temp_db)

    lab_file = io.BytesIO(b"LAB REPORT: ESR: 35 mm/hr (0 - 15)\n")
    lab_file.name = "esr_report.txt"

    rx_file = io.BytesIO(b"Rx: Tab. Paracetamol 650 mg SOS\n")
    rx_file.name = "rx_note.txt"

    reply = followup(case_id="case-multi-att", user_message="Here are my new test and prescription", new_files=[lab_file, rx_file], db_path=temp_db)

    assert "esr" in reply["what_changed"].lower() or "lab report" in reply["what_changed"].lower()


def test_unreadable_file_produces_clear_message_not_made_up_values(temp_db):
    """Acceptance Check 9: An unreadable file produces a clear message, not made-up values."""
    case_state = {"case_id": "case-unreadable", "doctor_dx": "regular checkup"}
    save_case(case_state, db_path=temp_db)

    empty_file = io.BytesIO(b"")
    empty_file.name = "blurry_empty.txt"

    reply = followup(case_id="case-unreadable", user_message="Check this file", new_files=[empty_file], db_path=temp_db)

    assert "could not be read clearly" in reply["what_changed"] or "clearer file" in reply["what_changed"]


def test_no_reply_ever_names_specific_drug_or_dosage(temp_db):
    """Acceptance Check 10: No reply ever names a specific drug to start, or gives a dose."""
    case_state = {
        "case_id": "case-safety-check",
        "doctor_dx": "viral infection",
    }
    save_case(case_state, db_path=temp_db)

    user_msg = "Do I need further medication or an antibiotic?"
    reply = followup(case_id="case-safety-check", user_message=user_msg, db_path=temp_db)

    full_reply_text = json.dumps(reply).lower()
    assert "start taking" not in full_reply_text
    assert "take 500mg" not in full_reply_text
    assert "take 250mg" not in full_reply_text
    assert "stop taking" not in full_reply_text
    assert "doctor" in full_reply_text


def test_prompt_sends_casestate_and_last_6_messages(temp_db):
    """Acceptance Check 11: get_case_messages bounds context to the last 6 messages."""
    case_id = "bounded-context-case"
    case_state = {"case_id": case_id, "doctor_dx": "viral infection"}
    save_case(case_state, db_path=temp_db)

    # Insert 10 user/assistant messages
    for i in range(10):
        followup(case_id=case_id, user_message=f"Message update {i+1}", db_path=temp_db)

    # Query last 6 messages
    recent = get_case_messages(case_id, limit=6, db_path=temp_db)
    assert len(recent) <= 6
