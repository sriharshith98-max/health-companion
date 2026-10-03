"""Structured extraction module for Second-Opinion Companion.

Transforms raw clinical notes, document text, and prescriptions into validated JSON schemas
for symptoms, lab values, and medications.
"""

import json
import logging
import re
from typing import Any

from core.llm import call_llm

logger = logging.getLogger(__name__)

STANDARD_FLAGS = [
    "fever",
    "weight_loss",
    "night_sweats",
    "blood_in_sputum",
    "cough_gt_14d",
    "breathlessness",
    "chest_pain",
    "fatigue",
    "thirst",
    "frequent_urination",
    "headache",
    "joint_pain",
]


def _extract_duration_days_from_text(text: str) -> int | None:
    """Heuristic extractor for duration in days from symptom text."""
    lower = text.lower()
    
    # Check weeks
    m_weeks = re.search(r"(\d+)\s*(?:weeks?|wks?)", lower)
    if m_weeks:
        return int(m_weeks.group(1)) * 7
        
    # Check months
    m_months = re.search(r"(\d+)\s*(?:months?|mths?)", lower)
    if m_months:
        return int(m_months.group(1)) * 30
        
    # Check days
    m_days = re.search(r"(\d+)\s*(?:days?|dys?)", lower)
    if m_days:
        return int(m_days.group(1))

    return None


def _heuristic_symptoms_fallback(text: str, duration_days: int | None = None) -> dict:
    """Deterministic extraction fallback for symptoms when LLM is offline or not configured."""
    lower = text.lower()
    detected_duration = duration_days if duration_days is not None else _extract_duration_days_from_text(text)

    flags = {flag: False for flag in STANDARD_FLAGS}

    # Fever
    if any(k in lower for k in ["fever", "pyrexia", "temperature", "chills", "febrile"]):
        flags["fever"] = True

    # Weight loss
    if any(k in lower for k in ["weight loss", "losing weight", "lost weight"]):
        flags["weight_loss"] = True

    # Night sweats
    if any(k in lower for k in ["night sweat", "night sweats", "sweating at night"]):
        flags["night_sweats"] = True

    # Blood in sputum / hemoptysis
    if any(k in lower for k in ["blood in sputum", "coughing blood", "hemoptysis", "blood tinged sputum"]):
        flags["blood_in_sputum"] = True

    # Cough & prolonged cough
    has_cough = "cough" in lower
    if has_cough:
        if detected_duration and detected_duration > 14:
            flags["cough_gt_14d"] = True
        elif any(k in lower for k in ["chronic cough", "3 weeks", "4 weeks", "month", "prolonged cough"]):
            flags["cough_gt_14d"] = True

    # Breathlessness / dyspnea
    if any(k in lower for k in ["breathless", "short of breath", "shortness of breath", "dyspnea", "breathing difficulty"]):
        flags["breathlessness"] = True

    # Chest pain
    if any(k in lower for k in ["chest pain", "pain in chest", "angina"]):
        flags["chest_pain"] = True

    # Fatigue
    if any(k in lower for k in ["fatigue", "tiredness", "exhaustion", "weakness", "lethargy"]):
        flags["fatigue"] = True

    # Thirst
    if any(k in lower for k in ["thirst", "polydipsia", "thirsty"]):
        flags["thirst"] = True

    # Frequent urination
    if any(k in lower for k in ["frequent urination", "polyuria", "urinating often"]):
        flags["frequent_urination"] = True

    # Headache
    if any(k in lower for k in ["headache", "head pain", "migraine"]):
        flags["headache"] = True

    # Joint pain
    if any(k in lower for k in ["joint pain", "arthralgia", "body ache", "body pains"]):
        flags["joint_pain"] = True

    # Extract rough list of symptoms
    tokens = [t.strip().strip(",.;") for t in re.split(r",|\band\b|\bwith\b|\n", text) if t.strip()]
    symptoms_list = [t for t in tokens if len(t) > 2 and not re.match(r"^\d+\s*(?:days?|weeks?|months?)$", t.lower())]
    if not symptoms_list:
        symptoms_list = [text.strip()]

    return {
        "symptoms": symptoms_list,
        "duration_days": detected_duration,
        "flags": flags,
    }


