"""HealthAi Second-Opinion Companion - Main Streamlit Application.

Structured 3-Screen Clinical Flow:
- SCREEN 1: Describe + Upload (~800px centered)
- SCREEN 2: Review (Editable tables, consent, analyze CTA)
- SCREEN 3: Result + Integrated Follow-Up Chat (Unified view)
"""

from datetime import datetime
import json
import os
import re
import sys
from typing import Any
import pandas as pd
import streamlit as st

# Add workspace directory to path
sys.path.insert(0, os.path.dirname(__file__))

import importlib
import core.llm
import core.followup
importlib.reload(core.llm)
importlib.reload(core.followup)

from core.drugcheck import check_prescription
from core.extract import (
    structure_prescription,
    structure_report,
    structure_symptoms,
)
from core.followup import followup
from core.ingest import classify_document, read_file
from core.labs import flag_values
from core.matcher import extract_signals, match_conditions
from core.pdf_export import generate_pdf_report
from core.pipeline import verify
from core.report import generate_report
from core.safety import DISCLAIMER_MAP, DISCLAIMER_TEXT, review_safety
from core.storage import (
    delete_all_data,
    delete_case_data,
    get_case,
    get_case_events,
    get_case_messages,
    init_db,
    list_cases,
    save_case,
    save_event,
)
from core.trends import build_lab_trend_figures

