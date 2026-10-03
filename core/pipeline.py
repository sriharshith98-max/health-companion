"""End-to-end verification pipeline for Second-Opinion Companion.

Coordinates:
- Ingestion (Step 3)
- Structured Extraction (Step 4)
- Lab Flagging (Step 5)
- Condition Matching & Verdict Engine (Step 7)
- Prescription Check (Step 8)
- Grounded Report Generation (Step 9)
- Safety Review & Disclaimer Enforcement (Step 9)
"""

import logging
from typing import Any

from core.drugcheck import check_prescription
from core.extract import (
    structure_prescription,
    structure_report,
    structure_symptoms,
)
from core.ingest import read_file
from core.labs import flag_values
from core.matcher import extract_signals, match_conditions
from core.report import generate_report
from core.safety import review_safety

logger = logging.getLogger(__name__)


def verify(patient_input: dict[str, Any]) -> dict[str, Any]:
    """Execute complete second-opinion clinical verification pipeline.

    Args:
        patient_input: Dictionary with:
            - 'age': int
            - 'sex': str
            - 'symptoms_text': str
            - 'duration_days': int | None
            - 'doctor_dx': str
            - 'reports': list of file objects, paths, or strings (optional)
            - 'prescription': file object, path, or string (optional)

    Returns:
        FinalReport JSON dict adhering to SPEC.md Section 4.4 schema.
    """
    # 1. Ingestion: aggregate report texts and prescription text
    reports_text_parts = []
    reports = patient_input.get("reports", [])
    if isinstance(reports, (str, bytes)):
        reports = [reports]

    for rep in reports:
        if isinstance(rep, str) and ("\n" in rep or len(rep) > 50):
            # Treat as already-extracted text
            reports_text_parts.append(rep)
        elif rep:
            extracted = read_file(rep)
            if extracted.get("text"):
                reports_text_parts.append(extracted["text"])

    combined_report_text = "\n\n".join(reports_text_parts).strip()

    rx_text = ""
    prescription_raw = patient_input.get("prescription")
    if isinstance(prescription_raw, str) and ("\n" in prescription_raw or len(prescription_raw) > 20):
        rx_text = prescription_raw
    elif prescription_raw:
        extracted_rx = read_file(prescription_raw)
        rx_text = extracted_rx.get("text", "")

    # 2. Structured Extraction
    symptoms_text = patient_input.get("symptoms_text", "")
    duration_days = patient_input.get("duration_days")
    structured_symptoms = structure_symptoms(symptoms_text, duration_days)

    structured_labs = structure_report(combined_report_text) if combined_report_text else []
    structured_rx = structure_prescription(rx_text) if rx_text else []

    # 3. Lab Analysis & Normalization
    flagged_labs = flag_values(structured_labs)

    # 4. Signal Extraction, Candidate Scoring, and Verdict Engine
    doctor_dx = patient_input.get("doctor_dx", "")
    signals = extract_signals(structured_symptoms, flagged_labs)
    verdict_data = match_conditions(signals, doctor_dx, flagged_labs, structured_symptoms)

    # 5. Prescription Analysis
    drug_analysis = check_prescription(
        prescription_items=structured_rx,
        doctor_dx=doctor_dx,
        top_conditions=verdict_data.get("top_candidates", []),
        verdict=verdict_data.get("verdict", ""),
        doctor_dx_matched=verdict_data.get("doctor_dx_matched"),
    )
    drug_notes = drug_analysis.get("discussion_notes", [])

    # 6. Grounded Report Generation
    raw_report = generate_report(verdict_data, patient_input, flagged_labs, drug_notes)

    # 7. Safety Review Layer
    evidence_context = {
        "verdict_data": verdict_data,
        "patient_input": patient_input,
        "flagged_labs": flagged_labs,
        "structured_rx": structured_rx,
        "signals": list(signals),
    }
    final_report = review_safety(raw_report, evidence_context)

    return final_report
