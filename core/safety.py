"""Safety filtering and validation layer for Second-Opinion Companion.

Enforces Section 3 safety rules:
1. Never state "you have <disease>". Use "possible", "consistent with", or "may be associated with".
2. Never tell the user to stop, skip, or change any medicine or dose. Use "discuss this with your doctor or pharmacist".
3. Never output medicine dosages that the system itself suggests.
4. Never say "your doctor is wrong". Use "some findings are not fully explained by the current diagnosis".
5. Every report must include the verbatim disclaimer and a specialist to verify with.
6. Urgency must be strictly derived from the deterministic rule engine.
7. Conducts secondary review ensuring all claims are grounded in evidence.
"""

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DISCLAIMER_TEXT = (
    "This tool provides general health information and is not a medical diagnosis. "
    "It cannot replace a qualified doctor. Please confirm any findings with a specialist, "
    "and seek urgent care for severe or worsening symptoms."
)

DISCLAIMER_MAP = {
    "English": DISCLAIMER_TEXT,
    "Telugu": (
        "ఈ సాధనం సాధారణ ఆరోగ్య సమాచారాన్ని అందిస్తుంది మరియు ఇది వైద్య నిర్ధారణ కాదు. "
        "ఇది అర్హత కలిగిన వైద్యుడిని భర్తీ చేయదు. దయచేసి నిపుణుడితో ధృవీకరించుకోండి మరియు "
        "తీవ్రమైన లేదా విషమించే లక్షణాల కోసం అత్యవసర సంరక్షణను పొందండి."
    ),
    "Hindi": (
        "यह उपकरण सामान्य स्वास्थ्य जानकारी प्रदान करता है और यह कोई चिकित्सीय निदान नहीं है। "
        "यह किसी योग्य चिकित्सक का स्थान नहीं ले सकता। कृपया किसी विशेषज्ञ से किसी भी निष्कर्ष की पुष्टि करें, "
        "और गंभीर या बिगड़ते लक्षणों के लिए तत्काल आपातकालीन चिकित्सा सहायता लें।"
    ),
}


BANNED_PHRASE_REPLACEMENTS = [
    # Diagnosis assertion patterns
    (r"\byou have\b", "your findings may be consistent with"),
    (r"\byou suffer from\b", "your findings may be associated with"),
    (r"\byou are diagnosed with\b", "your findings suggest a possible diagnosis of"),
    # Doctor opposition patterns
    (r"\byour doctor is wrong\b", "some findings are not fully explained by the current diagnosis"),
    (r"\bthe doctor is wrong\b", "some findings are not fully explained by the current diagnosis"),
    (r"\byour doctor misdiagnosed\b", "some findings are not fully explained by the current diagnosis"),
    (r"\bthe doctor missed\b", "additional evaluation may clarify whether"),
    # Medication cessation or modification patterns
    (
        r"\b(?:stop taking|discontinue|quit taking|cease taking)\b[^.;]*",
        "Please continue your medications as prescribed and discuss any potential treatment adjustments with your doctor or pharmacist",
    ),
    (
        r"\b(?:skip your|skip the)\s+(?:dose|medication|tablet|pill)\b[^.;]*",
        "Please discuss any medication timing questions with your doctor or pharmacist",
    ),
    (
        r"\b(?:change|increase|decrease|lower|raise)\s+(?:your\s+)?(?:dose|dosage)\b[^.;]*",
        "Please discuss any dose adjustments with your doctor or pharmacist",
    ),
    # System suggested dosage patterns (e.g. "take 500mg", "start 10mg")
    (
        r"\b(?:take|start|prescribe)\s+\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|tablets?|capsules?)\b",
        "consult your doctor or pharmacist regarding appropriate medical therapy and dosage",
    ),
]


def sanitize_text(text: str) -> str:
    """Scan and rewrite prohibited phrasing in text strings."""
    if not isinstance(text, str) or not text.strip():
        return text

    sanitized = text
    for pattern, replacement in BANNED_PHRASE_REPLACEMENTS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    # Clean up double punctuation or awkward whitespace
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def _sanitize_data_recursively(data: Any) -> Any:
    """Recursively sanitize all string elements in dicts or lists."""
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, list):
        return [_sanitize_data_recursively(item) for item in data]
    elif isinstance(data, dict):
        return {key: _sanitize_data_recursively(val) for key, val in data.items()}
    return data


def reviewer_llm_check(report_data: dict, evidence_context: dict) -> dict:
    """Optional secondary LLM reviewer pass to verify groundedness."""
    try:
        from core.llm import call_llm
        prompt = (
            f"You are a clinical safety auditor. Audit this report to ensure all findings are grounded in the evidence.\n\n"
            f"Evidence Context:\n{evidence_context}\n\n"
            f"Report under review:\n{report_data}\n\n"
            f"If there are any fabricated lab values or invented claims, remove them. "
            f"Ensure tone is objective and cautious. Return the cleaned JSON report."
        )
        cleaned = call_llm(prompt, as_json=True)
        if isinstance(cleaned, dict) and "verdict" in cleaned:
            return cleaned
    except Exception as err:
        logger.debug("Secondary LLM review pass skipped or unavailable: %s", err)

    return report_data


def review_safety(report_data: dict, evidence_context: dict) -> dict:
    """Filter, sanitize, and validate the report against safety guidelines.

    Enforces:
    - Banned phrasing removal/rewriting
    - Mandatory verbatim disclaimer
    - Urgency level strictly derived from the rule engine
    - Grounded specialist and tests
    """
    cleaned_report = copy.deepcopy(report_data)

    # 1. Recursive regex sanitization pass
    cleaned_report = _sanitize_data_recursively(cleaned_report)

    # 2. Enforce invariant: Verdict and Urgency strictly come from rule engine
    verdict_data = evidence_context.get("verdict_data", {})
    rule_verdict = verdict_data.get("verdict", "INCONCLUSIVE")
    rule_urgency = verdict_data.get("urgency", "routine")

    cleaned_report["verdict"] = rule_verdict
    cleaned_report["urgency"] = rule_urgency

    # 3. Enforce invariant: Verbatim disclaimer according to language
    language = evidence_context.get("patient_input", {}).get("language", "English")
    disclaimer_to_use = DISCLAIMER_MAP.get(language, DISCLAIMER_TEXT)
    cleaned_report["disclaimer"] = disclaimer_to_use

    # 4. Enforce invariant: Specialist to consult
    top_candidates = verdict_data.get("top_candidates", [])
    if top_candidates:
        default_specialist = top_candidates[0].get("specialist", "General Physician")
    else:
        default_specialist = "General Physician or Medical Specialist"

    current_specialist = cleaned_report.get("specialist_to_consult")
    if not current_specialist or current_specialist.strip().lower() in ("none", "n/a", "unknown"):
        cleaned_report["specialist_to_consult"] = default_specialist

    # 5. Enforce tests_to_confirm structure
    tests = cleaned_report.get("tests_to_confirm", [])
    if not tests and top_candidates:
        cleaned_report["tests_to_confirm"] = top_candidates[0].get("confirmatory_tests", [])

    # 6. Secondary groundedness check (if online)
    cleaned_report = reviewer_llm_check(cleaned_report, evidence_context)

    # Re-apply invariants post-review just in case reviewer LLM modified them
    cleaned_report["verdict"] = rule_verdict
    cleaned_report["urgency"] = rule_urgency
    cleaned_report["disclaimer"] = disclaimer_to_use

    return cleaned_report
