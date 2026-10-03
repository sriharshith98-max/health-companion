"""Prescription and drug interaction analysis module for Second-Opinion Companion.

Enforces Safety Rules (SPEC.md Section 3):
- Never tells the user to stop, skip, or change any medicine or dose.
- Uses 'discuss this with your doctor or pharmacist'.
- Never outputs suggested medicine dosages.
- Gracefully handles network or API failure without crashing.
"""

import logging
import re
from typing import Any
import requests

logger = logging.getLogger(__name__)

RXNAV_RXCUI_URL = "https://rxnav.nlm.nih.gov/REST/rxcui.json"
RXNAV_INTERACTION_URL = "https://rxnav.nlm.nih.gov/REST/interaction/list.json"
REQUEST_TIMEOUT_SECONDS = 4

# Common antibiotic generic names and stems for indication checks
ANTIBIOTIC_KEYWORDS = {
    "amoxicillin",
    "ampicillin",
    "clavulanate",
    "augmentin",
    "azithromycin",
    "clarithromycin",
    "erythromycin",
    "ciprofloxacin",
    "levofloxacin",
    "moxifloxacin",
    "ofloxacin",
    "cefixime",
    "ceftriaxone",
    "cefuroxime",
    "cephalexin",
    "doxycycline",
    "tetracycline",
    "metronidazole",
    "nitrofurantoin",
    "cotrimoxazole",
    "trimethoprim",
    "sulfamethoxazole",
}

# Curated reference pairs for offline reliability and fallback
KNOWN_INTERACTIONS: list[dict[str, Any]] = [
    {
        "drugs": {"warfarin", "aspirin"},
        "description": "Concurrent use of Warfarin and Aspirin may increase the risk of bleeding. Discuss this combination with your doctor or pharmacist to ensure appropriate monitoring.",
    },
    {
        "drugs": {"warfarin", "ibuprofen"},
        "description": "Concurrent use of Warfarin with NSAIDs such as Ibuprofen can increase the risk of gastrointestinal bleeding. Discuss this combination with your doctor or pharmacist.",
    },
    {
        "drugs": {"ciprofloxacin", "iron"},
        "description": "Co-administration of Ciprofloxacin with iron supplements or antacids can reduce the absorption of the antibiotic. Discuss the optimal timing between doses with your doctor or pharmacist.",
    },
    {
        "drugs": {"methotrexate", "ibuprofen"},
        "description": "NSAIDs like Ibuprofen may reduce the renal clearance of Methotrexate, increasing its toxicity risk. Discuss this combination with your doctor or pharmacist.",
    },
    {
        "drugs": {"paracetamol", "acetaminophen"},
        "description": "Check with your doctor or pharmacist to confirm you are not taking multiple products containing paracetamol/acetaminophen simultaneously.",
    },
    {
        "drugs": {"fluconazole", "atorvastatin"},
        "description": "Fluconazole may increase blood levels of Atorvastatin, potentially increasing muscle-related side effect risks. Discuss this with your doctor or pharmacist.",
    },
]


