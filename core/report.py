"""Report generation module for Second-Opinion Companion.

Synthesizes the deterministic verdict, evidence, lab flags, and prescription notes
into a grounded FinalReport JSON payload adhering strictly to Section 4.4 schema.
Supports English, Telugu, and Hindi translations.
"""

import json
import logging
from typing import Any

from core.llm import call_llm
from core.safety import DISCLAIMER_MAP, DISCLAIMER_TEXT

logger = logging.getLogger(__name__)


def generate_grounded_report_fallback(
    verdict_data: dict,
    patient_input: dict,
    flagged_labs: list[dict],
    drug_notes: list[str],
) -> dict[str, Any]:
    """Deterministic, grounded generation fallback when LLM is offline or unconfigured.

    Supports English, Telugu, and Hindi.
    """
    language = patient_input.get("language", "English")
    verdict = verdict_data.get("verdict", "INCONCLUSIVE")
    urgency = verdict_data.get("urgency", "routine")
    top_candidates = verdict_data.get("top_candidates", [])
    doctor_dx = patient_input.get("doctor_dx", "not specified")
    unexplained = verdict_data.get("unexplained_findings", [])
    top_name = top_candidates[0]["name"].replace("_", " ").title() if top_candidates else "an alternative condition"

    # Multilingual summaries & texts
    if language == "Telugu":
        if verdict == "AGREE":
            summary = (
                f"నివేదించబడిన ఫలితాలు మరియు క్లినికల్ ఆధారాలు మీ వైద్యుని {doctor_dx} అంచనాతో సరిపోలుతున్నాయి. "
                f"సాధారణంగా సహాయక సంరక్షణ మరియు హెచ్చరిక సంకేతాలను గమనించడం సిఫార్సు చేయబడింది."
            )
        elif verdict == "ESCALATE":
            unexplained_str = ", ".join(unexplained[:2]) if unexplained else "లక్షణాల వ్యవధి"
            summary = (
                f"కొన్ని క్లినికల్ ఫలితాలు ({unexplained_str} వంటివి) ప్రాథమిక నిర్ధారణ అయిన {doctor_dx} ద్వారా పూర్తిగా వివరించబడకపోవచ్చు. "
                f"సాధ్యమైన {top_name} కోసం మరింత సమగ్ర పరిశీలన సిఫార్సు చేయబడింది."
            )
        else:
            summary = (
                "అందుబాటులో ఉన్న సమాచారం ప్రస్తుతం పరిమితంగా లేదా అసంపూర్ణంగా ఉంది. "
                "మీ లక్షణాలను ఖచ్చితంగా అంచనా వేయడానికి అర్హత కలిగిన వైద్యుని సంప్రదించడం సిఫార్సు చేయబడింది."
            )

        warning_signs = [
            "శ్వాస తీసుకోవడంలో ఇబ్బంది లేదా నిరంతర ఆయాసం (Shortness of breath)",
            "ఛాతీ నొప్పి లేదా నిరంతర ఛాతీ బిగుతు (Chest pain)",
            "అధిక జ్వరం తగ్గకపోవడం లేదా గృహ సంరక్షణలో నియంత్రణ కాకపోవడం",
            "మగత, ఆకస్మిక గందరగోళం లేదా ద్రవాలు తాగలేకపోవడం",
        ]
        if any(cand["name"] == "tuberculosis" for cand in top_candidates):
            warning_signs.append("దగ్గులో రక్తం పడటం (Blood in sputum)")
        if any(cand["name"] == "dengue" for cand in top_candidates):
            warning_signs.append("చిగుళ్ళు/ముక్కు నుండి అసాధారణ రక్తస్రావం లేదా తీవ్రమైన కడుపు నొప్పి")

        questions_for_doctor = [
            f"నా ప్రస్తుత లక్షణాలు మరియు వ్యవధి {doctor_dx} నిర్ధారణతో సరిపోలుతున్నాయా?",
            "ఇతర కారణాలను తోసిపుచ్చడానికి ఏవైనా అదనపు నిర్ధారణ పరీక్షలు ఉపయోగపడతాయా?",
            "ఏ హెచ్చరిక లక్షణాలు కనిపిస్తే వెంటనే అత్యవసర సంరక్షణను సంప్రదించాలి?",
        ]
        if drug_notes:
            questions_for_doctor.append("నా మందుల సమయం లేదా పరస్పర చర్యల గురించి నేను తెలుసుకోవలసిన విషయాలు ఏమైనా ఉన్నాయా?")

    elif language == "Hindi":
        if verdict == "AGREE":
            summary = (
                f"रिपोर्ट किए गए निष्कर्ष और नैदानिक साक्ष्य आपके डॉक्टर के {doctor_dx} के आकलन के अनुरूप प्रतीत होते हैं। "
                f"सहानुभूतिपूर्ण देखभाल और चेतावनी संकेतों पर ध्यान देने की सलाह दी जाती है।"
            )
        elif verdict == "ESCALATE":
            unexplained_str = ", ".join(unexplained[:2]) if unexplained else "लक्षणों की अवधि"
            summary = (
                f"कुछ नैदानिक निष्कर्ष (जैसे {unexplained_str}) प्रारंभिक निदान {doctor_dx} द्वारा पूरी तरह से स्पष्ट नहीं हो सकते हैं। "
                f"संभावित {top_name} के लिए अतिरिक्त विशेषज्ञ मूल्यांकन की सिफारिश की जाती है।"
            )
        else:
            summary = (
                "उपलब्ध जानकारी वर्तमान में सीमित या अनिर्णायक है। "
                "आपके लक्षणों का सटीक आकलन करने के लिए एक योग्य चिकित्सक से परामर्श की सिफारिश की जाती है।"
            )

        warning_signs = [
            "सांस लेने में कठिनाई या लगातार सांस फूलना (Shortness of breath)",
            "सीने में दर्द या लगातार सीने में जकड़न (Chest pain)",
            "तेज बुखार का लगातार बने रहना या घर पर नियंत्रित न होना",
            "अत्यधिक सुस्ती, अचानक भ्रम, या तरल पदार्थ बनाए रखने में असमर्थता",
        ]
        if any(cand["name"] == "tuberculosis" for cand in top_candidates):
            warning_signs.append("खांसी में खून आना (Blood in sputum)")
        if any(cand["name"] == "dengue" for cand in top_candidates):
            warning_signs.append("मसूड़ों/नाक से असामान्य रक्तस्राव या पेट में तेज दर्द")

        questions_for_doctor = [
            f"क्या मेरे वर्तमान लक्षण और उनकी अवधि {doctor_dx} के निदान से मेल खाते हैं?",
            "क्या अन्य संभावित कारणों को खारिज करने के लिए कोई अतिरिक्त पुष्टिकरण परीक्षण आवश्यक हैं?",
            "किन विशिष्ट चेतावनी लक्षणों पर तुरंत डॉक्टर से संपर्क करना चाहिए?",
        ]
        if drug_notes:
            questions_for_doctor.append("क्या दवाओं के समय या उनके प्रभाव के संबंध में कोई विशेष सावधानी बरतनी चाहिए?")

    else:
        # Default English
        sym_text = patient_input.get("symptoms_text", "").strip() or "reported symptoms"
        rx_note_str = f" Note on your prescription: {drug_notes[0]}" if drug_notes else ""
        if verdict == "AGREE":
            summary = (
                f"Your presentation of {sym_text} appears clinically consistent with your doctor's assessment "
                f"of {doctor_dx}. Supportive care and close symptom tracking are advised.{rx_note_str}"
            )
        elif verdict == "ESCALATE":
            unexplained_str = f"such as {', '.join(unexplained[:2])}" if unexplained else "the duration and progression"
            summary = (
                f"Your reported symptoms of {sym_text} include details ({unexplained_str}) "
                f"that are not fully explained by the initial diagnosis of {doctor_dx}. "
                f"Further clinical evaluation for possible {top_name} is recommended.{rx_note_str}"
            )
        else:
            summary = (
                f"Based on {sym_text} and diagnosis of {doctor_dx}, available clinical evidence is currently inconclusive. "
                f"An in-person clinical re-evaluation is advised to clarify your diagnosis.{rx_note_str}"
            )

        warning_signs = [
            "Difficulty breathing or persistent shortness of breath",
            "Chest pain or persistent chest tightness",
            "High fever persisting beyond expected duration or unmanageable at home",
            "Drowsiness, sudden confusion, or inability to retain fluids",
        ]
        if any(cand["name"] == "tuberculosis" for cand in top_candidates):
            warning_signs.append("Coughing up blood or noticeable blood in sputum")
        if any(cand["name"] == "dengue" for cand in top_candidates):
            warning_signs.append("Unexplained bleeding from gums/nose or severe abdominal pain")

        questions_for_doctor = [
            f"Do my current symptoms and duration align with the diagnosis of {doctor_dx}?",
            "Would any additional confirmatory tests be beneficial to rule out alternative causes?",
            "What specific warning symptoms should prompt immediate re-evaluation?",
        ]
        if drug_notes:
            questions_for_doctor.append("Are there any medication timing or interaction points I should be aware of?")

    # Formulate why
    why = []
    if top_candidates:
        for cand in top_candidates[:2]:
            ev_str = ", ".join(cand.get("evidence", []))
            why.append(f"Evidence consistent with {cand['name'].replace('_', ' ').title()}: {ev_str}.")
    if unexplained:
        why.append(f"Findings requiring clarification: {', '.join(unexplained)}.")

    # Formulate possible conditions
    possible_conditions = []
    for cand in top_candidates:
        score = cand.get("score", 0.0)
        confidence = "high" if score >= 0.6 else ("medium" if score >= 0.4 else "low")
        ev_summary = "; ".join(cand.get("evidence", []))
        possible_conditions.append({
            "name": cand["name"].replace("_", " ").title(),
            "why_possible": f"Associated with noted findings: {ev_summary}",
            "confidence": confidence,
        })

    # Confirmatory tests & specialist
    tests_to_confirm = []
    specialist = "General Physician"
    if top_candidates:
        tests_to_confirm = top_candidates[0].get("confirmatory_tests", [])
        specialist = top_candidates[0].get("specialist", "General Physician")

    disclaimer = DISCLAIMER_MAP.get(language, DISCLAIMER_TEXT)

    return {
        "verdict": verdict,
        "summary": summary,
        "why": why,
        "possible_conditions": possible_conditions,
        "tests_to_confirm": tests_to_confirm,
        "specialist_to_consult": specialist,
        "prescription_notes": drug_notes,
        "warning_signs": warning_signs,
        "questions_for_doctor": questions_for_doctor,
        "urgency": urgency,
        "disclaimer": disclaimer,
    }


