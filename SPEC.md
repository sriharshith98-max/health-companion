# SPEC.md: AI Second-Opinion Companion

## 0. AGENT OPERATING RULES (READ FIRST, FOLLOW ALWAYS)

1. Work on **ONE step at a time**, in order. Never start the next step on your own.
2. Before writing code for a step, post a short **implementation plan** and wait for approval.
3. After finishing a step, run the step's **Acceptance Checks** and post this report:

```
STEP <N> COMPLETE: <step name>
Files created/changed: <list>
Acceptance checks: <each check: PASS / FAIL with a one-line note>
Known issues: <list or "none">
Next step: Step <N+1>: <name>
Should we proceed to Step <N+1>? (yes / fix issues first)
```

4. **Stop and wait** for the user to reply "yes" before continuing. If any check fails, fix it first and re-report.
5. Never hardcode API keys. Read them from `.env`. Make sure `.env` is in `.gitignore`.
6. Obey the **Safety Rules** in Section 3 in every file you write.
7. Keep code simple, commented, and runnable. Prefer fewer files and clear function names over cleverness.

---

## 1. PROJECT OVERVIEW

**Name:** Second-Opinion Companion
**Goal:** A patient uploads their symptoms, medical reports, the doctor's diagnosis, and the prescription. The AI independently analyzes the evidence and compares it with the doctor's diagnosis and treatment.

**Two possible outcomes:**
- **AGREE:** The doctor's diagnosis is consistent with the evidence. Explain why, and list warning signs to watch for.
- **ESCALATE:** The evidence suggests something more than the doctor's diagnosis explains. List the possible conditions, the **tests that would confirm them**, and the **specialist to consult** to verify.
- (A third outcome, **INCONCLUSIVE**, is used when information is insufficient.)

**Follow-ups:** The patient can return to the same case days later, describe new or changing symptoms in a chat, and get a re-assessment: is the condition improving, not improving, or showing something new, and does the treatment need a **medical re-evaluation** (see Section 4.6). The AI never prescribes; it tells the patient when and whom to consult.

**Value:** Helps catch serious conditions earlier (for example, TB, diabetes, or dengue labelled as a "regular infection") by sending patients toward the right tests and specialist.

**It is NOT:** a diagnosis tool, a replacement for a doctor, or a source of instructions to change medicines.

---

## 2. TECH STACK

| Layer | Choice |
|---|---|
| Language | Python 3.10+ |
| UI | Streamlit |
| LLM | Google Gemini API (`gemini-1.5-flash` or newer flash model; configurable in `.env`) |
| PDF text | `pdfplumber` |
| OCR (images/scans) | `pytesseract` + `Pillow` (fallback: send image directly to Gemini) |
| Drug interactions | RxNav API (free, NIH) and/or openFDA |
| Storage | SQLite (`sqlite3`) for case history and trends |
| Charts | Plotly |
| PDF export | `reportlab` or `fpdf2` |
| Config | `python-dotenv` |
| Tests | `pytest` |

---

## 3. SAFETY RULES (NON-NEGOTIABLE)

1. Never state "you have <disease>". Use "possible", "consistent with", or "may be associated with".
2. Never tell the user to **stop, skip, or change** any medicine or dose. Use "discuss this with your doctor or pharmacist".
3. Never output medicine dosages that the system itself suggests.
4. Never say "your doctor is wrong". Use "some findings are not fully explained by the current diagnosis".
5. Every claim must cite its evidence (a symptom, a lab value, or a knowledge-base source).
6. Every report must include the **disclaimer** and a **specialist to verify with**.
7. If any **critical red flag** is present (see `knowledge.py`), `urgency` must be `"urgent"` regardless of LLM output, and the report must say to seek medical care promptly.
8. The LLM may only explain data given to it. It must not invent lab values, tests, or findings.
9. Show the user the extracted data so they can correct mistakes before analysis.
10. Privacy: do not log raw reports to disk by default. Provide a "Delete my data" button.
11. **Follow-ups:** never name a specific drug to start, change, or stop, and never give a dose. When treatment may need changing, say so as "this is worth a medical re-evaluation of your treatment" and direct the user to their doctor.
12. **Follow-ups:** any urgent red flag in a follow-up message overrides everything else and shows the urgent-care notice first.

**Disclaimer text (use verbatim):**
> "This tool provides general health information and is not a medical diagnosis. It cannot replace a qualified doctor. Please confirm any findings with a specialist, and seek urgent care for severe or worsening symptoms."

---

## 4. ARCHITECTURE

### 4.1 Data flow

