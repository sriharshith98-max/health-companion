"""Lab normalization and flagging module for Second-Opinion Companion.

Normalizes test aliases and evaluates values against laboratory or reference ranges,
flagging LOW, NORMAL, HIGH, or CRITICAL states according to clinical thresholds.
"""

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Path to standard reference ranges
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
REF_FILE = os.path.join(DATA_DIR, "lab_reference.json")

_REFERENCE_CACHE: dict[str, Any] | None = None


def _load_reference_data() -> dict[str, Any]:
    """Load lab reference ranges and alias mappings from data/lab_reference.json."""
    global _REFERENCE_CACHE
    if _REFERENCE_CACHE is not None:
        return _REFERENCE_CACHE

    if os.path.exists(REF_FILE):
        try:
            with open(REF_FILE, "r", encoding="utf-8") as f:
                _REFERENCE_CACHE = json.load(f)
                return _REFERENCE_CACHE
        except Exception as exc:
            logger.error("Failed to load lab_reference.json: %s", exc)

    _REFERENCE_CACHE = {"tests": {}, "aliases": {}}
    return _REFERENCE_CACHE


def normalize_test_name(test_name: str) -> str:
    """Map common laboratory test aliases to standardized canonical names.

    Args:
        test_name: Raw test name string (e.g. 'Hb', 'Total Leukocyte Count').

    Returns:
        Canonical test name string.
    """
    if not test_name:
        return ""

    ref_data = _load_reference_data()
    aliases = ref_data.get("aliases", {})
    tests = ref_data.get("tests", {})

    cleaned = test_name.strip().lower()
    cleaned = re.sub(r"[\(\)\[\]]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Direct match in canonical tests
    if cleaned in tests:
        return cleaned

    # Direct match in aliases
    if cleaned in aliases:
        return aliases[cleaned]

    # Partial / substring match in aliases
    for alias_key, canonical in aliases.items():
        if alias_key == cleaned or f" {alias_key} " in f" {cleaned} ":
            return canonical

    return cleaned


def flag_values(lab_results: list[dict]) -> list[dict]:
    """Flag a list of lab results with LOW, NORMAL, HIGH, or CRITICAL.

    Evaluation hierarchy:
    1. Uses the report's own reference range if provided.
    2. Falls back to reference range in data/lab_reference.json if available.
    3. Evaluates against critical alert thresholds.

    Args:
        lab_results: List of extracted lab dicts:
                     [{test: str, value: float|str, unit: str|None, ref_low: float|None, ref_high: float|None, ...}]

    Returns:
        Augmented list of dicts with:
        - 'normalized_test': canonical name
        - 'status': 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL' | 'INDETERMINATE'
        - 'is_critical': bool
        - 'effective_ref_low': float | None
        - 'effective_ref_high': float | None
    """
    ref_data = _load_reference_data()
    canonical_tests = ref_data.get("tests", {})

    flagged_results = []

    for item in lab_results:
        raw_test = str(item.get("test", "")).strip()
        norm_test = normalize_test_name(raw_test)
        ref_entry = canonical_tests.get(norm_test, {})

        # 1. Determine effective reference range
        report_low = item.get("ref_low")
        report_high = item.get("ref_high")

        eff_low = report_low if report_low is not None else ref_entry.get("ref_low")
        eff_high = report_high if report_high is not None else ref_entry.get("ref_high")

        # Convert to float if possible
        try:
            eff_low = float(eff_low) if eff_low is not None else None
        except (ValueError, TypeError):
            eff_low = None

        try:
            eff_high = float(eff_high) if eff_high is not None else None
        except (ValueError, TypeError):
            eff_high = None

        # Critical thresholds
        crit_low = ref_entry.get("critical_low")
        crit_high = ref_entry.get("critical_high")

        val = item.get("value")
        status = "NORMAL"
        is_critical = False

        # Attempt numeric comparison
        try:
            num_val = float(val) if val is not None else None
        except (ValueError, TypeError):
            num_val = None

        if num_val is not None:
            # Check critical thresholds first
            if crit_low is not None and num_val <= crit_low:
                status = "CRITICAL"
                is_critical = True
            elif crit_high is not None and num_val >= crit_high:
                status = "CRITICAL"
                is_critical = True
            elif eff_low is not None and num_val < eff_low:
                status = "LOW"
            elif eff_high is not None and num_val > eff_high:
                status = "HIGH"
            else:
                status = "NORMAL"
        else:
            # Qualitative evaluation (e.g. "Positive" / "Reactive")
            val_str = str(val).strip().lower()
            if any(q in val_str for q in ["positive", "reactive", "detected"]):
                status = "HIGH"
            elif any(q in val_str for q in ["negative", "non-reactive", "not detected"]):
                status = "NORMAL"
            else:
                status = item.get("status") or "INDETERMINATE"

        unit = item.get("unit") or ref_entry.get("unit")

        flagged_results.append({
            "test": raw_test,
            "normalized_test": norm_test,
            "value": num_val if num_val is not None else val,
            "unit": unit,
            "ref_low": report_low,
            "ref_high": report_high,
            "effective_ref_low": eff_low,
            "effective_ref_high": eff_high,
            "status": status,
            "is_critical": is_critical,
        })

    return flagged_results
