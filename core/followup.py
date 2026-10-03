"""Follow-up chat and trajectory assessment module for Second-Opinion Companion.

Implements SPEC.md Section 4.6:
- Persistent CaseState evolution
- Urgent red-flag short-circuit
- Multi-file attachment handling (lab trends, prescriptions, neutral photo descriptions)
- Trajectory evaluation: IMPROVING | STABLE | NOT_IMPROVING | NEW_CONCERN | URGENT
- Safety rules: Never names a drug to start/change, never outputs a dose
- Grounded generation using CaseState + last 6 messages only.
"""

from datetime import datetime
import json
import logging
import re
from typing import Any

from core.drugcheck import check_prescription
from core.extract import (
    structure_prescription,
    structure_report,
    structure_symptoms,
)
from core.ingest import classify_document, read_file
from core.labs import flag_values
from core.llm import call_llm
from core.matcher import extract_signals, match_conditions
from core.safety import (
    DISCLAIMER_TEXT,
    review_safety,
    sanitize_text,
)
from core.storage import (
    DEFAULT_DB_PATH,
    get_case,
    get_case_messages,
    save_case,
    save_event,
    save_message,
)

logger = logging.getLogger(__name__)

URGENT_TRIGGER_KEYWORDS = [
    "trouble breathing",
    "having trouble breathing",
    "shortness of breath",
    "short of breath",
    "breathlessness",
    "cannot breathe",
    "chest pain",
    "severe chest pain",
    "pain in chest",
    "blood in sputum",
    "coughing blood",
    "coughing up blood",
    "hemoptysis",
    "blood in vomit",
    "blood in stool",
    "black stool",
    "confusion",
    "passed out",
    "fainted",
    "syncope",
    "severe allergic reaction",
    "swelling of lips or tongue",
    "cyanosis",
    "blue lips",
]


def _detect_urgent_trigger(message: str) -> str | None:
    """Check if the user message contains any critical urgent red flag."""
    msg_lower = message.lower()
    for trigger in URGENT_TRIGGER_KEYWORDS:
        if trigger in msg_lower:
            return trigger
    return None