# Configure page
st.set_page_config(
    page_title="HealthAi - Second-Opinion Companion",
    page_icon="🩺",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Initialize database
init_db()

# Load custom CSS template
CSS_PATH = os.path.join(os.path.dirname(__file__), "ui_template", "style.css")
if os.path.exists(CSS_PATH):
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Initialize Session State
if "language" not in st.session_state:
    st.session_state.language = "English"
if "page" not in st.session_state:
    st.session_state.page = "intake"  # "intake" (Screen 1) | "review" (Screen 2) | "result" (Screen 3)
if "current_case_id" not in st.session_state:
    st.session_state.current_case_id = None
if "patient_input" not in st.session_state:
    st.session_state.patient_input = {
        "age": 30,
        "sex": "Female",
        "symptoms_text": "",
        "duration_days": 3,
        "doctor_dx": "",
        "prescription_text": "",
        "language": "English",
    }
if "uploaded_files_data" not in st.session_state:
    st.session_state.uploaded_files_data = []  # list of dicts: {name, type, text, file_obj, id}
if "extracted_data" not in st.session_state:
    st.session_state.extracted_data = None
if "final_report" not in st.session_state:
    st.session_state.final_report = None


def reset_all_data():
    """Clear all session data, delete persisted DB records, and return to intake."""
    delete_all_data()
    st.session_state.page = "intake"
    st.session_state.current_case_id = None
    st.session_state.patient_input = {
        "age": 30,
        "sex": "Female",
        "symptoms_text": "",
        "duration_days": 3,
        "doctor_dx": "",
        "prescription_text": "",
        "language": st.session_state.get("language", "English"),
    }
    st.session_state.uploaded_files_data = []
    st.session_state.extracted_data = None
    st.session_state.final_report = None
    st.rerun()


def load_demo_case(case_num: int):
    """Load pre-configured demo cases into session state and jump directly to results."""
    st.session_state.uploaded_files_data = []
    st.session_state.current_case_id = None

    if case_num == 1:
        st.session_state.patient_input = {
            "age": 28,
            "sex": "Female",
            "symptoms_text": "Sore throat, runny nose, and mild fever",
            "duration_days": 2,
            "doctor_dx": "viral upper respiratory infection",
            "language": st.session_state.get("language", "English"),
        }
        st.session_state.uploaded_files_data = [
            {
                "id": "demo_rx_1",
                "name": "prescription.txt",
                "type": "prescription",
                "text": "Rx: Tab. Paracetamol 650 mg SOS, rest, and oral hydration",
            }
        ]
    elif case_num == 2:
        st.session_state.patient_input = {
            "age": 34,
            "sex": "Male",
            "symptoms_text": "Persistent cough for 3 weeks, evening fever, night sweats, unexplained weight loss",
            "duration_days": 21,
            "doctor_dx": "regular infection",
            "language": st.session_state.get("language", "English"),
        }
        st.session_state.uploaded_files_data = [
            {
                "id": "demo_lab_2",
                "name": "cbc_esr_report.txt",
                "type": "lab_report",
                "text": "METROPOLITAN LAB\nHemoglobin: 11.5 g/dL (13.5 - 17.5)\nESR: 45 mm/hr (0 - 15)\nPlatelet Count: 280000 /cumm\n",
            },
            {
                "id": "demo_rx_2",
                "name": "rx_antibiotic.txt",
                "type": "prescription",
                "text": "Rx: Tab. Amoxicillin 500 mg TID x 5 days",
            },
        ]
    elif case_num == 3:
        st.session_state.patient_input = {
            "age": 45,
            "sex": "Male",
            "symptoms_text": "Constant fatigue, excessive thirst, frequent urination, slow-healing wound on foot for 6 weeks",
            "duration_days": 42,
            "doctor_dx": "weakness, vitamin deficiency",
            "language": st.session_state.get("language", "English"),
        }
        st.session_state.uploaded_files_data = [
            {
                "id": "demo_lab_3",
                "name": "fasting_blood_sugar.txt",
                "type": "lab_report",
                "text": "CLINICAL BIOCHEMISTRY\nFasting Blood Sugar: 138 mg/dL (70 - 99)\nHemoglobin: 12.0 g/dL (13.0 - 17.5)\n",
            },
            {
                "id": "demo_rx_3",
                "name": "rx_vitamins.txt",
                "type": "prescription",
                "text": "Rx: Cap. Multivitamins once daily for 30 days",
            },
        ]

    # Pre-compute report and persist case
    demo_report = verify({
        "age": st.session_state.patient_input["age"],
        "sex": st.session_state.patient_input["sex"],
        "symptoms_text": st.session_state.patient_input["symptoms_text"],
        "duration_days": st.session_state.patient_input["duration_days"],
        "doctor_dx": st.session_state.patient_input["doctor_dx"],
        "reports": [f["text"] for f in st.session_state.uploaded_files_data if f["type"] == "lab_report"],
        "prescription": "\n".join([f["text"] for f in st.session_state.uploaded_files_data if f["type"] == "prescription"]),
        "language": st.session_state.get("language", "English"),
    })
    st.session_state.final_report = demo_report
    cid = f"demo_case_{case_num}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    st.session_state.current_case_id = cid

    save_case({
        "case_id": cid,
        "patient": {"age": st.session_state.patient_input["age"], "sex": st.session_state.patient_input["sex"]},
        "doctor_dx": st.session_state.patient_input["doctor_dx"],
        "symptom_timeline": [{"symptom": s, "onset": "Initial visit", "status": "active"} for s in st.session_state.patient_input["symptoms_text"].split(", ")],
        "events": [{
            "event_id": f"ev_{cid}",
            "date": datetime.now().isoformat(),
            "type": "initial_assessment",
            "summary": f"Initial assessment: Verdict {demo_report['verdict']}, Urgency {demo_report['urgency']}",
            "details": demo_report,
        }],
    })

    st.session_state.page = "result"
    st.rerun()


def load_saved_case(chosen_id: str):
    """Load a previously saved case and its messages into session state."""
    loaded_case = get_case(chosen_id)
    if loaded_case:
        st.session_state.current_case_id = chosen_id
        pat = loaded_case.get("patient", {})
        symptoms_str = pat.get("symptoms_text")
        if not symptoms_str and loaded_case.get("symptom_timeline"):
            symptoms_str = " ".join(s.get("symptom", "") for s in loaded_case.get("symptom_timeline", []) if s.get("symptom"))
        st.session_state.patient_input = {
            "age": pat.get("age", 30),
            "sex": pat.get("sex", "Unknown"),
            "symptoms_text": symptoms_str or "",
            "duration_days": pat.get("duration_days", 3),
            "doctor_dx": loaded_case.get("doctor_dx", ""),
            "prescription_text": pat.get("prescription_text", ""),
            "language": st.session_state.get("language", "English"),
        }
        events = loaded_case.get("events", [])
        if events and events[-1].get("details"):
            st.session_state.final_report = events[-1].get("details", {})
        elif loaded_case.get("final_report"):
            st.session_state.final_report = loaded_case.get("final_report")
        elif loaded_case.get("last_verdict"):
            st.session_state.final_report = loaded_case.get("last_verdict")
        st.session_state.page = "result"
        st.rerun()


# ==============================================================================
# SLIM TOP HEADER (Brand Left, Quick Consultation Bar Center, Language Selector Right)
# ==============================================================================
saved_cases_all = list_cases()
header_col1, header_col2, header_col3 = st.columns([2.2, 1.8, 1])

with header_col1:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 8px; padding-top: 6px;">
            <span style="font-size: 1.55rem;">🩺</span>
            <span style="font-size: 1.35rem; font-weight: 800; color: #1E293B; letter-spacing: -0.02em;">HealthAi</span>
            <span class="pulse-badge">Second Opinion</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_col2:
    badge_label = f"💬 Past Chats ({len(saved_cases_all)})" if saved_cases_all else "💬 Past Chats"
    with st.popover(badge_label, use_container_width=True):
        st.markdown("##### 📁 Previous Consultations & Chats")
        if st.button("➕ Start New Check", key="top_new_check", use_container_width=True, type="primary"):
            st.session_state.page = "intake"
            st.session_state.final_report = None
            st.session_state.current_case_id = None
            st.session_state.uploaded_files_data = []
            st.rerun()

        if saved_cases_all:
            st.markdown("---")
            for idx, sc in enumerate(saved_cases_all[:6]):
                s_cid = sc["case_id"]
                s_dx = (sc.get("doctor_dx") or "").strip()
                s_sym = (sc.get("patient", {}).get("symptoms_text") or "").strip()
                s_title = s_dx if s_dx and s_dx.lower() != "regular infection" else (s_sym or s_dx or "Consultation")
                s_short = (s_title[:20] + "…") if len(s_title) > 20 else s_title
                s_mc = sc.get("message_count", 0)
                is_cur = (s_cid == st.session_state.current_case_id)
                icon = "▶ " if is_cur else "📄 "
                badge = f" ({s_mc} msgs)" if s_mc > 0 else ""
                if st.button(
                    f"{icon}{s_short}{badge}",
                    key=f"top_case_{s_cid}_{idx}",
                    use_container_width=True,
                    type="primary" if is_cur else "secondary",
                ):
                    load_saved_case(s_cid)
        else:
            st.caption("No past consultations yet.")

with header_col3:
    selected_lang = st.selectbox(
        "Language",
        options=["English", "Telugu", "Hindi"],
        format_func=lambda x: {"English": "English", "Telugu": "తెలుగు", "Hindi": "हिन्दी"}[x],
        index=["English", "Telugu", "Hindi"].index(st.session_state.get("language", "English")),
        key="top_lang_selector",
        label_visibility="collapsed",
    )
    if selected_lang != st.session_state.language:
        st.session_state.language = selected_lang
        st.session_state.patient_input["language"] = selected_lang
        st.rerun()

st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)