```
 ┌──────────────────────────── USER (Streamlit UI) ────────────────────────────┐
 │ age, sex, symptoms text, duration, doctor's diagnosis, reports, prescription │
 └───────────────────────────────────┬──────────────────────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  1. INGESTION        │ multi-file upload, type detection, OCR/vision
                          └──────────┬──────────┘
                                     │ raw text
                          ┌──────────▼──────────┐
                          │  2. STRUCTURING      │ LLM → JSON (symptoms, labs, drugs)
                          └──────────┬──────────┘
                                     │ validated JSON
                          ┌──────────▼──────────┐
                          │  3. USER CONFIRMS    │ editable tables
                          └──────────┬──────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
 ┌────────▼────────┐       ┌─────────▼────────┐       ┌─────────▼────────┐
 │ 4. LAB ANALYSIS │       │ 5. CONDITION     │       │ 6. PRESCRIPTION  │
 │ flag LOW/HIGH/  │       │ MATCHER          │       │ CHECK            │
 │ CRITICAL (rules)│       │ red-flag scoring │       │ indication,      │
 └────────┬────────┘       │ + RAG evidence   │       │ interactions     │
          │                └─────────┬────────┘       └─────────┬────────┘
          └──────────────────────────┼──────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ 7. VERDICT ENGINE    │ AGREE / ESCALATE / INCONCLUSIVE
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ 8. REPORT WRITER     │ LLM, grounded, JSON schema
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ 9. SAFETY REVIEWER   │ regex filters + reviewer LLM pass
                          └──────────┬──────────┘
                                     │
                          ┌──────────▼──────────┐
                          │ 10. RESULT UI + PDF  │ + save to SQLite for trends
                          └─────────────────────┘
```

### 4.2 Design principles

- **Rules decide, LLM explains.** Verdicts, flags, and urgency come from deterministic Python. The LLM writes the language only.
- **Grounded generation.** The LLM receives only structured findings and retrieved knowledge. Never raw free-form questions.
- **Fail safe.** When unsure, return INCONCLUSIVE and recommend a doctor visit.
- **Swappable LLM.** All model calls go through `llm.py`.

### 4.3 Folder structure

```
second-opinion/
├── SPEC.md
├── README.md
├── requirements.txt
├── .env                  # GEMINI_API_KEY=...   (never commit)
├── .gitignore
├── app.py                # Streamlit entry point
├── core/
│   ├── __init__.py
│   ├── llm.py            # call_llm(), JSON parsing + retry
│   ├── ingest.py         # file → raw text
│   ├── extract.py        # raw text → structured JSON
│   ├── labs.py           # normalization + flagging
│   ├── knowledge.py      # CONDITIONS, SYNONYMS, SPECIALISTS
│   ├── matcher.py        # scoring + verdict
│   ├── drugcheck.py      # prescription analysis
│   ├── report.py         # LLM report generation
│   ├── safety.py         # output filters
│   ├── storage.py        # SQLite: cases, events, messages
│   ├── followup.py       # follow-up chat on an existing case
│   └── pipeline.py       # verify() chains everything
├── data/
│   ├── lab_reference.json    # fallback reference ranges + critical thresholds
│   ├── synonyms.json         # diagnosis synonym groups
│   └── kb/                   # optional RAG docs (Step 11)
├── ui_template/          # OPTIONAL: your own design (images, style.css, fonts, logo, or HTML template)
├── .streamlit/
│   └── config.toml       # theme colors/fonts (created in Step 10)
├── samples/
│   ├── case_viral_fever/     # AGREE demo
│   ├── case_tb/              # ESCALATE demo
│   └── case_diabetes/        # ESCALATE demo
└── tests/
    ├── test_labs.py
    ├── test_matcher.py
    ├── test_safety.py
    ├── test_cases.py
    └── test_followup.py
```

### 4.4 Core data schemas

**PatientInput**
```json
{
  "age": 34, "sex": "Male",
  "symptoms_text": "string",
  "duration_days": 21,
  "doctor_dx": "regular infection",
  "reports": ["file refs"], "prescription": "file ref"
}
```

**StructuredSymptoms**
```json
{
  "symptoms": ["cough", "night sweats", "weight loss"],
  "duration_days": 21,
  "flags": {"fever": true, "weight_loss": true, "night_sweats": true, "blood_in_sputum": false}
}
```

**LabResult**
```json
{"test": "hemoglobin", "value": 10.2, "unit": "g/dL",
 "ref_low": 13.5, "ref_high": 17.5, "status": "LOW | NORMAL | HIGH | CRITICAL"}
```

**PrescriptionItem**
```json
{"drug": "Amoxicillin", "dose": "500 mg", "frequency": "TID", "duration": "5 days"}
```