def structure_symptoms(symptoms_text: str, duration_days: int | None = None) -> dict:
    """Extract structured symptoms and red-flag indicators from free text.

    Args:
        symptoms_text: Free-text descriptions of symptoms.
        duration_days: Optional known duration in days.

    Returns:
        dict: StructuredSymptoms schema {symptoms: list, duration_days: int|None, flags: dict}
    """
    if not symptoms_text or not symptoms_text.strip():
        return {
            "symptoms": [],
            "duration_days": duration_days,
            "flags": {f: False for f in STANDARD_FLAGS},
        }

    # Prompt LLM for extraction
    prompt = (
        f"You are a clinical NLP extractor. Extract structured symptoms, duration, and red flags from this patient input.\n\n"
        f"Input: \"\"\"{symptoms_text}\"\"\"\n"
        f"Provided duration override: {duration_days if duration_days is not None else 'None'}\n\n"
        f"Output ONLY a valid JSON object matching this schema:\n"
        f"{{\n"
        f'  "symptoms": ["list of individual symptom strings"],\n'
        f'  "duration_days": <integer or null>,\n'
        f'  "flags": {{\n'
        f'    "fever": <boolean>,\n'
        f'    "weight_loss": <boolean>,\n'
        f'    "night_sweats": <boolean>,\n'
        f'    "blood_in_sputum": <boolean>,\n'
        f'    "cough_gt_14d": <boolean (true if cough persists > 14 days)>,\n'
        f'    "breathlessness": <boolean>,\n'
        f'    "chest_pain": <boolean>,\n'
        f'    "fatigue": <boolean>,\n'
        f'    "thirst": <boolean>,\n'
        f'    "frequent_urination": <boolean>,\n'
        f'    "headache": <boolean>,\n'
        f'    "joint_pain": <boolean>\n'
        f"  }}\n"
        f"}}"
    )

    try:
        res = call_llm(prompt, as_json=True)
        if isinstance(res, dict) and "symptoms" in res and "flags" in res:
            # Validate types
            dur = duration_days if duration_days is not None else res.get("duration_days")
            if dur is not None:
                try:
                    dur = int(dur)
                except (ValueError, TypeError):
                    dur = _extract_duration_days_from_text(symptoms_text)

            res_flags = res.get("flags", {})
            sanitized_flags = {}
            for k in STANDARD_FLAGS:
                sanitized_flags[k] = bool(res_flags.get(k, False))

            # Auto-align cough_gt_14d if duration is > 14 days and cough is present
            if dur and dur > 14 and any("cough" in s.lower() for s in res.get("symptoms", [])):
                sanitized_flags["cough_gt_14d"] = True

            return {
                "symptoms": [str(s).strip() for s in res.get("symptoms", []) if str(s).strip()],
                "duration_days": dur,
                "flags": sanitized_flags,
            }
    except Exception as err:
        logger.debug("LLM symptom extraction fell back to heuristic: %s", err)

    return _heuristic_symptoms_fallback(symptoms_text, duration_days)