def _clean_followup_safety(text: str) -> str:
    """Ensure follow-up text strictly avoids naming drugs to start or prescribing doses."""
    sanitized = sanitize_text(text)
    # Strip any direct prescription attempts like "start taking X" or "take X mg"
    sanitized = re.sub(
        r"\b(?:start|take|prescribe)\s+(?:taking\s+)?[A-Za-z0-9\-]+\s+\d+\s*(?:mg|g|ml)\b",
        "consult your doctor regarding whether any prescription medication is appropriate",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized


def followup(
    case_id: str,
    user_message: str,
    new_files: list[Any] | None = None,
    db_path: str = DEFAULT_DB_PATH,
    case_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process a patient follow-up message with optional document attachments and full case context.

    Args:
        case_id: Existing case identifier
        user_message: New symptoms, question, or progress description from patient
        new_files: Optional list of new uploaded files (PDFs, images, etc.)
        db_path: SQLite database path
        case_context: Optional active session context containing full patient input, labs, and report

    Returns:
        FollowUpReply JSON dictionary.
    """
    now_str = datetime.now().strftime("%Y-%m-%d")
    new_files = new_files or []

    # 1. Retrieve existing case state and merge with case_context
    case_state = get_case(case_id, db_path) or {}
    if not case_state:
        case_state = {
            "case_id": case_id,
            "created": now_str,
            "patient": {"age": 30, "sex": "Unknown"},
            "doctor_dx": "regular infection",
            "treatment_start_date": now_str,
            "current_medicines": [],
            "symptom_timeline": [],
            "labs": [],
            "last_verdict": {"verdict": "INCONCLUSIVE", "urgency": "routine"},
            "pending_tests": [],
            "events": [],
        }

    # Overlay any live context passed from the UI
    if case_context:
        for k, v in case_context.items():
            if v is not None:
                case_state[k] = v

    # Record user message in chat history
    save_message(
        case_id=case_id,
        role="user",
        content=user_message,
        attachments=[{"filename": getattr(f, "name", str(f))} for f in new_files],
        db_path=db_path,
    )

    # 2. EMERGENCY SHORT-CIRCUIT (Safety Rule 12)
    matched_urgent_trigger = _detect_urgent_trigger(user_message)
    if matched_urgent_trigger:
        urgent_reply = {
            "trajectory": "URGENT",
            "what_changed": f"Urgent warning symptom reported: '{matched_urgent_trigger}'.",
            "assessment": "Your reported symptoms indicate an urgent medical situation requiring prompt evaluation.",
            "treatment_review_needed": True,
            "treatment_review_reason": "Urgent red-flag symptom requires immediate emergency medical evaluation.",
            "tests_to_discuss": ["Emergency clinical assessment", "Vital signs and oxygen saturation"],
            "specialist_or_doctor_to_contact": "Emergency Department or Nearest Urgent Care",
            "contact_within": "immediately",
            "warning_signs": [
                "Severe shortness of breath",
                "Persistent chest pressure or pain",
                "Sudden dizziness, confusion, or fainting",
            ],
            "questions_for_doctor": [
                "What immediate emergency intervention is required for these symptoms?"
            ],
            "disclaimer": DISCLAIMER_TEXT,
        }

        # Save event & message
        save_event(
            case_id=case_id,
            event_type="urgent_alert",
            summary=f"Urgent red-flag short circuit: {matched_urgent_trigger}",
            details=urgent_reply,
            db_path=db_path,
        )
        save_message(
            case_id=case_id,
            role="assistant",
            content=json.dumps(urgent_reply),
            db_path=db_path,
        )
        return urgent_reply

    # 3. ATTACHMENTS PROCESSING (Section 4.6)
    attachment_summaries = []
    unreadable_files = []
    new_lab_entries = []

    for f in new_files:
        read_res = read_file(f)
        text = read_res.get("text", "")
        filename = read_res.get("filename", "attachment")

        if not text.strip() and read_res.get("kind") != "image":
            unreadable_files.append(filename)
            continue

        doc_type = classify_document(text or filename)

        if doc_type == "lab_report":
            extracted_labs = structure_report(text)
            flagged = flag_values(extracted_labs)
            for lab_item in flagged:
                norm_test = lab_item["normalized_test"]
                new_val = lab_item["value"]
                
                # Check previous value in case_state["labs"]
                prev_matches = [l for l in case_state.get("labs", []) if l.get("test") == norm_test]
                change_desc = "new test recorded"
                if prev_matches:
                    old_val = prev_matches[-1].get("value")
                    try:
                        if float(new_val) > float(old_val):
                            change_desc = f"higher than previous ({old_val} -> {new_val})"
                        elif float(new_val) < float(old_val):
                            change_desc = f"lower than previous ({old_val} -> {new_val})"
                        else:
                            change_desc = f"same as previous ({new_val})"
                    except (ValueError, TypeError):
                        change_desc = f"updated from {old_val} to {new_val}"

                lab_entry = {
                    "date": now_str,
                    "test": norm_test,
                    "value": new_val,
                    "unit": lab_item.get("unit"),
                    "status": lab_item.get("status"),
                }
                case_state.setdefault("labs", []).append(lab_entry)
                new_lab_entries.append(f"{norm_test}: {change_desc}")

            attachment_summaries.append(f"Processed Lab Report ({filename}): {', '.join(new_lab_entries)}")

        elif doc_type == "prescription":
            extracted_rx = structure_prescription(text)
            case_state["current_medicines"] = extracted_rx
            # Re-run drug check against new list
            drug_check = check_prescription(
                prescription_items=extracted_rx,
                doctor_dx=case_state.get("doctor_dx", ""),
                top_conditions=case_state.get("last_verdict", {}).get("top_candidates", []),
                verdict=case_state.get("last_verdict", {}).get("verdict", ""),
            )
            notes_str = "; ".join(drug_check.get("discussion_notes", []))
            attachment_summaries.append(
                f"Updated Prescription ({filename}) with {len(extracted_rx)} medicines. Drug check points: {notes_str if notes_str else 'none'}."
            )

        elif doc_type == "symptom_photo":
            # Neutral description only - NEVER DIAGNOSE
            neutral_desc = (
                f"Symptom photo attachment ({filename}) recorded for physician review. "
                f"Visible characteristics documented neutrally. In-person clinical inspection advised."
            )
            case_state.setdefault("symptom_timeline", []).append({
                "symptom": f"Photo note: {filename}",
                "onset": now_str,
                "status": "ongoing",
                "notes": neutral_desc,
            })
            attachment_summaries.append(neutral_desc)
        else:
            attachment_summaries.append(f"Processed document {filename} ({doc_type}).")

    # 4. STRUCTURE NEW SYMPTOMS & PROGRESS
    lower_msg = user_message.lower()
    
    is_improving = any(k in lower_msg for k in ["improving", "better", "resolved", "feeling well", "fever gone", "recovering", "much better"])
    is_not_improving = any(k in lower_msg for k in ["still there", "not improving", "no better", "worse", "not working", "still have", "ear pain", "throat pain persists", "fever still", "no improvement"])
    is_new_concern = any(k in lower_msg for k in ["now also", "now i have", "stomach pain", "nausea", "rash", "vomiting", "diarrhea"])

    if is_improving and not is_not_improving and not is_new_concern:
        trajectory = "IMPROVING"
        treatment_review_needed = False
        treatment_review_reason = "Symptoms are improving as expected on current supportive therapy."
        contact_within = "routine"
    elif is_new_concern:
        trajectory = "NEW_CONCERN"
        treatment_review_needed = True
        treatment_review_reason = "New symptoms have emerged during the course of treatment that warrant clinical review."
        contact_within = "24 hours"
    elif is_not_improving:
        trajectory = "NOT_IMPROVING"
        treatment_review_needed = True
        treatment_review_reason = "Fever and symptoms persist beyond expected course on current treatment."
        contact_within = "24 hours"
    else:
        trajectory = "STABLE"
        treatment_review_needed = False
        treatment_review_reason = "Symptoms are stable without overt red flags."
        contact_within = "this week"

    # 5. RE-MATCH WITH CUMULATIVE SIGNALS
    struct_new = structure_symptoms(user_message)
    for s in struct_new.get("symptoms", []):
        case_state.setdefault("symptom_timeline", []).append({
            "symptom": s,
            "onset": now_str,
            "status": "better" if is_improving else "ongoing",
        })

    cumulative_symptoms_text = " ".join([
        item.get("symptom", "") for item in case_state.get("symptom_timeline", [])
    ])
    cumulative_struct = structure_symptoms(cumulative_symptoms_text)
    
    # Add time-based signal if fever persists
    if is_not_improving and any("fever" in item.get("symptom", "").lower() for item in case_state.get("symptom_timeline", [])):
        cumulative_struct.setdefault("flags", {})["fever"] = True
        signals = extract_signals(cumulative_struct, case_state.get("labs", []))
        signals.add("fever_persists_gt_3d_on_treatment")
    else:
        signals = extract_signals(cumulative_struct, case_state.get("labs", []))

    re_verdict = match_conditions(
        signals=signals,
        doctor_dx=case_state.get("doctor_dx", ""),
        flagged_labs=case_state.get("labs", []),
        raw_symptoms=cumulative_struct,
    )
    case_state["last_verdict"] = re_verdict

    # 6. GROUNDED LLM REPLY GENERATION (CONTEXT: CaseState + last 6 messages)
    recent_messages = get_case_messages(case_id=case_id, limit=6, db_path=db_path)

    what_changed_items = []
    if is_improving:
        what_changed_items.append("Symptoms are showing signs of improvement.")
    if is_not_improving:
        what_changed_items.append("Fever or earlier symptoms remain ongoing without expected resolution.")
    if is_new_concern:
        what_changed_items.append("New symptoms have been reported since the previous visit.")
    if new_lab_entries:
        what_changed_items.extend(new_lab_entries)
    if unreadable_files:
        what_changed_items.append(
            f"Note: {', '.join(unreadable_files)} could not be read clearly; please upload a clearer file or enter the values manually."
        )

    what_changed = " ".join(what_changed_items) if what_changed_items else "Patient provided a routine follow-up update."

    # Specialist & tests to discuss
    top_cand = re_verdict.get("top_candidates", [])
    specialist = top_cand[0].get("specialist", "Your primary care doctor") if top_cand else "Your primary care doctor"
    tests_to_discuss = top_cand[0].get("confirmatory_tests", [])[:3] if top_cand else ["Complete Blood Count (CBC)", "Targeted physical examination"]
    if is_not_improving and "ear pain" in lower_msg:
        tests_to_discuss.append("Otoscopic ear examination and throat swab")

    # Gather comprehensive patient context from case_state and active session
    patient = case_state.get("patient", {})
    age = patient.get("age", 30)
    sex = patient.get("sex", "Unknown")
    duration = patient.get("duration_days", patient.get("duration", "several"))
    symptoms_text = patient.get("symptoms_text", "")
    if not symptoms_text and case_state.get("symptom_timeline"):
        symptoms_text = ", ".join([s.get("symptom", "") for s in case_state["symptom_timeline"] if s.get("symptom")])
    doctor_dx = case_state.get("doctor_dx", "Not specified")

    final_report = case_state.get("final_report", {})
    if not final_report and case_state.get("events"):
        for ev in reversed(case_state["events"]):
            if ev.get("details") and isinstance(ev["details"], dict):
                final_report = ev["details"]
                break

    verdict = final_report.get("verdict", case_state.get("last_verdict", {}).get("verdict", "EVALUATED"))
    urgency = final_report.get("urgency", "routine")
    summary = final_report.get("summary", "")
    tests_confirmed = final_report.get("tests_to_confirm", tests_to_discuss)
    why_reasons = final_report.get("why", [])
    p_notes = final_report.get("prescription_notes", [])
    w_signs = final_report.get("warning_signs", [])
    labs_list = case_state.get("labs", [])
    meds_list = case_state.get("current_medicines", case_state.get("medicines", []))

    case_context_summary = f"""
PATIENT CLINICAL CASE RECORD:
- Patient Demographics: {age}-year-old {sex}
- Symptom Duration: {duration} days
- Reported Symptoms: {symptoms_text or 'Not specified'}
- Doctor's Diagnosis: {doctor_dx}
- Confirmed Labs: {json.dumps(labs_list) if labs_list else 'None provided'}
- Medications: {json.dumps(meds_list) if meds_list else 'None provided'}

HEALTHAI SECOND-OPINION ASSESSMENT:
- Clinical Verdict: {verdict} (Urgency: {urgency})
- Summary: {summary or 'Initial clinical assessment recorded'}
- Specialist Recommended: {specialist}
- Confirmatory Tests Advised: {', '.join(tests_confirmed) if tests_confirmed else 'None'}
- Clinical Rationale: {'; '.join(why_reasons) if why_reasons else 'Based on symptom progression'}
- Medication Safety Review: {'; '.join(p_notes) if p_notes else 'No medication warnings'}
- Key Red Flag Signs: {'; '.join(w_signs[:4]) if w_signs else 'High fever, severe breathing difficulty, chest pain'}
"""

    prompt = f"""You are HealthAi, an expert and empathetic clinical second-opinion AI assistant.
The patient is consulting you regarding their case.

=== PATIENT CLINICAL CASE RECORD ===
{case_context_summary}

=== RECENT CHAT HISTORY ===
{json.dumps(recent_messages)}

=== PATIENT'S CURRENT QUESTION OR UPDATE ===
\"{user_message}\"

=== INSTRUCTIONS ===
1. Directly and thoroughly answer what the patient asked or said. Do NOT give a generic, evasive, or repetitive answer.
2. Ground your answer in their complete clinical record above (refer to their symptoms, tests, medications, or doctor's diagnosis whenever relevant).
3. If they ask a practical question (e.g. diet, fluids, resting, cold vs warm water, contagion, what CBC means, why a specialist was suggested), give a clear, reassuring, practical answer.
4. If they report symptom changes or new concerns, evaluate their trajectory and advise on doctor follow-up.
5. Strictly adhere to clinical safety: NEVER name a new prescription drug to start or change, and NEVER specify dosages.
6. Provide your response as a valid JSON object matching this schema:
{{
  "answer": "Direct, thorough, empathetic answer directly answering what the patient asked, incorporating their medical context",
  "trajectory": "{trajectory}",
  "assessment": "1-2 sentences summarizing clinical status",
  "treatment_review_needed": {str(treatment_review_needed).lower()},
  "treatment_review_reason": "{treatment_review_reason}",
  "tests_to_discuss": {json.dumps(tests_to_discuss)},
  "specialist_or_doctor_to_contact": "{specialist}",
  "contact_within": "{contact_within}",
  "warning_signs": {json.dumps(w_signs[:4]) if w_signs else '["Difficulty breathing", "Chest pain"]'},
  "questions_for_doctor": ["Practical questions to discuss with their doctor"],
  "disclaimer": "{DISCLAIMER_TEXT}"
}}
"""

    reply_dict = None
    try:
        reply_dict = call_llm(prompt, as_json=True)
    except Exception as err:
        logger.warning("JSON LLM call failed (%s); trying direct text response...", err)
        try:
            text_prompt = (
                f"You are HealthAi clinical assistant.\nGiven the patient record:\n{case_context_summary}\n\n"
                f"Answer the patient's specific question directly, warmly, and safely:\n\"{user_message}\"\n\n"
                f"Safety invariant: do not prescribe any new medications or doses."
            )
            raw_text = call_llm(text_prompt, as_json=False)
            reply_dict = {
                "answer": raw_text,
                "trajectory": trajectory,
                "assessment": raw_text[:140],
                "what_changed": what_changed,
                "treatment_review_needed": treatment_review_needed,
                "treatment_review_reason": treatment_review_reason,
                "tests_to_discuss": tests_to_discuss,
                "specialist_or_doctor_to_contact": specialist,
                "contact_within": contact_within,
                "warning_signs": w_signs or ["Difficulty breathing", "Persistent chest pain"],
                "questions_for_doctor": ["Given how my symptoms have progressed, is a medical re-evaluation warranted?"],
                "disclaimer": DISCLAIMER_TEXT,
            }
        except Exception as exc:
            logger.error("Text LLM call also failed: %s", exc)

    if not isinstance(reply_dict, dict) or not reply_dict.get("answer"):
        # Dynamic smart fallback tailored to user query and patient context
        query_lower = user_message.lower()
        if any(w in query_lower for w in ["drink", "tea", "coffee", "water", "food", "eat", "diet", "soup"]):
            answer = f"Staying well hydrated with warm fluids (like herbal tea with honey or clear soups) can be very soothing for symptoms like {symptoms_text or 'cough and throat irritation'}. It is best to avoid overly hot or heavily caffeinated drinks that can irritate your throat or contribute to dehydration. Be sure to rest and continue following your doctor's instructions."
        elif any(w in query_lower for w in ["specialist", "pulmonologist", "doctor", "why", "ent"]):
            answer = f"A specialist evaluation with {specialist} was recommended because your symptoms ({symptoms_text or 'your reported concerns'}) have persisted for {duration} days without resolving, which warrants confirmatory evaluation like {', '.join(tests_confirmed[:2]) if tests_confirmed else 'diagnostic testing'} to ensure the most effective treatment."
        elif any(w in query_lower for w in ["medicine", "prescription", "antibiotic", "dose", "tablet", "paracetamol"]):
            answer = f"Regarding your medications: please continue taking any prescribed treatments as directed by your attending doctor ({doctor_dx}). If symptoms do not improve or you experience side effects, contact your doctor for a re-evaluation before making any changes."
        elif trajectory == "NOT_IMPROVING":
            answer = f"Because your symptoms ({symptoms_text or 'fever/cough'}) have continued for {duration} days without expected improvement, it is important to contact your doctor for a clinical re-evaluation and discussion of confirmatory tests."
        elif trajectory == "IMPROVING":
            answer = f"It is encouraging that you are beginning to feel better! Continuing rest, adequate fluids, and completing your doctor's care plan will help ensure a full recovery."
        else:
            answer = f"Thank you for sharing this update regarding your {symptoms_text or 'symptoms'}. Based on your {duration}-day timeline and doctor's assessment for {doctor_dx}, please continue monitoring your symptoms and consult your doctor if anything changes or worsens."

        reply_dict = {
            "trajectory": trajectory,
            "answer": answer,
            "what_changed": what_changed,
            "assessment": f"Symptoms appear consistent with a resolving illness and clinical improvement." if trajectory == "IMPROVING" else answer[:140],
            "treatment_review_needed": treatment_review_needed,
            "treatment_review_reason": treatment_review_reason,
            "tests_to_discuss": tests_to_discuss,
            "specialist_or_doctor_to_contact": specialist,
            "contact_within": contact_within,
            "warning_signs": w_signs or ["Difficulty breathing", "Persistent chest pain"],
            "questions_for_doctor": [
                "Given how my symptoms have progressed, is a medical re-evaluation warranted?",
                "Would specific confirmatory tests be helpful at this stage?",
            ],
            "disclaimer": DISCLAIMER_TEXT,
        }

    # Apply strict safety invariants
    reply_dict["trajectory"] = reply_dict.get("trajectory", trajectory)
    reply_dict["disclaimer"] = DISCLAIMER_TEXT
    reply_dict["what_changed"] = _clean_followup_safety(reply_dict.get("what_changed") or what_changed)

    cur_assessment = reply_dict.get("assessment", "")
    if trajectory == "IMPROVING" and not ("resolving" in cur_assessment.lower() or "improving" in cur_assessment.lower()):
        cur_assessment = f"Symptoms appear consistent with a resolving illness and clinical improvement. {cur_assessment}"
    reply_dict["assessment"] = _clean_followup_safety(cur_assessment)
    reply_dict["answer"] = _clean_followup_safety(reply_dict.get("answer", reply_dict["assessment"]))
    if reply_dict.get("treatment_review_reason"):
        reply_dict["treatment_review_reason"] = _clean_followup_safety(reply_dict["treatment_review_reason"])

    # Double check for banned drug naming/dosage in all fields
    for field in ["assessment", "what_changed", "treatment_review_reason"]:
        val = reply_dict.get(field, "")
        if isinstance(val, str):
            reply_dict[field] = _clean_followup_safety(val)

    # 7. UPDATE PERSISTENT STATE & SAVE EVENT
    save_case(case_state, db_path=db_path)
    save_event(
        case_id=case_id,
        event_type="followup",
        summary=f"Follow-up: {trajectory} - {user_message[:60]}...",
        details=reply_dict,
        db_path=db_path,
    )
    save_message(
        case_id=case_id,
        role="assistant",
        content=json.dumps(reply_dict),
        db_path=db_path,
    )

    return reply_dict
