"""Unit tests for the clinical knowledge base (core/knowledge.py and data/synonyms.json)."""

import json
import os
import pytest
from core.knowledge import (
    CONDITIONS,
    CRITICAL_RED_FLAGS,
    SPECIALISTS,
    get_condition_by_name,
    get_conditions,
)

EXPECTED_CONDITIONS = {
    "tuberculosis",
    "dengue",
    "typhoid",
    "malaria",
    "diabetes",
    "anemia",
    "hypothyroidism",
    "urinary_tract_infection",
    "pneumonia",
    "hepatitis",
    "chronic_kidney_disease",
    "viral_upper_respiratory_infection",
}

REQUIRED_KEYS = {
    "name",
    "category",
    "red_flags",
    "confirmatory_tests",
    "specialist",
    "urgent_triggers",
    "typical_treatment_keywords",
    "sources",
}


def test_clinical_review_header_comment():
    """Verify that core/knowledge.py contains the mandatory # NEEDS CLINICAL REVIEW header."""
    file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "knowledge.py")
    with open(file_path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    assert first_line == "# NEEDS CLINICAL REVIEW"


def test_twelve_conditions_exist():
    """Acceptance Check: Exactly the 12 specified conditions exist in the knowledge base."""
    all_conds = get_conditions()
    assert len(all_conds) == 12
    found_names = {c["name"] for c in all_conds}
    assert found_names == EXPECTED_CONDITIONS


def test_all_conditions_validate_against_schema():
    """Acceptance Check: All 12 entries validate against schema with red flags, tests, specialist, sources."""
    for cond in CONDITIONS:
        # Check required top-level keys
        for key in REQUIRED_KEYS:
            assert key in cond, f"Condition {cond.get('name')} missing key: {key}"

        # Specialist
        assert isinstance(cond["specialist"], str) and len(cond["specialist"].strip()) > 0

        # Confirmatory tests
        assert isinstance(cond["confirmatory_tests"], list) and len(cond["confirmatory_tests"]) > 0
        for test_item in cond["confirmatory_tests"]:
            assert isinstance(test_item, str) and len(test_item.strip()) > 0

        # Sources
        assert isinstance(cond["sources"], list) and len(cond["sources"]) > 0
        for src in cond["sources"]:
            assert isinstance(src, str) and len(src.strip()) > 0

        # Urgent triggers
        assert isinstance(cond["urgent_triggers"], list) and len(cond["urgent_triggers"]) > 0

        # Typical treatment keywords
        assert isinstance(cond["typical_treatment_keywords"], list) and len(cond["typical_treatment_keywords"]) > 0

        # Red flags validation
        assert isinstance(cond["red_flags"], list) and len(cond["red_flags"]) >= 3
        for rf in cond["red_flags"]:
            assert "id" in rf and isinstance(rf["id"], str) and len(rf["id"]) > 0
            assert "label" in rf and isinstance(rf["label"], str) and len(rf["label"]) > 0
            assert "weight" in rf and isinstance(rf["weight"], int) and rf["weight"] >= 1


def test_specialists_dictionary():
    """Verify SPECIALISTS mapping maps all 12 conditions to non-empty specialist descriptions."""
    assert len(SPECIALISTS) == 12
    for cond_name, spec in SPECIALISTS.items():
        assert cond_name in EXPECTED_CONDITIONS
        assert isinstance(spec, str) and len(spec) > 0


def test_synonyms_file_validity():
    """Verify data/synonyms.json maps to recognized conditions."""
    syn_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "synonyms.json")
    with open(syn_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    groups = data.get("synonym_groups", {})
    assert len(groups) == 12
    for group_name, syn_list in groups.items():
        assert group_name in EXPECTED_CONDITIONS
        assert isinstance(syn_list, list) and len(syn_list) > 0
        # Common cold / regular infection should be in viral URI
        if group_name == "viral_upper_respiratory_infection":
            assert "regular infection" in syn_list
            assert "common cold" in syn_list