def _heuristic_report_fallback(text: str) -> list[dict]:
    """Deterministic regex extraction fallback for lab test reports."""
    results = []
    lines = text.splitlines()
    
    # Common pattern: "Test Name: Value Unit (Ref: Low - High)" or "Test Name Value Unit Low - High"
    # Example: "Hemoglobin: 10.2 g/dL (Ref Range: 13.5 - 17.5)"
    # Example: "ESR: 45 mm/hr (Ref Range: 0 - 15)"
    pattern = re.compile(
        r"([A-Za-z0-9\s\/\-_]+?)\s*[:=-]\s*([<>]?\s*\d+(?:\.\d+)?)\s*([a-zA-Z\/\%μµ\^0-9]+)?(?:\s*\(.*?(?:ref|range)?.*?(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?).*?\))?",
        re.IGNORECASE,
    )

    for line in lines:
        line_clean = line.strip()
        if not line_clean or len(line_clean) < 4:
            continue
            
        m = pattern.search(line_clean)
        if m:
            test_name = m.group(1).strip()
            # Ignore non-test labels
            if test_name.lower() in ("patient", "age", "sex", "doctor", "date", "sample", "report", "hospital"):
                continue

            raw_val = m.group(2).replace(" ", "").strip()
            unit = m.group(3).strip() if m.group(3) else None
            ref_low = float(m.group(4)) if m.group(4) else None
            ref_high = float(m.group(5)) if m.group(5) else None

            try:
                val = float(raw_val)
            except ValueError:
                val = raw_val

            results.append({
                "test": test_name,
                "value": val,
                "unit": unit,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "status": None,
            })
            continue

        # Simple space-delimited table row fallback: "Platelet Count 150000 /cumm 150000 - 450000"
        m_row = re.search(
            r"^([A-Za-z\s]+?)\s+(\d+(?:\.\d+)?)\s+([a-zA-Z\/\%μµ\^0-9]+)?\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)",
            line_clean,
        )
        if m_row:
            test_name = m_row.group(1).strip()
            try:
                val = float(m_row.group(2))
            except ValueError:
                val = m_row.group(2)
            results.append({
                "test": test_name,
                "value": val,
                "unit": m_row.group(3).strip() if m_row.group(3) else None,
                "ref_low": float(m_row.group(4)),
                "ref_high": float(m_row.group(5)),
                "status": None,
            })

    return results


def structure_report(report_text: str) -> list[dict]:
    """Extract structured lab results from medical report text.

    Args:
        report_text: Raw text of the laboratory report.

    Returns:
        List of dicts: [{test: str, value: float|str, unit: str|None, ref_low: float|None, ref_high: float|None, status: str|None}]
    """
    if not report_text or not report_text.strip():
        return []

    prompt = (
        f"You are a medical laboratory data extractor. Extract all test results from the text below.\n\n"
        f"Report text:\n\"\"\"\n{report_text}\n\"\"\"\n\n"
        f"Output ONLY a valid JSON array of objects with these exact keys:\n"
        f"[\n"
        f"  {{\n"
        f'    "test": "Name of test (e.g., hemoglobin, fasting glucose, platelets)",\n'
        f'    "value": <numeric number (e.g. 10.2) or string if qualitative (e.g. "Positive")>,\n'
        f'    "unit": <unit string (e.g. "g/dL") or null>,\n'
        f'    "ref_low": <lower reference limit as float, or null>,\n'
        f'    "ref_high": <upper reference limit as float, or null>,\n'
        f'    "status": <"LOW"|"NORMAL"|"HIGH"|"CRITICAL" if indicated in the report, else null>\n'
        f"  }}\n"
        f"]"
    )

    try:
        res = call_llm(prompt, as_json=True)
        if isinstance(res, list):
            validated = []
            for item in res:
                if isinstance(item, dict) and "test" in item and "value" in item:
                    # Clean numeric value
                    val = item["value"]
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        val = str(val).strip()

                    ref_low = item.get("ref_low")
                    if ref_low is not None:
                        try:
                            ref_low = float(ref_low)
                        except (ValueError, TypeError):
                            ref_low = None

                    ref_high = item.get("ref_high")
                    if ref_high is not None:
                        try:
                            ref_high = float(ref_high)
                        except (ValueError, TypeError):
                            ref_high = None

                    validated.append({
                        "test": str(item["test"]).strip(),
                        "value": val,
                        "unit": str(item["unit"]).strip() if item.get("unit") else None,
                        "ref_low": ref_low,
                        "ref_high": ref_high,
                        "status": str(item["status"]).strip().upper() if item.get("status") else None,
                    })
            if validated:
                return validated
    except Exception as err:
        logger.debug("LLM report extraction fell back to heuristic: %s", err)

    return _heuristic_report_fallback(report_text)


