"""Clinical PDF export module for Second-Opinion Companion.

Generates structured, professional clinical summary reports via ReportLab.
Includes verdict, evidence, confirmatory tests, specialist referrals,
follow-up timelines, and the verbatim mandatory safety disclaimer.
"""

from datetime import datetime
import io
import logging
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.safety import DISCLAIMER_TEXT

logger = logging.getLogger(__name__)


def generate_pdf_report(case_state: dict[str, Any], final_report: dict[str, Any]) -> bytes:
    """Generate a formatted PDF summary of the clinical second-opinion assessment.

    Args:
        case_state: Persistent CaseState dictionary
        final_report: Validated FinalReport dictionary

    Returns:
        bytes: Raw PDF binary stream
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1E3A8A"),
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#64748B"),
        fontName="Helvetica",
        spaceAfter=12,
    )
    h2_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        fontName="Helvetica-Bold",
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1E293B"),
        fontName="Helvetica",
        spaceAfter=4,
    )
    disclaimer_style = ParagraphStyle(
        "DisclaimerText",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica-Oblique",
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("HealthAi - Clinical Second-Opinion Summary", title_style))
    story.append(
        Paragraph(
            "Evidence-Based Second-Opinion Assessment & Diagnostic Guidance System",
            subtitle_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563EB"), spaceAfter=10))

    # 2. Patient & Clinical Context Table
    patient = case_state.get("patient", {})
    case_id = case_state.get("case_id", "N/A")
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    doctor_dx = case_state.get("doctor_dx", "Not specified")

    meta_data = [
        [
            Paragraph(f"<b>Case ID:</b> {case_id[:16]}...", body_style),
            Paragraph(f"<b>Date:</b> {date_str}", body_style),
        ],
        [
            Paragraph(f"<b>Patient:</b> Age {patient.get('age', 'N/A')}, {patient.get('sex', 'N/A')}", body_style),
            Paragraph(f"<b>Stated Diagnosis:</b> {doctor_dx}", body_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[260, 260])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # 3. Verdict & Urgency Banner Box
    verdict = final_report.get("verdict", "INCONCLUSIVE").upper()
    urgency = final_report.get("urgency", "routine").upper()

    if verdict == "AGREE":
        v_bg = colors.HexColor("#ECFDF5")
        v_text_color = colors.HexColor("#065F46")
        v_border = colors.HexColor("#10B981")
    elif verdict == "ESCALATE":
        v_bg = colors.HexColor("#FEF2F2")
        v_text_color = colors.HexColor("#991B1B")
        v_border = colors.HexColor("#EF4444")
    else:
        v_bg = colors.HexColor("#F1F5F9")
        v_text_color = colors.HexColor("#334155")
        v_border = colors.HexColor("#64748B")

    verdict_style = ParagraphStyle(
        "VerdictTitle",
        parent=styles["Normal"],
        fontSize=14,
        leading=18,
        fontName="Helvetica-Bold",
        textColor=v_text_color,
    )
    urgency_style = ParagraphStyle(
        "UrgencyTitle",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        fontName="Helvetica-Bold",
        textColor=v_text_color,
        alignment=2,  # Right aligned
    )

    verdict_row = [
        [
            Paragraph(f"VERDICT: {verdict}", verdict_style),
            Paragraph(f"URGENCY: {urgency}", urgency_style),
        ]
    ]
    verdict_table = Table(verdict_row, colWidths=[300, 220])
    verdict_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), v_bg),
            ("BOX", (0, 0), (-1, -1), 1.5, v_border),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(verdict_table)
    story.append(Spacer(1, 10))

    # 4. Clinical Summary & Evidence
    story.append(Paragraph("1. Assessment Summary & Evidence", h2_style))
    summary_text = final_report.get("summary", "")
    story.append(Paragraph(summary_text, body_style))

    why_reasons = final_report.get("why", [])
    if why_reasons:
        story.append(Paragraph("<b>Key Evidence & Findings:</b>", body_style))
        for r in why_reasons:
            story.append(Paragraph(f"• {r}", body_style))
    story.append(Spacer(1, 8))

    # 5. Possible Conditions & Confirmatory Tests
    story.append(Paragraph("2. Candidate Conditions & Confirmatory Tests", h2_style))
    possible_conds = final_report.get("possible_conditions", [])
    if possible_conds:
        for c in possible_conds:
            c_name = c.get("name", "")
            c_why = c.get("why_possible", "")
            c_conf = c.get("confidence", "medium").upper()
            story.append(Paragraph(f"• <b>{c_name}</b> (Confidence: {c_conf}) - {c_why}", body_style))

    specialist = final_report.get("specialist_to_consult", "General Physician")
    story.append(Paragraph(f"<b>Recommended Specialist to Consult:</b> {specialist}", body_style))

    tests = final_report.get("tests_to_confirm", [])
    if tests:
        tests_str = ", ".join(tests)
        story.append(Paragraph(f"<b>Recommended Tests for Verification:</b> {tests_str}", body_style))
    story.append(Spacer(1, 8))

    # 6. Prescription & Medication Points
    rx_notes = final_report.get("prescription_notes", [])
    if rx_notes:
        story.append(Paragraph("3. Prescription Points for Discussion", h2_style))
        for pn in rx_notes:
            story.append(Paragraph(f"• {pn}", body_style))
        story.append(Spacer(1, 8))

    # 7. Warning Signs & Questions for Doctor
    story.append(Paragraph("4. Warning Signs & Questions for Your Doctor", h2_style))
    warning_signs = final_report.get("warning_signs", [])
    if warning_signs:
        story.append(Paragraph("<b>Warning Signs Requiring Urgent Evaluation:</b>", body_style))
        for ws in warning_signs:
            story.append(Paragraph(f"• {ws}", body_style))

    questions = final_report.get("questions_for_doctor", [])
    if questions:
        story.append(Paragraph("<b>Questions to Ask Your Doctor:</b>", body_style))
        for q in questions:
            story.append(Paragraph(f"• {q}", body_style))
    story.append(Spacer(1, 8))

    # 8. Follow-up Timeline (if present)
    events = case_state.get("events", [])
    if events and len(events) > 1:
        story.append(Paragraph("5. Chronological Case Timeline", h2_style))
        for ev in events:
            date_part = ev.get("date", "")[:16].replace("T", " ")
            story.append(Paragraph(f"• <b>{date_part}</b>: {ev.get('summary', '')}", body_style))
        story.append(Spacer(1, 8))

    # 9. Mandatory Verbatim Disclaimer Box
    story.append(Spacer(1, 10))
    disclaimer_box = [
        [
            Paragraph(
                f"<b>MANDATORY MEDICAL DISCLAIMER:</b> {DISCLAIMER_TEXT}",
                disclaimer_style,
            )
        ]
    ]
    disc_table = Table(disclaimer_box, colWidths=[520])
    disc_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#94A3B8")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(disc_table)

    doc.build(story)
    return buffer.getvalue()