# ==============================================================================
# SIDEBAR (Navigation & Previous Chats / Consultations)
# ==============================================================================
with st.sidebar:
    st.markdown("### 🩺 HealthAi")
    st.caption("Evidence-Based Second Opinion")

    if st.button("➕ New Check", use_container_width=True, type="primary"):
        st.session_state.page = "intake"
        st.session_state.final_report = None
        st.session_state.current_case_id = None
        st.session_state.uploaded_files_data = []
        st.rerun()

    st.markdown("---")
    st.markdown("#### 💬 Previous Chats & Cases")
    saved_cases = list_cases()
    if saved_cases:
        for idx, c in enumerate(saved_cases[:8]):
            cid = c["case_id"]
            dx = (c.get("doctor_dx") or "").strip()
            sym = (c.get("patient", {}).get("symptoms_text") or "").strip()
            raw_title = dx if dx and dx.lower() != "regular infection" else (sym or dx or "Consultation")
            short_title = (raw_title[:20] + "…") if len(raw_title) > 20 else raw_title
            
            created_ts = c.get("updated_at") or c.get("created_at") or ""
            date_str = ""
            if created_ts:
                try:
                    dt = datetime.fromisoformat(created_ts.split(".")[0])
                    today = datetime.now()
                    if dt.date() == today.date():
                        date_str = dt.strftime("%I:%M %p")
                    else:
                        date_str = dt.strftime("%b %d")
                except Exception:
                    date_str = ""

            msg_count = c.get("message_count", 0)
            is_active = (cid == st.session_state.current_case_id)
            
            icon = "▶ " if is_active else "🩺 "
            badge = f" ({msg_count} msgs)" if msg_count > 0 else ""
            btn_label = f"{icon}{short_title}{badge}"

            if st.button(
                btn_label,
                key=f"side_case_{cid}_{idx}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                help=f"Case ID: {cid}\nDiagnosis/Symptoms: {raw_title}\nMessages: {msg_count}\nUpdated: {created_ts}",
            ):
                load_saved_case(cid)

        if len(saved_cases) > 8:
            with st.expander(f"📂 More Past Consultations ({len(saved_cases) - 8})", expanded=False):
                for idx, c in enumerate(saved_cases[8:], start=8):
                    cid = c["case_id"]
                    dx = (c.get("doctor_dx") or "").strip()
                    sym = (c.get("patient", {}).get("symptoms_text") or "").strip()
                    title = dx or sym[:20] or "Case"
                    msg_c = c.get("message_count", 0)
                    if st.button(
                        f"📄 {title} ({msg_c} msgs)" if msg_c > 0 else f"📄 {title}",
                        key=f"side_case_{cid}_{idx}",
                        use_container_width=True,
                    ):
                        load_saved_case(cid)
    else:
        st.caption("No previous chats yet. Complete an initial check to save your consultations.")

    st.markdown("---")
    with st.expander("⚡ Try a Sample Case", expanded=False):
        if st.button("Case 1: Viral Upper Respiratory Infection", use_container_width=True):
            load_demo_case(1)
        if st.button("Case 2: Prolonged Cough / Tuberculosis Suspect", use_container_width=True):
            load_demo_case(2)
        if st.button("Case 3: Chronic Fatigue & Thirst / Diabetes Suspect", use_container_width=True):
            load_demo_case(3)

    st.markdown("---")
    st.markdown("#### 🔒 Privacy")
    st.caption("Medical records and chats are kept strictly within your local session and private database.")
    if st.button("🗑️ Delete My Data", use_container_width=True, type="secondary"):
        reset_all_data()

    st.markdown("---")
    st.caption("HealthAi • Evidence-Based Second Opinion")