def _clean_drug_name(name: str) -> str:
    """Normalize drug name by stripping dosage, form prefixes, and punctuation."""
    cleaned = re.sub(r"^(?:tab|cap|syp|inj|tab\.|cap\.|syp\.|inj\.)\s+", "", name.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def get_rxcui(drug_name: str) -> str | None:
    """Lookup RxCUI identifier from RxNav API."""
    clean_name = _clean_drug_name(drug_name)
    if not clean_name:
        return None
    resp = requests.get(
        RXNAV_RXCUI_URL,
        params={"name": clean_name},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 200:
        data = resp.json()
        id_group = data.get("idGroup", {})
        rxnorm_ids = id_group.get("rxnormId", [])
        if rxnorm_ids:
            return str(rxnorm_ids[0])
    return None


def check_interactions_api(rxcuis: list[str]) -> list[str]:
    """Query RxNav interaction API for pairs of RxCUIs."""
    if len(rxcuis) < 2:
        return []

    notes = []
    rxcui_str = "+".join(rxcuis)
    resp = requests.get(
        f"{RXNAV_INTERACTION_URL}?rxcuis={rxcui_str}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code == 200:
        data = resp.json()
        type_group = data.get("interactionTypeGroup", [])
        for tg in type_group:
            for itype in tg.get("interactionType", []):
                for pair in itype.get("interactionPair", []):
                    desc = pair.get("description", "")
                    if desc:
                        notes.append(
                            f"Potential interaction: {desc}. Please discuss this with your doctor or pharmacist."
                        )

    return notes


def check_local_interactions(drug_names: list[str]) -> list[str]:
    """Check drug names against curated local interaction database."""
    notes = []
    cleaned_drugs = [_clean_drug_name(d) for d in drug_names]

    for item in KNOWN_INTERACTIONS:
        req_drugs = item["drugs"]
        # Check if all drugs in the interaction pair are present in the list
        matched_count = 0
        for req in req_drugs:
            if any(req in d for d in cleaned_drugs):
                matched_count += 1
        if matched_count >= len(req_drugs):
            notes.append(item["description"])

    return notes


def check_interactions(prescription_items: list[dict]) -> tuple[list[str], list[str]]:
    """Analyze prescription items for potential drug-drug interactions.

    Returns:
        tuple: (interaction_notes: list[str], warnings: list[str])
    """
    notes = []
    warnings = []
    drug_names = [item.get("drug", "") for item in prescription_items if item.get("drug")]

    if len(drug_names) < 2:
        return notes, warnings

    # 1. Local curated interaction check (instant and works offline)
    local_notes = check_local_interactions(drug_names)
    notes.extend(local_notes)

    # 2. Online RxNav check with network fault-tolerance
    try:
        rxcuis = []
        for name in drug_names:
            cui = get_rxcui(name)
            if cui:
                rxcuis.append(cui)

        if len(rxcuis) >= 2:
            api_notes = check_interactions_api(rxcuis)
            for an in api_notes:
                if an not in notes:
                    notes.append(an)
    except Exception as err:
        logger.warning("Online RxNav API interaction check failed: %s", err)
        warnings.append(
            "Online drug interaction check could not be completed due to a network connection issue. "
            "Please review all prescribed medicines with your doctor or pharmacist."
        )

    return notes, warnings


def check_indication(
    prescription_items: list[dict],
    doctor_dx: str,
    doctor_dx_matched: str | None = None,
) -> list[str]:
    """Check if prescribed medications fit the stated diagnosis.

    Example: Antibiotics prescribed for a diagnosis stated or classified as viral.
    All notes are framed as discussion points with the doctor or pharmacist.
    """
    notes = []
    dx_lower = (doctor_dx or "").lower()
    is_viral = (
        doctor_dx_matched == "viral_upper_respiratory_infection"
        or "viral" in dx_lower
        or "common cold" in dx_lower
        or "flu" in dx_lower
    )

    prescribed_antibiotics = []
    for item in prescription_items:
        raw_drug = item.get("drug", "")
        clean_drug = _clean_drug_name(raw_drug)
        if any(ab in clean_drug for ab in ANTIBIOTIC_KEYWORDS):
            prescribed_antibiotics.append(raw_drug)

    if is_viral and prescribed_antibiotics:
        drugs_str = ", ".join(prescribed_antibiotics)
        notes.append(
            f"An antibiotic ({drugs_str}) is included alongside a diagnosis of a viral condition. "
            f"Antibiotics treat bacterial infections rather than viral illnesses. "
            f"You may wish to discuss this with your doctor or pharmacist to understand if it is intended "
            f"to treat a suspected secondary bacterial infection, or whether supportive care is sufficient."
        )

    return notes


def check_treatment_gaps(
    prescription_items: list[dict],
    top_conditions: list[dict],
    verdict: str,
) -> list[str]:
    """Check whether the current prescription addresses candidate conditions when escalating."""
    notes = []
    if verdict != "ESCALATE" or not top_conditions:
        return notes

    top_condition = top_conditions[0]
    cond_name = top_condition.get("name", "").replace("_", " ").title()
    specialist = top_condition.get("specialist", "specialist")

    notes.append(
        f"Because some of your findings may warrant further evaluation for conditions such as {cond_name}, "
        f"please discuss with a {specialist} whether any additional or different therapy is needed. "
        f"Please continue your current medicines as prescribed and discuss any potential treatment adjustments with your doctor or pharmacist."
    )
    return notes


def check_prescription(
    prescription_items: list[dict],
    doctor_dx: str,
    top_conditions: list[dict] | None = None,
    verdict: str = "",
    doctor_dx_matched: str | None = None,
) -> dict[str, Any]:
    """Execute complete prescription review.

    Combines interaction checks, indication alignment, treatment gap discussion notes,
    and any network warnings.

    Returns:
        dict: {'discussion_notes': list[str], 'warnings': list[str]}
    """
    top_conditions = top_conditions or []
    interaction_notes, warnings = check_interactions(prescription_items)
    indication_notes = check_indication(prescription_items, doctor_dx, doctor_dx_matched)
    gap_notes = check_treatment_gaps(prescription_items, top_conditions, verdict)

    all_notes = []
    for note in interaction_notes + indication_notes + gap_notes:
        if note not in all_notes:
            all_notes.append(note)

    return {
        "discussion_notes": all_notes,
        "warnings": warnings,
    }
