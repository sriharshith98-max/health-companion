"""Condition matching and verdict determination engine for Second-Opinion Companion.

Implements SPEC.md Section 4.5:
1. Signal extraction from symptoms and flagged labs
2. Deterministic condition scoring against weighted red flags
3. Doctor diagnosis matching via synonyms and LLM classification
4. Verdict rules: AGREE, ESCALATE, INCONCLUSIVE
5. Urgency evaluation: routine, soon, urgent
6. Unexplained findings identification
"""

import json
import logging
import os
import re
from typing import Any

from core.knowledge import CONDITIONS, SPECIALISTS, get_condition_by_name

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SYNONYMS_FILE = os.path.join(DATA_DIR, "synonyms.json")

_SYNONYMS_CACHE: dict[str, list[str]] | None = None


def _load_synonyms() -> dict[str, list[str]]:
    """Load diagnosis synonym groups from data/synonyms.json."""
    global _SYNONYMS_CACHE
    if _SYNONYMS_CACHE is not None:
        return _SYNONYMS_CACHE

    if os.path.exists(SYNONYMS_FILE):
        try:
            with open(SYNONYMS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                _SYNONYMS_CACHE = data.get("synonym_groups", {})
                return _SYNONYMS_CACHE
        except Exception as exc:
            logger.error("Failed to load synonyms.json: %s", exc)

    _SYNONYMS_CACHE = {}
    return _SYNONYMS_CACHE


def map_doctor_dx(doctor_dx: str) -> str | None:
    """Map the doctor's diagnosis to a canonical condition group.

    Args:
        doctor_dx: Doctor's diagnosis string (e.g., 'viral fever', 'regular infection').

    Returns:
        Canonical condition name or None if unmapped.
    """
    if not doctor_dx or not doctor_dx.strip():
        return None

    cleaned = doctor_dx.strip().lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    synonyms = _load_synonyms()

    # 1. Direct exact or substring match in synonym groups
    for canonical_name, syn_list in synonyms.items():
        for syn in syn_list:
            syn_clean = syn.lower().strip()
            if syn_clean == cleaned or f" {syn_clean} " in f" {cleaned} ":
                return canonical_name

    # 2. Check for "regular infection" specifically -> maps to viral_upper_respiratory_infection
    if "regular infection" in cleaned or "normal infection" in cleaned or "routine infection" in cleaned:
        return "viral_upper_respiratory_infection"

    # 3. Fallback LLM classification
    try:
        from core.llm import call_llm
        known_conditions = [c["name"] for c in CONDITIONS]
        prompt = (
            f"Classify the clinical diagnosis: '{doctor_dx}' into ONE of these canonical condition categories:\n"
            f"{json.dumps(known_conditions)}\n"
            f"If it does not match any, output 'other'.\n"
            f"Respond with JSON: {{\"matched_group\": \"<condition_or_other>\"}}"
        )
        res = call_llm(prompt, as_json=True)
        if isinstance(res, dict):
            matched = res.get("matched_group", "").strip().lower()
            if matched in known_conditions:
                return matched
    except Exception as err:
        logger.debug("Doctor dx LLM classification fallback failed: %s", err)

    return None


def extract_signals(symptoms: dict, flagged_labs: list[dict]) -> set[str]:
    """Convert symptoms and flagged labs into a set of active clinical signal IDs.

    Args:
        symptoms: StructuredSymptoms dict {symptoms: list, duration_days: int|None, flags: dict}
        flagged_labs: List of flagged lab dicts from core.labs.flag_values()

    Returns:
        Set of active standardized signal IDs.
    """
    signals = set()
    flags = symptoms.get("flags", {})
    symptom_list = [s.lower() for s in symptoms.get("symptoms", [])]
    combined_symptom_text = " ".join(symptom_list)

    # 1. Transfer active symptom flags
    for flag_id, is_active in flags.items():
        if is_active:
            signals.add(flag_id)

    # 2. Check duration
    duration = symptoms.get("duration_days")
    if duration is not None:
        if duration > 14 and ("cough" in combined_symptom_text or flags.get("cough_gt_14d")):
            signals.add("cough_gt_14d")
        if duration <= 7:
            signals.add("duration_short")
        if duration > 5:
            signals.add("fever_step_ladder")

    # 3. Check symptom text keywords for unflagged conditions
    if any(k in combined_symptom_text for k in ["sore throat", "scratchy throat"]):
        signals.add("sore_throat")
    if any(k in combined_symptom_text for k in ["runny nose", "rhinorrhea", "nasal congestion", "sneezing"]):
        signals.add("runny_nose")
    if any(k in combined_symptom_text for k in ["chills", "rigors"]):
        signals.add("fever_with_chills")
    if any(k in combined_symptom_text for k in ["rash", "petechiae", "red spots"]):
        signals.add("rash")
    if any(k in combined_symptom_text for k in ["dysuria", "burning urination", "painful urination"]):
        signals.add("dysuria")
    if any(k in combined_symptom_text for k in ["slow-healing", "slow healing wound", "wound"]):
        signals.add("slow_healing_wound")
    if any(k in combined_symptom_text for k in ["jaundice", "yellow eyes", "yellow skin"]):
        signals.add("jaundice")
    if any(k in combined_symptom_text for k in ["dark urine", "tea colored urine"]):
        signals.add("dark_urine")
    if any(k in combined_symptom_text for k in ["cold intolerance", "feeling cold"]):
        signals.add("cold_intolerance")
    if any(k in combined_symptom_text for k in ["edema", "swollen feet", "swollen ankles", "leg swelling"]):
        signals.add("edema")
    if any(k in combined_symptom_text for k in ["foamy urine", "bubbly urine", "proteinuria"]):
        signals.add("foamy_urine")
    if any(k in combined_symptom_text for k in ["blood in sputum", "hemoptysis", "coughing blood"]):
        signals.add("blood_in_sputum")
    if any(k in combined_symptom_text for k in ["pleuritic", "sharp chest pain", "chest pain on breathing"]):
        signals.add("chest_pain")

    # 4. Map flagged lab results
    for lab in flagged_labs:
        test = lab.get("normalized_test", "")
        status = lab.get("status", "NORMAL")

        if test == "esr" and status in ("HIGH", "CRITICAL"):
            signals.add("esr_high")
        elif test == "platelets" and status in ("LOW", "CRITICAL"):
            signals.add("platelets_low")
        elif test in ("fasting_glucose", "random_glucose", "postprandial_glucose", "hba1c") and status in ("HIGH", "CRITICAL"):
            signals.add("glucose_high")
        elif test == "hemoglobin" and status in ("LOW", "CRITICAL"):
            signals.add("hemoglobin_low")
        elif test in ("creatinine", "blood_urea_nitrogen") and status in ("HIGH", "CRITICAL"):
            signals.add("creatinine_high")
        elif test in ("total_bilirubin", "sgpt_alt", "sgot_ast") and status in ("HIGH", "CRITICAL"):
            signals.add("bilirubin_high")
        elif test == "tsh" and status in ("HIGH", "CRITICAL"):
            signals.add("tsh_high")
        elif test == "wbc" and status == "HIGH":
            signals.add("wbc_high")
        elif test == "wbc" and status == "LOW":
            signals.add("wbc_low")

    return signals


def score_conditions(signals: set[str]) -> list[dict[str, Any]]:
    """Score each condition based on matched weighted red flags.

    Algorithm: score = sum(weights of matched red flags) / sum(all weights)

    Args:
        signals: Set of active clinical signals.

    Returns:
        Ranked list of candidate dicts with score >= 0.25.
    """
    candidates = []

    for cond in CONDITIONS:
        total_weight = sum(rf["weight"] for rf in cond["red_flags"])
        matched_weight = 0
        matched_evidence = []

        for rf in cond["red_flags"]:
            if rf["id"] in signals:
                matched_weight += rf["weight"]
                matched_evidence.append(rf["label"])

        score = (matched_weight / total_weight) if total_weight > 0 else 0.0

        if score >= 0.25:
            candidates.append({
                "name": cond["name"],
                "score": round(score, 2),
                "matched_weight": matched_weight,
                "total_weight": total_weight,
                "evidence": matched_evidence,
                "confirmatory_tests": cond.get("confirmatory_tests", []),
                "specialist": cond.get("specialist", "General Physician"),
                "urgent_triggers": cond.get("urgent_triggers", []),
            })

    # Sort descending by score, then by matched_weight
    candidates.sort(key=lambda c: (c["score"], c["matched_weight"]), reverse=True)
    return candidates


def match_conditions(
    signals: set[str],
    doctor_dx: str,
    flagged_labs: list[dict] | None = None,
    raw_symptoms: dict | None = None,
) -> dict[str, Any]:
    """Score candidate conditions, evaluate doctor dx, and determine verdict and urgency.

    SPEC.md Section 4.5 Rules:
    - If fewer than 2 signals are active or top score < 0.25 -> INCONCLUSIVE
    - If doctor's dx group equals top candidate's group and no urgent trigger -> AGREE
    - If top candidate (score >= 0.5) is not in doctor's dx group -> ESCALATE
    - If a "regular infection" dx is given and any duration or severity red flag fires -> ESCALATE
    - Urgency: 'urgent' if any urgent_triggers or CRITICAL lab; 'soon' for ESCALATE; else 'routine'.

    Returns:
        Verdict schema dict.
    """
    flagged_labs = flagged_labs or []
    raw_symptoms = raw_symptoms or {}

    doctor_dx_matched = map_doctor_dx(doctor_dx)
    candidates = score_conditions(signals)

    # 1. Determine urgent triggers and critical lab status
    has_critical_lab = any(lab.get("is_critical", False) for lab in flagged_labs)
    
    # Check condition-specific urgent triggers in symptoms
    active_urgent_triggers = []
    combined_text = " ".join([
        doctor_dx or "",
        " ".join(raw_symptoms.get("symptoms", [])),
    ]).lower()
    
    flags = raw_symptoms.get("flags", {})
    if flags.get("blood_in_sputum") or "blood in sputum" in signals or "blood in sputum" in combined_text:
        active_urgent_triggers.append("blood in sputum")
    if flags.get("breathlessness") or "breathlessness" in signals or "breathless" in combined_text:
        active_urgent_triggers.append("breathlessness at rest / difficulty breathing")
    if flags.get("chest_pain") or "chest_pain" in signals or "chest pain" in combined_text:
        active_urgent_triggers.append("chest pain")

    for lab in flagged_labs:
        if lab.get("is_critical"):
            active_urgent_triggers.append(f"Critical lab alert: {lab.get('test')} = {lab.get('value')} {lab.get('unit', '')}")

    # Check for duration / severity red flags
    duration = raw_symptoms.get("duration_days")
    has_duration_flag = (duration is not None and duration > 14) or "cough_gt_14d" in signals
    has_severity_flag = bool(
        flags.get("weight_loss")
        or flags.get("night_sweats")
        or flags.get("blood_in_sputum")
        or "glucose_high" in signals
        or "esr_high" in signals
        or "platelets_low" in signals
        or "creatinine_high" in signals
    )

    is_generic_dx = (
        doctor_dx_matched == "viral_upper_respiratory_infection"
        or "regular infection" in (doctor_dx or "").lower()
        or "weakness" in (doctor_dx or "").lower()
    )

    # 2. Evaluate Verdict
    if len(signals) < 2 or not candidates:
        verdict = "INCONCLUSIVE"
    else:
        top_cand = candidates[0]
        top_name = top_cand["name"]
        top_score = top_cand["score"]

        if is_generic_dx and (has_duration_flag or has_severity_flag):
            verdict = "ESCALATE"
        elif doctor_dx_matched and doctor_dx_matched == top_name and not active_urgent_triggers:
            verdict = "AGREE"
        elif top_score >= 0.50 and (doctor_dx_matched != top_name):
            verdict = "ESCALATE"
        elif doctor_dx_matched and doctor_dx_matched == top_name:
            verdict = "AGREE"
        elif top_score >= 0.35 and doctor_dx_matched != top_name:
            verdict = "ESCALATE"
        else:
            verdict = "INCONCLUSIVE"

    # 3. Determine Urgency
    if active_urgent_triggers or has_critical_lab:
        urgency = "urgent"
    elif verdict == "ESCALATE":
        urgency = "soon"
    else:
        urgency = "routine"

    # 4. Identify unexplained findings
    # Findings not typical of the doctor's diagnosis
    unexplained = []
    if doctor_dx_matched:
        doc_cond = get_condition_by_name(doctor_dx_matched)
        doc_rf_ids = {rf["id"] for rf in doc_cond.get("red_flags", [])} if doc_cond else set()
        
        # Check active signals not in doctor dx red flags
        signal_labels = {
            "cough_gt_14d": "cough longer than 2 weeks",
            "night_sweats": "night sweats",
            "weight_loss": "unexplained weight loss",
            "esr_high": "elevated ESR",
            "glucose_high": "elevated blood sugar",
            "slow_healing_wound": "slow-healing wound",
            "thirst": "excessive thirst",
            "frequent_urination": "frequent urination",
            "blood_in_sputum": "blood in sputum",
            "platelets_low": "low platelets",
            "creatinine_high": "elevated creatinine",
            "jaundice": "jaundice",
        }
        for s in signals:
            if s not in doc_rf_ids and s in signal_labels:
                unexplained.append(signal_labels[s])
    else:
        # If doctor dx was unmapped, all active severe/duration signals are unexplained
        for s in ["cough_gt_14d", "night_sweats", "weight_loss", "esr_high", "glucose_high"]:
            if s in signals:
                unexplained.append(s.replace("_", " "))

    return {
        "verdict": verdict,
        "doctor_dx_matched": doctor_dx_matched or "unmapped",
        "top_candidates": candidates[:3],  # Keep top 3 candidates
        "urgency": urgency,
        "unexplained_findings": list(dict.fromkeys(unexplained)),  # Deduplicate preserving order
        "active_signals": list(signals),
        "active_urgent_triggers": active_urgent_triggers,
    }