def render_limitations_footer():
    """Render Section 7 Known Limitations & Disclosures footer."""
    st.markdown("---")
    st.markdown(
        """
        <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px 18px; margin-top: 20px; font-size: 0.82rem; color: #475569; line-height: 1.5;">
            <strong style="color: #1E293B;">⚠️ Clinical Disclosures & Known Limitations:</strong>
            <ul style="margin-top: 6px; margin-bottom: 0px; padding-left: 18px;">
                <li><strong>Not a Diagnostic Tool:</strong> HealthAi provides evidence-based second-opinion decision support. It does not provide a definitive diagnosis or replace qualified medical practitioners.</li>
                <li><strong>Input Quality Dependence:</strong> Accuracy depends directly on the completeness and clarity of entered symptoms and documents.</li>
                <li><strong>Scope of Evaluated Conditions:</strong> The deterministic rule engine evaluates 12 high-impact conditions; other findings receive cautious, generalized clinical guidance.</li>
                <li><strong>Imaging Limitations:</strong> Extracts text from lab and radiology summaries, but does not interpret raw DICOM imaging or pathology slides.</li>
                <li><strong>OCR Confirmation Requirement:</strong> Machine OCR can occasionally misread values. Users must verify extracted values on the editable review screen.</li>
                <li><strong>Clinical Review:</strong> All knowledge bases and reference thresholds require institutional clinical validation before real-world deployment.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# SCREEN 1: DESCRIBE + UPLOAD (~800px Centered, Compact)
# ==============================================================================
if st.session_state.page == "intake":
    # Mandatory Safety Notice Pill
    cur_disclaimer = DISCLAIMER_MAP.get(st.session_state.language, DISCLAIMER_TEXT)
    st.markdown(
        f"""
        <div class="disclaimer-card" style="margin-top: 0px; margin-bottom: 14px;">
            <strong>Notice:</strong> {cur_disclaimer}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # CARD 1: About you (Age, Sex, Duration in one row)
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">👤 About You</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            age = st.number_input(
                "Age",
                min_value=1,
                max_value=120,
                value=int(st.session_state.patient_input["age"]),
                key="input_age",
            )
        with c2:
            sex_options = ["Female", "Male", "Other"]
            curr_sex = st.session_state.patient_input["sex"]
            s_idx = sex_options.index(curr_sex) if curr_sex in sex_options else 0
            sex = st.selectbox("Sex", options=sex_options, index=s_idx, key="input_sex")
        with c3:
            duration = st.number_input(
                "Symptom Days",
                min_value=1,
                max_value=365,
                value=int(st.session_state.patient_input["duration_days"]),
                key="input_duration",
            )

    # CARD 2: Your symptoms
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">🩺 Your Symptoms</div>', unsafe_allow_html=True)
        symptoms = st.text_area(
            "Current Symptoms (Describe what you are experiencing)*",
            value=st.session_state.patient_input["symptoms_text"],
            placeholder="e.g. Persistent dry cough for 3 weeks, evening fever, chills, fatigue, unintentional weight loss...",
            height=95,
            key="input_symptoms",
            label_visibility="collapsed",
        )

    # CARD 3: What did your doctor say?
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">👨‍⚕️ What Did Your Doctor Say?</div>', unsafe_allow_html=True)
        st.markdown("<div style='font-size: 0.88rem; font-weight: 600; color: #475569; margin-bottom: 4px;'>Doctor's Stated Diagnosis or Suspected Condition:</div>", unsafe_allow_html=True)
        doctor_dx = st.text_input(
            "Doctor's stated diagnosis",
            value=st.session_state.patient_input.get("doctor_dx", ""),
            placeholder="e.g. viral fever, chest infection, regular infection, bronchitis...",
            key="input_dx",
            label_visibility="collapsed",
        )
        st.markdown("<div style='font-size: 0.88rem; font-weight: 600; color: #475569; margin-top: 12px; margin-bottom: 4px;'>💊 Prescribed Medications (Optional):</div>", unsafe_allow_html=True)
        doctor_rx = st.text_area(
            "Prescribed medications",
            value=st.session_state.patient_input.get("prescription_text", ""),
            placeholder="e.g. Tab. Paracetamol 650 mg SOS, Tab. Amoxicillin 500 mg TID for 5 days, Cough syrup...",
            height=70,
            key="input_rx",
            label_visibility="collapsed",
        )

    # CARD 4: Documents and pictures (optional)
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">📁 Documents and Pictures (Optional)</div>', unsafe_allow_html=True)
        uploaded_files = st.file_uploader(
            "Upload lab reports, prescriptions, or photos",
            type=["pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"],
            accept_multiple_files=True,
            key="file_uploader",
            label_visibility="collapsed",
        )

        with st.expander("📷 Capture Photo with Device Camera", expanded=False):
            camera_photo = st.camera_input("Take a photo of prescription or report")
            if camera_photo:
                cam_name = f"camera_capture_{len(st.session_state.uploaded_files_data)+1}.png"
                if not any(f["name"] == cam_name for f in st.session_state.uploaded_files_data):
                    extracted_cam = read_file(camera_photo)
                    detected_cam_type = classify_document(extracted_cam.get("text", ""))
                    st.session_state.uploaded_files_data.append({
                        "id": f"cam_{len(st.session_state.uploaded_files_data)}",
                        "name": cam_name,
                        "type": detected_cam_type,
                        "text": extracted_cam.get("text", ""),
                        "file_obj": camera_photo,
                    })

        # Process newly uploaded files
        if uploaded_files:
            for uf in uploaded_files:
                if not any(f["name"] == uf.name for f in st.session_state.uploaded_files_data):
                    extracted = read_file(uf)
                    detected_type = classify_document(extracted.get("text", ""))
                    st.session_state.uploaded_files_data.append({
                        "id": f"file_{len(st.session_state.uploaded_files_data)}_{uf.name}",
                        "name": uf.name,
                        "type": detected_type,
                        "text": extracted.get("text", ""),
                        "file_obj": uf,
                    })

        # Show list of uploaded files with detected-type dropdown and remove button
        if st.session_state.uploaded_files_data:
            st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
            files_to_remove = []
            doc_categories = [
                "lab_report",
                "prescription",
                "discharge_summary",
                "imaging_report",
                "symptom_photo",
                "other",
            ]
            for idx, file_item in enumerate(st.session_state.uploaded_files_data):
                c_name, c_type, c_del = st.columns([3, 2, 0.7])
                with c_name:
                    st.markdown(f"📄 **{file_item['name']}**")
                with c_type:
                    curr_type = file_item.get("type", "other")
                    type_idx = doc_categories.index(curr_type) if curr_type in doc_categories else 5
                    new_type = st.selectbox(
                        f"Type for {file_item['name']}",
                        options=doc_categories,
                        index=type_idx,
                        key=f"type_select_{file_item['id']}",
                        label_visibility="collapsed",
                    )
                    file_item["type"] = new_type
                with c_del:
                    if st.button("🗑️", key=f"del_{file_item['id']}", help="Remove file"):
                        files_to_remove.append(idx)

            if files_to_remove:
                for idx in sorted(files_to_remove, reverse=True):
                    st.session_state.uploaded_files_data.pop(idx)
                st.rerun()


    # Large Button: Next: Review
    if st.button("Next: Review →", type="primary", use_container_width=True):
        if not symptoms.strip():
            st.error("Please enter your current symptoms to continue.")
        else:
            st.session_state.patient_input["age"] = age
            st.session_state.patient_input["sex"] = sex
            st.session_state.patient_input["duration_days"] = duration
            st.session_state.patient_input["symptoms_text"] = symptoms
            st.session_state.patient_input["doctor_dx"] = doctor_dx
            st.session_state.patient_input["prescription_text"] = doctor_rx
            st.session_state.patient_input["language"] = st.session_state.language

            with st.spinner("Extracting clinical data from symptoms and documents..."):
                # 1. Structure symptoms
                symptoms_struct = structure_symptoms(symptoms, duration)

                # 2. Extract labs
                lab_texts = [
                    f["text"] for f in st.session_state.uploaded_files_data
                    if f.get("type") == "lab_report" and f.get("text")
                ]
                combined_lab = "\n\n".join(lab_texts)
                labs_struct = structure_report(combined_lab) if combined_lab else []

                # 3. Extract prescriptions from typed prescription + uploaded documents
                rx_sources = []
                if doctor_rx.strip():
                    rx_sources.append(doctor_rx.strip())
                for f in st.session_state.uploaded_files_data:
                    if f.get("text") and f.get("type") in ("prescription", "doctor_notes_or_discharge_summary", "other"):
                        rx_sources.append(f["text"])

                # If user typed medicine names in doctor_dx or symptoms, include for fallback extraction
                if any(k in doctor_dx.lower() for k in ["tab", "cap", "mg", "rx", "syrup", "amox", "paracetamol", "antibiotic"]):
                    rx_sources.append(doctor_dx)
                if any(k in symptoms.lower() for k in ["tab", "cap", "mg", "rx", "syrup", "prescribed"]):
                    rx_sources.append(symptoms)

                combined_rx = "\n\n".join(rx_sources)
                rx_struct = structure_prescription(combined_rx) if combined_rx.strip() else []

                st.session_state.extracted_data = {
                    "symptoms": symptoms_struct,
                    "labs": labs_struct,
                    "prescriptions": rx_struct,
                }
                st.session_state.page = "review"
                st.rerun()

    render_limitations_footer()