def _heuristic_prescription_fallback(text: str) -> list[dict]:
    """Deterministic regex extraction fallback for prescriptions."""
    items = []
    lines = text.splitlines()

    # Pattern: Tab/Cap/Syp [Drug Name] [Dose] [Frequency] [Duration]
    # Example: "Tab. Amoxicillin 500 mg TID for 5 days"
    # Example: "Paracetamol 650 mg SOS 3 days"
    pattern = re.compile(
        r"(?:(?:tab|cap|syp|inj|tab\.|cap\.|syp\.|inj\.)\s+)?([A-Za-z0-9\-]+(?:\s+[A-Za-z0-9\-]+)?)\s+(\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu))\s*(?:(?:po|orally)\s+)?([A-Za-z0-9\.\s]+?)(?:\s*(?:x|for|dur:)?\s*(\d+\s*(?:days?|weeks?|months?|d|w)))?$",
        re.IGNORECASE,
    )

    for line in lines:
        line_clean = line.strip().lstrip("*-•1234567890. ")
        if not line_clean or len(line_clean) < 3:
            continue
        
        # Check standard prescription lines
        m = pattern.search(line_clean)
        if m:
            drug = m.group(1).strip()
            # Clean common prefixes from drug
            drug = re.sub(r"^(?:rx|tab|cap|syp|inj)\.?\s+", "", drug, flags=re.IGNORECASE).strip()
            dose = m.group(2).strip()
            freq = m.group(3).strip() if m.group(3) else None
            dur = m.group(4).strip() if m.group(4) else None

            # Filter out non-drug sentences
            if drug.lower() in ("rx", "prescription", "date", "dr", "doctor", "take", "sig"):
                continue

            items.append({
                "drug": drug,
                "dose": dose,
                "frequency": freq,
                "duration": dur,
            })
            continue

        # Simpler fallback: "Amoxicillin 500mg"
        m_simple = re.search(r"([A-Za-z]{3,20})\s+(\d+\s*(?:mg|g|mcg|ml))", line_clean, re.IGNORECASE)
        if m_simple and m_simple.group(1).lower() not in ("take", "with", "food", "daily", "days"):
            items.append({
                "drug": m_simple.group(1).strip(),
                "dose": m_simple.group(2).strip(),
                "frequency": None,
                "duration": None,
            })

    return items


def structure_prescription(prescription_text: str) -> list[dict]:
    """Extract structured prescription items (drug, dose, frequency, duration).

    Args:
        prescription_text: Raw text of the prescription.

    Returns:
        List of dicts: [{drug: str, dose: str|None, frequency: str|None, duration: str|None}]
    """
    if not prescription_text or not prescription_text.strip():
        return []

    prompt = (
        f"You are a medical prescription extractor. Extract all prescribed medications from the text below.\n\n"
        f"Prescription text:\n\"\"\"\n{prescription_text}\n\"\"\"\n\n"
        f"Output ONLY a valid JSON array of objects with these exact keys:\n"
        f"[\n"
        f"  {{\n"
        f'    "drug": "Generic or brand name of medication (e.g., Amoxicillin, Paracetamol)",\n'
        f'    "dose": <dosage string (e.g. "500 mg") or null>,\n'
        f'    "frequency": <frequency string (e.g. "TID", "once daily", "BID") or null>,\n'
        f'    "duration": <duration string (e.g. "5 days", "1 week") or null>\n'
        f"  }}\n"
        f"]"
    )

    try:
        res = call_llm(prompt, as_json=True)
        if isinstance(res, list):
            validated = []
            for item in res:
                if isinstance(item, dict) and "drug" in item:
                    drug_name = str(item["drug"]).strip()
                    if drug_name:
                        validated.append({
                            "drug": drug_name,
                            "dose": str(item["dose"]).strip() if item.get("dose") else None,
                            "frequency": str(item["frequency"]).strip() if item.get("frequency") else None,
                            "duration": str(item["duration"]).strip() if item.get("duration") else None,
                        })
            if validated:
                return validated
    except Exception as err:
        logger.debug("LLM prescription extraction fell back to heuristic: %s", err)

    return _heuristic_prescription_fallback(prescription_text)