def generate_report(
    verdict_data: dict,
    patient_input: dict,
    flagged_labs: list[dict],
    drug_notes: list[str],
) -> dict[str, Any]:
    """Generate grounded FinalReport adhering to strict schema and safety constraints.

    Args:
        verdict_data: Output from core.matcher.match_conditions()
        patient_input: Dict containing patient demographics, symptoms, doctor_dx, and language
        flagged_labs: Output from core.labs.flag_values()
        drug_notes: List of discussion points from core.drugcheck.check_prescription()

    Returns:
        FinalReport dict adhering to Section 4.4 schema.
    """
    language = patient_input.get("language", "English")
    disclaimer_text = DISCLAIMER_MAP.get(language, DISCLAIMER_TEXT)

    language_prompt = ""
    if language in ("Telugu", "Hindi"):
        language_prompt = (
            f"\nIMPORTANT MULTILINGUAL INSTRUCTION:\n"
            f"The patient requested this report in {language}. Provide the natural language text fields "
            f"('summary', 'why', 'why_possible', 'tests_to_confirm', 'specialist_to_consult', "
            f"'prescription_notes', 'warning_signs', 'questions_for_doctor') in {language}. "
            f"Keep medical terms in English alongside local script transliteration (e.g., మలేరియా (Malaria) or मलेरिया (Malaria)). "
            f"Preserve standard English enum values for 'verdict' ('AGREE', 'ESCALATE', 'INCONCLUSIVE'), "
            f"'urgency' ('emergency', 'same_day', 'routine'), and 'confidence' ('low', 'medium', 'high').\n"
        )

    prompt = (
        "You are an AI Clinical Second-Opinion Companion assistant. "
        "Generate a grounded second-opinion report in JSON format matching the schema below.\n\n"
        "STRICT SAFETY RULES:\n"
        "1. Never state 'you have <disease>'. Use 'possible', 'consistent with', or 'may be associated with'.\n"
        "2. Never tell the user to stop, skip, or change any medicine or dose. Use 'discuss this with your doctor or pharmacist'.\n"
        "3. Never output medicine dosages that the system itself suggests.\n"
        "4. Never say 'your doctor is wrong'. Use 'some findings are not fully explained by the current diagnosis'.\n"
        "5. Every claim must be grounded in the provided patient data, lab results, or evidence below.\n"
        "6. Do NOT invent lab values, findings, or treatments.\n"
        "7. Explicitly incorporate the patient's specific symptoms and any medicine notes directly into your summary and prescription_notes.\n"
        f"{language_prompt}\n"
        f"PATIENT DATA:\n"
        f"- Age: {patient_input.get('age')}, Sex: {patient_input.get('sex')}\n"
        f"- Symptoms: {patient_input.get('symptoms_text')}\n"
        f"- Duration (days): {patient_input.get('duration_days')}\n"
        f"- Doctor's Diagnosis: {patient_input.get('doctor_dx')}\n"
        f"- Prescriptions/Medicines: {patient_input.get('prescription_text') or 'None specified'}\n"
        f"- Preferred Language: {language}\n\n"
        f"DETERMINISTIC VERDICT ENGINE FINDINGS:\n"
        f"- Verdict: {verdict_data.get('verdict')}\n"
        f"- Urgency: {verdict_data.get('urgency')}\n"
        f"- Matched Doctor Dx Group: {verdict_data.get('doctor_dx_matched')}\n"
        f"- Top Candidate Conditions: {json.dumps(verdict_data.get('top_candidates'))}\n"
        f"- Unexplained Findings: {json.dumps(verdict_data.get('unexplained_findings'))}\n\n"
        f"LAB RESULTS (FLAGGED):\n{json.dumps(flagged_labs)}\n\n"
        f"PRESCRIPTION DISCUSSION NOTES:\n{json.dumps(drug_notes)}\n\n"
        "OUTPUT SCHEMA (JSON ONLY):\n"
        "{\n"
        f'  "verdict": "{verdict_data.get("verdict")}",\n'
        '  "summary": "2-3 simple sentences explaining the assessment in neutral language",\n'
        '  "why": ["list of evidence-based reasons citing specific symptoms or lab values"],\n'
        '  "possible_conditions": [\n'
        '    {"name": "<Condition Name>", "why_possible": "<reason citing evidence>", "confidence": "low|medium|high"}\n'
        "  ],\n"
        '  "tests_to_confirm": ["list of confirmatory tests recommended for the specialist visit"],\n'
        '  "specialist_to_consult": "<specific specialist type to consult>",\n'
        '  "prescription_notes": ["points to discuss with doctor or pharmacist"],\n'
        '  "warning_signs": ["specific red flag symptoms to watch for"],\n'
        '  "questions_for_doctor": ["practical questions for the patient to ask at their next visit"],\n'
        f'  "urgency": "{verdict_data.get("urgency")}",\n'
        f'  "disclaimer": "{disclaimer_text}"\n'
        "}"
    )

    try:
        report = call_llm(prompt, as_json=True)
        if isinstance(report, dict) and "verdict" in report and "summary" in report:
            return report
    except Exception as err:
        logger.debug("LLM report generation fallback engaged: %s", err)

    return generate_grounded_report_fallback(verdict_data, patient_input, flagged_labs, drug_notes)