# ==============================================================================
# SCREEN 2: REVIEW (Editable Tables, Consent Checkbox, Large Analyze Button)
# ==============================================================================
elif st.session_state.page == "review":
    st.markdown(
        """
        <div class="pulse-hero">
            <h1>Review Extracted Data</h1>
            <p>Verify or adjust the extracted clinical details before running the second-opinion assessment.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    data = st.session_state.extracted_data or {"symptoms": {}, "labs": [], "prescriptions": []}

    # Table 1: Symptoms
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">🩺 Extracted Symptoms</div>', unsafe_allow_html=True)
        raw_symptoms = data.get("symptoms", {}).get("symptoms", [])
        symptoms_df = pd.DataFrame([{"Present": True, "Symptom": s} for s in raw_symptoms])
        if symptoms_df.empty:
            symptoms_df = pd.DataFrame(columns=["Present", "Symptom"])

        edited_symptoms_df = st.data_editor(
            symptoms_df,
            num_rows="dynamic",
            use_container_width=True,
            key="edit_symptoms_table",
        )

    # Table 2: Lab Results
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">🧪 Extracted Lab Results</div>', unsafe_allow_html=True)
        raw_labs = data.get("labs", [])
        if raw_labs:
            labs_df = pd.DataFrame(raw_labs)
            for col in ["test", "value", "unit", "ref_low", "ref_high"]:
                if col not in labs_df.columns:
                    labs_df[col] = None
            labs_df = labs_df[["test", "value", "unit", "ref_low", "ref_high"]]
        else:
            labs_df = pd.DataFrame(columns=["test", "value", "unit", "ref_low", "ref_high"])

        edited_labs_df = st.data_editor(
            labs_df,
            num_rows="dynamic",
            use_container_width=True,
            key="edit_labs_table",
        )

    # Table 3: Prescriptions & Medications
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">💊 Extracted Prescriptions</div>', unsafe_allow_html=True)
        raw_rx = data.get("prescriptions", [])
        if raw_rx:
            rx_df = pd.DataFrame(raw_rx)
            for col in ["drug", "dose", "frequency", "duration"]:
                if col not in rx_df.columns:
                    rx_df[col] = None
            rx_df = rx_df[["drug", "dose", "frequency", "duration"]]
        else:
            rx_df = pd.DataFrame(columns=["drug", "dose", "frequency", "duration"])

        edited_rx_df = st.data_editor(
            rx_df,
            num_rows="dynamic",
            use_container_width=True,
            key="edit_rx_table",
        )

    # Consent Checkbox
    with st.container(border=True):
        consent = st.checkbox(
            "I confirm this extracted clinical information accurately reflects my records, and understand that HealthAi provides informational second-opinion evaluation, not a definitive diagnosis or medical prescription.",
            key="consent_checkbox",
        )

    # Actions: Back link + One Large "Analyze" Button
    c_back, c_analyze = st.columns([1, 2])
    with c_back:
        if st.button("← Back to Describe & Upload", use_container_width=True):
            st.session_state.page = "intake"
            st.rerun()

    with c_analyze:
        analyze_btn = st.button(
            "Analyze & Generate Second Opinion 🚀",
            type="primary",
            use_container_width=True,
            disabled=not consent,
        )

    if analyze_btn:
        with st.spinner("Analyzing findings, matching evidence, and applying safety rules..."):
            confirmed_symptoms = [
                row["Symptom"] for _, row in edited_symptoms_df.iterrows()
                if row.get("Present", True) and str(row.get("Symptom", "")).strip()
            ]
            updated_symptoms_dict = {
                "symptoms": confirmed_symptoms,
                "duration_days": st.session_state.patient_input["duration_days"],
                "flags": data["symptoms"].get("flags", {}),
            }

            confirmed_labs = []
            for _, row in edited_labs_df.iterrows():
                test_str = str(row.get("test", "")).strip()
                if test_str and test_str.lower() != "nan":
                    confirmed_labs.append({
                        "test": test_str,
                        "value": row.get("value"),
                        "unit": str(row.get("unit", "")).strip() if pd.notna(row.get("unit")) else None,
                        "ref_low": float(row.get("ref_low")) if pd.notna(row.get("ref_low")) else None,
                        "ref_high": float(row.get("ref_high")) if pd.notna(row.get("ref_high")) else None,
                    })

            confirmed_rx = []
            for _, row in edited_rx_df.iterrows():
                drug_str = str(row.get("drug", "")).strip()
                if drug_str and drug_str.lower() != "nan":
                    confirmed_rx.append({
                        "drug": drug_str,
                        "dose": str(row.get("dose", "")).strip() if pd.notna(row.get("dose")) else None,
                        "frequency": str(row.get("frequency", "")).strip() if pd.notna(row.get("frequency")) else None,
                        "duration": str(row.get("duration", "")).strip() if pd.notna(row.get("duration")) else None,
                    })

            # Pipeline Analysis
            flagged_labs = flag_values(confirmed_labs)
            signals = extract_signals(updated_symptoms_dict, flagged_labs)
            doctor_dx = st.session_state.patient_input["doctor_dx"]
            verdict_data = match_conditions(signals, doctor_dx, flagged_labs, updated_symptoms_dict)

            drug_res = check_prescription(
                prescription_items=confirmed_rx,
                doctor_dx=doctor_dx,
                top_conditions=verdict_data.get("top_candidates", []),
                verdict=verdict_data.get("verdict", ""),
                doctor_dx_matched=verdict_data.get("doctor_dx_matched"),
            )
            drug_notes = drug_res.get("discussion_notes", [])

            raw_report = generate_report(
                verdict_data,
                st.session_state.patient_input,
                flagged_labs,
                drug_notes,
            )
            evidence_context = {
                "verdict_data": verdict_data,
                "patient_input": st.session_state.patient_input,
                "flagged_labs": flagged_labs,
                "structured_rx": confirmed_rx,
                "signals": list(signals),
            }
            final_report = review_safety(raw_report, evidence_context)

            # Persist Case to SQLite
            cid = st.session_state.current_case_id or f"case_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            st.session_state.current_case_id = cid
            st.session_state.final_report = final_report

            save_case({
                "case_id": cid,
                "patient": {
                    "age": st.session_state.patient_input["age"],
                    "sex": st.session_state.patient_input["sex"],
                    "duration_days": st.session_state.patient_input.get("duration_days", 3),
                    "symptoms_text": st.session_state.patient_input.get("symptoms_text", ""),
                },
                "doctor_dx": doctor_dx,
                "symptom_timeline": [
                    {"symptom": s, "onset": "Initial visit", "status": "active"}
                    for s in confirmed_symptoms
                ],
                "events": [{
                    "event_id": f"ev_{cid}",
                    "date": datetime.now().isoformat(),
                    "type": "initial_assessment",
                    "summary": f"Initial assessment: Verdict {final_report['verdict']}, Urgency {final_report['urgency']}",
                    "details": final_report,
                }],
                "labs": confirmed_labs,
                "medicines": confirmed_rx,
                "final_report": final_report,
                "last_verdict": final_report,
            })

            st.session_state.page = "result"
            st.rerun()

    render_limitations_footer()


# ==============================================================================
# SCREEN 3: RESULT + CHAT ON ONE SCREEN (Unified View)
# ==============================================================================
elif st.session_state.page == "result":
    report = st.session_state.final_report or {}
    verdict = report.get("verdict", "INCONCLUSIVE")
    urgency = report.get("urgency", "routine").lower()

    # 1. Urgent Banner (if rule-derived urgency is emergency or same_day)
    if urgency in ("emergency", "urgent"):
        st.markdown(
            """
            <div class="urgent-alert-banner">
                <span style="font-size: 1.5rem;">🚨</span>
                <div>
                    <strong>URGENT MEDICAL ATTENTION RECOMMENDED:</strong>
                    Severe red-flag findings or critical lab values require immediate same-day evaluation at an emergency care center.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif urgency == "same_day":
        st.markdown(
            """
            <div class="urgent-alert-banner" style="background: #FFFBEB; border-color: #F59E0B; color: #92400E;">
                <span style="font-size: 1.5rem;">⚠️</span>
                <div>
                    <strong>PROMPT EVALUATION RECOMMENDED:</strong>
                    Some findings are not fully explained by the initial diagnosis. Consult your doctor or specialist soon.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 2. Large Colored Verdict Card with Summary
    if verdict == "AGREE":
        banner_class = "verdict-banner-agree"
        badge_text = "🟢 VERDICT: AGREE"
    elif verdict == "ESCALATE":
        banner_class = "verdict-banner-escalate"
        badge_text = "🔴 VERDICT: ESCALATE (Specialist Evaluation Recommended)"
    else:
        banner_class = "verdict-banner-inconclusive"
        badge_text = "⚪ VERDICT: INCONCLUSIVE"

    st.markdown(
        f"""
        <div class="{banner_class}">
            <div style="font-size: 0.85rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.9;">
                {badge_text} • URGENCY: {urgency.upper()}
            </div>
            <div style="font-size: 1.35rem; font-weight: 700; margin-top: 8px; line-height: 1.4;">
                {report.get("summary", "")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3. Two Columns: Tests to Confirm / Specialist to Consult
    col_tests, col_spec = st.columns([1, 1])
    with col_tests:
        with st.container(border=True):
            st.markdown('<div class="ha-card-title">🧪 Confirmatory Tests</div>', unsafe_allow_html=True)
            tests = report.get("tests_to_confirm", [])
            if tests:
                for t in tests:
                    st.markdown(f"• **{t}**")
            else:
                st.write("Clinical observation and monitoring advised.")

    with col_spec:
        with st.container(border=True):
            st.markdown('<div class="ha-card-title">👨‍⚕️ Specialist to Consult</div>', unsafe_allow_html=True)
            specialist = report.get("specialist_to_consult", "General Physician")
            st.markdown(f"**Recommended:** {specialist}")
            st.caption("Share this assessment and confirmatory test list with your specialist.")

    # 4. Collapsed Sections (Evidence, Medicine Notes, Warning Signs, Questions)
    with st.expander("🔍 Clinical Evidence & Rationale", expanded=False):
        why_items = report.get("why", [])
        if why_items:
            for w in why_items:
                st.markdown(f"• {w}")
        possible = report.get("possible_conditions", [])
        if possible:
            st.markdown("##### Candidate Conditions Considered:")
            for p in possible:
                st.markdown(f"- **{p['name']}** ({p.get('confidence', 'medium').capitalize()} confidence): {p.get('why_possible', '')}")

    with st.expander("💊 Prescription & Medication Discussion Points", expanded=False):
        p_notes = report.get("prescription_notes", [])
        if p_notes:
            for pn in p_notes:
                st.markdown(f"• 💬 {pn}")
        else:
            st.write("No major medication interactions or indication gaps flagged. Take medicines as prescribed.")

    with st.expander("⚠️ Red Flag Warning Signs to Watch", expanded=False):
        warning_signs = report.get("warning_signs", [])
        for ws in warning_signs:
            st.markdown(f"• 🚩 {ws}")

    with st.expander("❓ Questions for Your Doctor", expanded=False):
        questions = report.get("questions_for_doctor", [])
        for q in questions:
            st.markdown(f"• ❓ {q}")

    # 5. Mandatory Medical Disclaimer
    disclaimer_text = report.get("disclaimer", DISCLAIMER_MAP.get(st.session_state.language, DISCLAIMER_TEXT))
    st.markdown(
        f"""
        <div class="disclaimer-card">
            <strong>Mandatory Medical Notice:</strong> {disclaimer_text}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 6. Action Buttons: Download PDF and New Check
    c_pdf, c_new = st.columns([1, 1])
    with c_pdf:
        current_case = get_case(st.session_state.current_case_id) if st.session_state.current_case_id else None
        case_state_for_pdf = current_case or {
            "case_id": st.session_state.current_case_id or "summary",
            "patient": st.session_state.patient_input,
            "doctor_dx": st.session_state.patient_input.get("doctor_dx", ""),
            "events": [],
        }
        pdf_bytes = generate_pdf_report(case_state_for_pdf, report)
        st.download_button(
            label="📥 Download PDF Report",
            data=pdf_bytes,
            file_name=f"HealthAi_Report_{st.session_state.current_case_id[:8] if st.session_state.current_case_id else 'Summary'}.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )
    with c_new:
        if st.button("➕ New Check", use_container_width=True):
            st.session_state.page = "intake"
            st.session_state.final_report = None
            st.session_state.current_case_id = None
            st.session_state.uploaded_files_data = []
            st.rerun()

    # Optional: Repeated Lab Trend Figures if available
    if current_case:
        case_labs = current_case.get("labs", [])
        trend_figs = build_lab_trend_figures(case_labs)
        if trend_figs:
            st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
            with st.expander("📈 Longitudinal Laboratory Trends", expanded=True):
                for tf in trend_figs:
                    st.plotly_chart(tf["figure"], use_container_width=True)

    # 7. Follow-Up Chat (Directly Below on the Same Screen)
    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="ha-card-title">💬 Follow-Up Chat & Case Assistant</div>', unsafe_allow_html=True)
        st.caption("Returning days later? Report what has changed, attach new reports, or ask how your recovery is progressing.")

        if st.session_state.current_case_id:
            # Prior chat history (Up to 50 messages)
            msgs = get_case_messages(st.session_state.current_case_id, limit=50)
            if msgs:
                for m in msgs:
                    with st.chat_message(m["role"], avatar="🩺" if m["role"] == "assistant" else "👤"):
                        if m["role"] == "assistant":
                            try:
                                parsed = json.loads(m["content"])
                                # Display direct conversational answer to user's question
                                answer_text = parsed.get("answer") or parsed.get("conversational_reply") or parsed.get("assessment", "")
                                if answer_text:
                                    st.markdown(answer_text)
                                else:
                                    st.markdown(m["content"])
                            
                                # Show clinical trajectory badge if noteworthy
                                traj = parsed.get("trajectory")
                                if traj and traj in ("NOT_IMPROVING", "NEW_CONCERN", "URGENT"):
                                    badge_emoji = "🚨" if traj == "URGENT" else "⚠️"
                                    st.markdown(f"{badge_emoji} **Clinical Trajectory:** `{traj}`")
                            
                                if parsed.get("treatment_review_needed"):
                                    st.warning(f"**Re-evaluation Advised:** {parsed.get('treatment_review_reason', '')}")
                            
                                # Show practical questions to ask doctor if available
                                q_doc = parsed.get("questions_for_doctor")
                                if q_doc and isinstance(q_doc, list) and len(q_doc) > 0 and "re-evaluation" in q_doc[0].lower():
                                    with st.expander("📋 Questions to discuss with your doctor", expanded=False):
                                        for q in q_doc:
                                            st.markdown(f"• {q}")
                            except Exception:
                                st.markdown(m["content"])
                        else:
                            st.markdown(m["content"])

            # Chat message input
            follow_text = st.text_area(
                "Ask questions about your condition or report recovery progress",
                placeholder="e.g. Can I drink warm tea? / Day 5: Fever persists and now I have right ear pain...",
                height=80,
                key="follow_up_input",
                label_visibility="collapsed",
            )

            with st.expander("📎 Attach New Lab Report, Prescription, or Photo", expanded=False):
                follow_attachments = st.file_uploader(
                    "Attach follow-up document",
                    type=["pdf", "png", "jpg", "jpeg", "webp", "docx", "txt"],
                    accept_multiple_files=True,
                    key="follow_up_uploader",
                    label_visibility="collapsed",
                )
                if follow_attachments:
                    st.info(f"{len(follow_attachments)} file(s) attached to follow-up update.")

            if st.button("💬 Send Message or Update", type="primary", use_container_width=True):
                if not follow_text.strip():
                    st.error("Please enter a message describing what has changed.")
                else:
                    with st.spinner("Reviewing your complete case context and responding..."):
                        if not st.session_state.current_case_id:
                            st.session_state.current_case_id = f"case_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        session_context = {
                            "patient": st.session_state.patient_input,
                            "doctor_dx": st.session_state.patient_input.get("doctor_dx", ""),
                            "extracted_data": st.session_state.extracted_data,
                            "final_report": st.session_state.final_report,
                        }
                        follow_reply = followup(
                            case_id=st.session_state.current_case_id,
                            user_message=follow_text,
                            new_files=follow_attachments,
                            case_context=session_context,
                        )
                        st.rerun()


    render_limitations_footer()