**Condition (knowledge base entry)**
```json
{
  "name": "tuberculosis",
  "category": "respiratory",
  "red_flags": [
    {"id": "cough_gt_14d", "label": "Cough longer than 2 weeks", "weight": 3},
    {"id": "night_sweats", "label": "Night sweats", "weight": 2},
    {"id": "weight_loss", "label": "Unexplained weight loss", "weight": 2},
    {"id": "esr_high", "label": "Raised ESR", "weight": 1}
  ],
  "confirmatory_tests": ["Chest X-ray", "Sputum AFB smear / CBNAAT", "CBC, ESR"],
  "specialist": "Pulmonologist",
  "urgent_triggers": ["blood in sputum", "breathlessness at rest"],
  "typical_treatment_keywords": ["antitubercular"],
  "sources": ["WHO", "ICMR"]
}
```

**Verdict**
```json
{
  "verdict": "AGREE | ESCALATE | INCONCLUSIVE",
  "doctor_dx_matched": "viral infection",
  "top_candidates": [{"name": "tuberculosis", "score": 0.78, "evidence": ["..."]}],
  "urgency": "routine | soon | urgent",
  "unexplained_findings": ["night sweats", "weight loss"]
}
```

**FinalReport (LLM output schema)**
```json
{
  "verdict": "...",
  "summary": "2-3 simple sentences",
  "why": ["evidence-based reasons"],
  "possible_conditions": [{"name": "", "why_possible": "", "confidence": "low|medium|high"}],
  "tests_to_confirm": [""],
  "specialist_to_consult": "",
  "prescription_notes": ["points to discuss with doctor/pharmacist"],
  "warning_signs": [""],
  "questions_for_doctor": [""],
  "urgency": "routine | soon | urgent",
  "disclaimer": "verbatim text"
}
```

### 4.5 Matching algorithm

1. Convert symptoms and flagged labs into a set of **active signal IDs** (for example `cough_gt_14d`, `esr_high`).
2. For each condition: `score = sum(weights of matched red flags) / sum(all weights)`.
3. Rank conditions by score. Keep those with `score >= 0.25`.
4. **Doctor dx match:** map `doctor_dx` to a synonym group (`data/synonyms.json`); fall back to a small LLM classification call if no match.
5. **Verdict rules:**
   - If doctor's dx group equals the top candidate's group **and** no urgent trigger → `AGREE`
   - If top candidate (score ≥ 0.5) is **not** in the doctor's dx group → `ESCALATE`
   - If a "regular infection" dx is given and any **duration or severity red flag** fires → `ESCALATE`
   - If fewer than 2 signals are active or the top score < 0.25 → `INCONCLUSIVE`
6. **Urgency:** `urgent` if any `urgent_triggers` or CRITICAL lab; `soon` for ESCALATE; else `routine`.

### 4.6 Follow-up flow (new symptoms days after the first visit)

A **case** is a persistent record. After the first verdict, the patient can return to the same case days later, describe what is happening, and get a re-assessment, including whether treatment may need to be reviewed.

```
 Existing CASE (CaseState + timeline)
        │
        ▼
 User message: "Day 5: fever still there, now stomach pain, taking medicines as told"
        │
 ┌──────▼───────────┐
 │ F1. STRUCTURE     │ new symptoms, onset day, progress (better/same/worse),
 │                   │ medicine adherence, new reports/prescription if uploaded
 └──────┬───────────┘
 ┌──────▼───────────┐
 │ F2. UPDATE STATE  │ merge into CaseState (cumulative symptoms + days since
 │                   │ treatment started + current medicines)
 └──────┬───────────┘
 ┌──────▼───────────┐
 │ F3. RE-MATCH      │ matcher.py on cumulative signals, plus time rules:
 │                   │ e.g. "fever > 3 days on treatment", "new GI symptoms on
 │                   │ antibiotics", "no improvement after expected course"
 └──────┬───────────┘
 ┌──────▼───────────┐
 │ F4. TRAJECTORY    │ IMPROVING | STABLE | NOT_IMPROVING | NEW_CONCERN | URGENT
 └──────┬───────────┘
 ┌──────▼───────────┐
 │ F5. REPLY WRITER  │ grounded LLM reply (schema below) + safety.py
 └──────┬───────────┘
        ▼
 Chat reply + new event saved to the case timeline
```

---

## 5. BUILD STEPS

### STEP 1: Project scaffold and environment
**Build:** folder structure from 4.3, `requirements.txt`, `.gitignore` (include `.env`, `__pycache__`, `*.db`), `.env.example`, minimal `README.md`, empty modules with docstrings.
**Acceptance checks:**
- [ ] `pip install -r requirements.txt` succeeds
- [ ] `streamlit run app.py` shows a placeholder page
- [ ] `.env` is git-ignored
**Checkpoint:** report, then ask to proceed to Step 2.
