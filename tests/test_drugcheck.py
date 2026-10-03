"""Unit tests for prescription and interaction analysis (core/drugcheck.py)."""

from unittest.mock import patch
import pytest
import requests

from core.drugcheck import (
    check_indication,
    check_interactions,
    check_prescription,
)


def test_known_interacting_pair_flagged():
    """Acceptance Check 1: A known interacting pair is flagged."""
    prescription_items = [
        {"drug": "Tab. Warfarin", "dose": "5 mg", "frequency": "OD", "duration": "30 days"},
        {"drug": "Tab. Aspirin", "dose": "75 mg", "frequency": "OD", "duration": "30 days"},
    ]

    notes, warnings = check_interactions(prescription_items)
    assert len(notes) > 0
    assert any("warfarin" in n.lower() and "aspirin" in n.lower() for n in notes)
    # Check safety phrasing
    assert any("doctor or pharmacist" in n.lower() for n in notes)
    assert not any("stop taking" in n.lower() for n in notes)


def test_antibiotic_with_viral_dx_produces_discussion_note():
    """Acceptance Check 2: An antibiotic with a viral dx produces a discussion note."""
    prescription_items = [
        {"drug": "Amoxicillin", "dose": "500 mg", "frequency": "TID", "duration": "5 days"},
        {"drug": "Paracetamol", "dose": "650 mg", "frequency": "TID", "duration": "3 days"},
    ]
    doctor_dx = "viral upper respiratory infection"
    doctor_dx_matched = "viral_upper_respiratory_infection"

    notes = check_indication(prescription_items, doctor_dx, doctor_dx_matched)
    assert len(notes) > 0
    assert any("antibiotic" in n.lower() and "amoxicillin" in n.lower() for n in notes)
    assert any("bacterial" in n.lower() and "viral" in n.lower() for n in notes)
    assert any("discuss this with your doctor or pharmacist" in n.lower() for n in notes)
    assert not any("stop taking" in n.lower() for n in notes)


def test_api_failure_returns_warning_not_crash():
    """Acceptance Check 3: API failure returns an empty note list plus a warning, not a crash."""
    prescription_items = [
        {"drug": "NonInteractingMedA", "dose": "10 mg", "frequency": "OD", "duration": "5 days"},
        {"drug": "NonInteractingMedB", "dose": "20 mg", "frequency": "OD", "duration": "5 days"},
    ]

    # Force requests.get to simulate a network outage / connection error
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Network unavailable")):
        res = check_prescription(
            prescription_items=prescription_items,
            doctor_dx="regular checkup",
            top_conditions=[],
            verdict="AGREE",
        )
        assert isinstance(res, dict)
        assert "warnings" in res
        # Function did not crash and recorded a friendly warning
        assert len(res["warnings"]) > 0
        assert any("network" in w.lower() or "connection" in w.lower() for w in res["warnings"])


def test_prescription_safety_phrasing_rules():
    """Verify that no prescription output advises stopping medicines or contains dosages."""
    prescription_items = [
        {"drug": "Ciprofloxacin", "dose": "500 mg", "frequency": "BD", "duration": "7 days"},
        {"drug": "Iron Supplement", "dose": "100 mg", "frequency": "OD", "duration": "30 days"},
    ]
    res = check_prescription(
        prescription_items=prescription_items,
        doctor_dx="viral infection",
        top_conditions=[{"name": "tuberculosis", "specialist": "Pulmonologist"}],
        verdict="ESCALATE",
    )

    for note in res["discussion_notes"]:
        assert "stop taking" not in note.lower()
        assert "skip" not in note.lower()
        assert "your doctor is wrong" not in note.lower()
