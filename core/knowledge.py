# NEEDS CLINICAL REVIEW
"""Clinical knowledge base for Second-Opinion Companion.

Contains definitions of 12 conditions, red flags, weights, confirmatory tests,
recommended specialists, urgent triggers, and source attributions.
All medical content must be reviewed by qualified clinicians prior to deployment.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

CONDITIONS: list[dict[str, Any]] = [
    {
        "name": "tuberculosis",
        "category": "respiratory",
        "red_flags": [
            {"id": "cough_gt_14d", "label": "Cough longer than 2 weeks", "weight": 3},
            {"id": "night_sweats", "label": "Night sweats", "weight": 2},
            {"id": "weight_loss", "label": "Unexplained weight loss", "weight": 2},
            {"id": "fever", "label": "Low grade or evening fever", "weight": 2},
            {"id": "esr_high", "label": "Raised ESR", "weight": 1},
            {"id": "blood_in_sputum", "label": "Blood in sputum (hemoptysis)", "weight": 3},
        ],
        "confirmatory_tests": [
            "Chest X-ray",
            "Sputum AFB smear / CBNAAT (GeneXpert)",
            "CBC, ESR",
        ],
        "specialist": "Pulmonologist",
        "urgent_triggers": ["blood in sputum", "breathlessness at rest", "hemoptysis"],
        "typical_treatment_keywords": [
            "antitubercular",
            "rifampicin",
            "isoniazid",
            "pyrazinamide",
            "ethambutol",
            "att",
        ],
        "sources": ["WHO Guidelines on Tuberculosis", "ICMR Guidelines"],
    },
    {
        "name": "dengue",
        "category": "infectious",
        "red_flags": [
            {"id": "fever", "label": "High acute fever", "weight": 2},
            {"id": "headache", "label": "Severe headache or retro-orbital pain", "weight": 2},
            {"id": "joint_pain", "label": "Severe joint, muscle, or bone pain", "weight": 2},
            {"id": "platelets_low", "label": "Low platelet count (thrombocytopenia)", "weight": 3},
            {"id": "rash", "label": "Petechiae or skin rash", "weight": 2},
        ],
        "confirmatory_tests": [
            "Dengue NS1 Antigen Test",
            "Dengue IgM/IgG Serology",
            "Complete Blood Count (CBC) with Platelet Monitoring",
        ],
        "specialist": "Infectious Disease Specialist or General Physician",
        "urgent_triggers": [
            "bleeding from gums or nose",
            "severe abdominal pain",
            "persistent vomiting",
            "platelet count < 50000",
            "black stool",
        ],
        "typical_treatment_keywords": ["supportive", "hydration", "fluid therapy", "paracetamol"],
        "sources": ["WHO Dengue Guidelines", "NVBDCP / ICMR Guidelines"],
    },
    {
        "name": "typhoid",
        "category": "infectious",
        "red_flags": [
            {"id": "fever_step_ladder", "label": "Step-ladder prolonged fever (> 5 days)", "weight": 3},
            {"id": "headache", "label": "Persistent dull headache", "weight": 1},
            {"id": "gi_symptoms", "label": "Abdominal discomfort, constipation or diarrhea", "weight": 2},
            {"id": "wbc_low", "label": "Low or normal WBC despite high fever", "weight": 1},
            {"id": "fever_persists_gt_3d_on_treatment", "label": "Fever persisting over 3 days on treatment", "weight": 2},
        ],
        "confirmatory_tests": [
            "Blood Culture for Salmonella typhi",
            "Typhidot / Widal Test",
            "Complete Blood Count (CBC)",
        ],
        "specialist": "General Physician or Gastroenterologist",
        "urgent_triggers": [
            "severe abdominal pain or distension",
            "gastrointestinal bleeding",
            "delirium or high fever encephalopathy",
        ],
        "typical_treatment_keywords": ["ceftriaxone", "azithromycin", "cefixime", "ciprofloxacin"],
        "sources": ["WHO Guidelines on Typhoid", "ICMR Antimicrobial Guidelines"],
    },
    {
        "name": "malaria",
        "category": "infectious",
        "red_flags": [
            {"id": "fever_with_chills", "label": "High intermittent fever with shaking chills and rigors", "weight": 3},
            {"id": "night_sweats", "label": "Profuse sweating after fever spikes", "weight": 2},
            {"id": "headache", "label": "Generalized headache", "weight": 1},
            {"id": "hemoglobin_low", "label": "Anemia or pallor", "weight": 1},
            {"id": "platelets_low", "label": "Thrombocytopenia", "weight": 1},
        ],
        "confirmatory_tests": [
            "Peripheral Blood Smear for Malarial Parasites (thick and thin)",
            "Rapid Diagnostic Test (RDT) for Malaria",
            "Complete Blood Count (CBC)",
        ],
        "specialist": "General Physician or Infectious Disease Specialist",
        "urgent_triggers": [
            "confusion or coma (cerebral malaria)",
            "dark or black urine (blackwater fever)",
            "severe breathlessness",
            "profound jaundice",
        ],
        "typical_treatment_keywords": [
            "artemisinin",
            "artesunate",
            "artemether",
            "lumefantrine",
            "chloroquine",
            "primaquine",
        ],
        "sources": ["WHO Malaria Treatment Guidelines", "NVBDCP Malaria Drug Policy"],
    },
    {
        "name": "diabetes",
        "category": "metabolic",
        "red_flags": [
            {"id": "thirst", "label": "Excessive thirst (polydipsia)", "weight": 3},
            {"id": "frequent_urination", "label": "Frequent urination (polyuria)", "weight": 3},
            {"id": "fatigue", "label": "Unexplained persistent fatigue", "weight": 2},
            {"id": "weight_loss", "label": "Unintentional weight loss", "weight": 2},
            {"id": "slow_healing_wound", "label": "Slow-healing wounds or cuts", "weight": 2},
            {"id": "glucose_high", "label": "Elevated blood glucose (fasting >= 126 mg/dL)", "weight": 4},
        ],
        "confirmatory_tests": [
            "Fasting Plasma Glucose (FPG)",
            "HbA1c (Glycated Hemoglobin)",
            "Postprandial Blood Sugar (PPBS)",
            "Oral Glucose Tolerance Test (OGTT)",
        ],
        "specialist": "Endocrinologist or Diabetologist",
        "urgent_triggers": [
            "blood glucose > 400 mg/dL",
            "fruity breath odor or deep rapid breathing",
            "confusion or drowsiness (DKA/HHS risk)",
        ],
        "typical_treatment_keywords": [
            "metformin",
            "insulin",
            "glimepiride",
            "glipizide",
            "dapagliflozin",
            "empagliflozin",
            "sitagliptin",
            "vildagliptin",
        ],
        "sources": ["ADA Standards of Care in Diabetes", "ICMR Guidelines for Management of Type 2 Diabetes"],
    },
    {
        "name": "anemia",
        "category": "hematology",
        "red_flags": [
            {"id": "fatigue", "label": "Weakness, fatigue, and lethargy", "weight": 2},
            {"id": "breathlessness", "label": "Shortness of breath on mild exertion", "weight": 2},
            {"id": "dizziness", "label": "Lightheadedness, dizziness, or palpitations", "weight": 2},
            {"id": "hemoglobin_low", "label": "Low hemoglobin (< 12 g/dL women, < 13 g/dL men)", "weight": 4},
            {"id": "pale_skin", "label": "Noticeable pallor of skin, tongue, or nail beds", "weight": 2},
        ],
        "confirmatory_tests": [
            "Complete Blood Count (CBC) with RBC Indices (MCV, MCH)",
            "Serum Ferritin and Iron Profile",
            "Peripheral Blood Smear",
        ],
        "specialist": "Hematologist or General Physician",
        "urgent_triggers": [
            "hemoglobin < 7.0 g/dL",
            "chest pain",
            "syncope (fainting)",
            "resting heart rate > 120 with breathlessness",
        ],
        "typical_treatment_keywords": [
            "iron",
            "ferrous ascorbate",
            "ferrous sulfate",
            "folic acid",
            "vitamin b12",
        ],
        "sources": ["WHO Guidelines on Nutritional Anemia", "MoHFW Anemia Mukt Bharat Guidelines"],
    },
    {
        "name": "hypothyroidism",
        "category": "endocrine",
        "red_flags": [
            {"id": "fatigue", "label": "Chronic fatigue and low energy", "weight": 2},
            {"id": "cold_intolerance", "label": "Intolerance to cold environments", "weight": 2},
            {"id": "weight_gain", "label": "Unexplained weight gain", "weight": 2},
            {"id": "constipation", "label": "Persistent constipation", "weight": 1},
            {"id": "dry_skin", "label": "Dry skin and brittle hair", "weight": 1},
            {"id": "tsh_high", "label": "Elevated serum TSH (> 4.5 mIU/L)", "weight": 4},
        ],
        "confirmatory_tests": [
            "Thyroid Function Tests (Serum TSH, Free T4, Free T3)",
            "Anti-Thyroid Peroxidase (Anti-TPO) Antibodies",
        ],
        "specialist": "Endocrinologist",
        "urgent_triggers": [
            "severe hypothermia",
            "profound stupor or confusion (myxedema coma)",
            "marked bradycardia",
        ],
        "typical_treatment_keywords": ["levothyroxine", "thyroxine", "eltroxin", "thyronorm"],
        "sources": ["American Thyroid Association (ATA) Guidelines", "Endocrine Society Clinical Practice Guidelines"],
    },
    {
        "name": "urinary_tract_infection",
        "category": "urology",
        "red_flags": [
            {"id": "dysuria", "label": "Painful or burning urination", "weight": 3},
            {"id": "frequent_urination", "label": "Increased urinary frequency and urgency", "weight": 2},
            {"id": "lower_abdominal_pain", "label": "Lower abdominal or suprapubic pain", "weight": 2},
            {"id": "fever", "label": "Fever with chills or back pain", "weight": 2},
            {"id": "urine_pus_cells", "label": "Cloudy urine or pus cells on urinalysis", "weight": 3},
        ],
        "confirmatory_tests": [
            "Urine Routine and Microscopy (Urine R/M)",
            "Urine Culture and Antibiotic Sensitivity",
        ],
        "specialist": "Urologist or General Physician",
        "urgent_triggers": [
            "high fever with severe flank or back pain (pyelonephritis)",
            "inability to pass urine",
            "blood in urine (gross hematuria)",
            "septic shock signs",
        ],
        "typical_treatment_keywords": [
            "nitrofurantoin",
            "fosfomycin",
            "norfloxacin",
            "ciprofloxacin",
            "cefixime",
            "amoxicillin-clavulanate",
        ],
        "sources": ["IDSA Clinical Practice Guidelines for UTI", "EAU Guidelines on Urological Infections"],
    },
    {
        "name": "pneumonia",
        "category": "respiratory",
        "red_flags": [
            {"id": "fever", "label": "High fever with chills", "weight": 2},
            {"id": "cough", "label": "Cough with discolored or purulent sputum", "weight": 3},
            {"id": "chest_pain", "label": "Sharp pleuritic chest pain aggravated by breathing", "weight": 3},
            {"id": "breathlessness", "label": "Difficulty breathing or rapid respiratory rate", "weight": 3},
            {"id": "wbc_high", "label": "Elevated WBC count (leukocytosis)", "weight": 2},
        ],
        "confirmatory_tests": [
            "Chest X-ray (PA view)",
            "Complete Blood Count (CBC)",
            "Sputum Culture and Gram Stain",
            "Pulse Oximetry (SpO2)",
        ],
        "specialist": "Pulmonologist",
        "urgent_triggers": [
            "oxygen saturation (SpO2) < 92%",
            "severe breathlessness at rest",
            "confusion or cyanosis",
            "blood pressure drop (< 90 mmHg systolic)",
        ],
        "typical_treatment_keywords": [
            "amoxicillin-clavulanate",
            "azithromycin",
            "clarithromycin",
            "ceftriaxone",
            "levofloxacin",
        ],
        "sources": ["ATS/IDSA Community-Acquired Pneumonia Guidelines", "BTS Guidelines on Pneumonia"],
    },
    {
        "name": "hepatitis",
        "category": "gastrointestinal",
        "red_flags": [
            {"id": "jaundice", "label": "Yellowing of eyes or skin (jaundice)", "weight": 4},
            {"id": "dark_urine", "label": "Dark yellow or tea-colored urine", "weight": 3},
            {"id": "fatigue", "label": "Severe fatigue, nausea, and loss of appetite", "weight": 2},
            {"id": "right_upper_quadrant_pain", "label": "Right upper quadrant abdominal discomfort", "weight": 2},
            {"id": "bilirubin_high", "label": "Elevated serum bilirubin or ALT/AST enzymes", "weight": 4},
        ],
        "confirmatory_tests": [
            "Liver Function Tests (Total Bilirubin, SGPT/ALT, SGOT/AST, Alk Phos)",
            "Viral Hepatitis Markers (Anti-HAV IgM, HBsAg, Anti-HCV, Anti-HEV IgM)",
            "Ultrasound Abdomen",
        ],
        "specialist": "Gastroenterologist or Hepatologist",
        "urgent_triggers": [
            "confusion, drowsiness, or altered behavior (hepatic encephalopathy)",
            "easy bleeding or bruising",
            "abdominal swelling (ascites)",
            "persistent uncontrolled vomiting",
        ],
        "typical_treatment_keywords": ["supportive care", "hydration", "antivirals", "avoid hepatotoxic drugs"],
        "sources": ["WHO Guidelines on Viral Hepatitis", "INASL Guidelines on Liver Disease"],
    },
    {
        "name": "chronic_kidney_disease",
        "category": "nephrology",
        "red_flags": [
            {"id": "creatinine_high", "label": "Elevated serum creatinine", "weight": 4},
            {"id": "edema", "label": "Swelling in feet, ankles, legs, or face (edema)", "weight": 3},
            {"id": "fatigue", "label": "Persistent fatigue and weakness", "weight": 2},
            {"id": "foamy_urine", "label": "Foamy or bubbly urine", "weight": 2},
            {"id": "hemoglobin_low", "label": "Normocytic anemia", "weight": 1},
        ],
        "confirmatory_tests": [
            "Serum Creatinine and Blood Urea Nitrogen (with eGFR)",
            "Urine Routine & Albumin-to-Creatinine Ratio (uACR)",
            "Ultrasound Kidneys, Ureters, and Bladder (KUB)",
            "Serum Electrolytes",
        ],
        "specialist": "Nephrologist",
        "urgent_triggers": [
            "serum creatinine > 3.5 mg/dL",
            "severe hyperkalemia",
            "pulmonary edema with acute breathlessness",
            "anuria (no urine output)",
        ],
        "typical_treatment_keywords": [
            "ace inhibitors",
            "arbs",
            "sglt2 inhibitors",
            "erythropoietin",
            "phosphate binders",
            "blood pressure control",
        ],
        "sources": ["KDIGO Clinical Practice Guidelines for CKD", "ICMR Guidelines on Chronic Renal Failure"],
    },
    {
        "name": "viral_upper_respiratory_infection",
        "category": "respiratory",
        "red_flags": [
            {"id": "runny_nose", "label": "Runny nose, nasal congestion, or sneezing", "weight": 3},
            {"id": "sore_throat", "label": "Sore or scratchy throat", "weight": 3},
            {"id": "fever", "label": "Mild fever or low-grade body temperature", "weight": 2},
            {"id": "duration_short", "label": "Duration 2 to 7 days", "weight": 2},
            {"id": "cough", "label": "Mild cough without respiratory distress", "weight": 1},
        ],
        "confirmatory_tests": [
            "Clinical physical examination",
            "Throat swab (if streptococcal pharyngitis is suspected)",
            "Rapid Influenza Test (if seasonal flu suspected)",
        ],
        "specialist": "General Physician or ENT Specialist",
        "urgent_triggers": [
            "difficulty swallowing or breathing (stridor)",
            "fever persisting > 5 days without improvement",
            "severe ear pain or neck stiffness",
        ],
        "typical_treatment_keywords": [
            "paracetamol",
            "rest",
            "hydration",
            "saline nasal spray",
            "antihistamine",
            "steam inhalation",
        ],
        "sources": ["CDC Common Cold and Viral URI Guidelines", "NICE Guidelines on Respiratory Infections"],
    },
]

SPECIALISTS: dict[str, str] = {
    cond["name"]: cond["specialist"] for cond in CONDITIONS
}

# Global set of urgent triggers across all conditions
CRITICAL_RED_FLAGS: set[str] = set()
for _cond in CONDITIONS:
    for _trig in _cond.get("urgent_triggers", []):
        CRITICAL_RED_FLAGS.add(_trig.lower())


def get_conditions() -> list[dict[str, Any]]:
    """Return all conditions in the clinical knowledge base."""
    return CONDITIONS


def get_condition_by_name(name: str) -> dict[str, Any] | None:
    """Find a condition by name or alias."""
    name_clean = name.strip().lower().replace(" ", "_")
    for cond in CONDITIONS:
        if cond["name"] == name_clean:
            return cond
    return None
