"""Document and image ingestion module for Second-Opinion Companion.

Extracts text from PDF, images, DOCX, and TXT files, and classifies document types.
Adheres to safety rules:
- Imaging reports are summarized as written, never diagnosed from raw scans.
- Symptom photos are described neutrally and never diagnosed.
- File size limit enforced (10 MB).
"""

import io
import logging
import os
from typing import Any
import docx
import pdfplumber
from PIL import Image
import pytesseract

from core.llm import call_llm

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

VALID_DOC_TYPES = {
    "lab_report",
    "prescription",
    "doctor_notes_or_discharge_summary",
    "imaging_report",
    "symptom_photo",
    "other",
    "unknown",
}


def _get_file_size(file: Any) -> int:
    """Get the size in bytes of a file path, BytesIO, or UploadedFile."""
    if isinstance(file, (str, os.PathLike)):
        try:
            if os.path.exists(file):
                return os.path.getsize(file)
            return len(str(file).encode("utf-8"))
        except Exception:
            return len(str(file).encode("utf-8"))
    elif hasattr(file, "size") and isinstance(file.size, int):
        return file.size
    elif hasattr(file, "getbuffer"):
        return len(file.getbuffer())
    elif hasattr(file, "getvalue"):
        return len(file.getvalue())
    elif hasattr(file, "seek") and hasattr(file, "tell"):
        current_pos = file.tell()
        file.seek(0, io.SEEK_END)
        size = file.tell()
        file.seek(current_pos)
        return size
    return 0


def _get_filename(file: Any) -> str:
    """Extract a filename string from a file object or path."""
    if isinstance(file, (str, os.PathLike)):
        return os.path.basename(str(file))
    elif hasattr(file, "name"):
        return str(file.name)
    return "uploaded_file"


def _extract_from_pdf(file: Any) -> tuple[str, list[str]]:
    """Extract text from a PDF file using pdfplumber with OCR fallback."""
    text_content = []
    warnings = []
    
    try:
        with pdfplumber.open(file) as pdf:
            if not pdf.pages:
                warnings.append("The PDF file contains no pages.")
                return "", warnings

            for page_idx, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_content.append(page_text.strip())
                else:
                    # Possible scanned page, attempt image extraction & OCR
                    try:
                        page_image = page.to_image(resolution=150).original
                        ocr_text = pytesseract.image_to_string(page_image).strip()
                        if ocr_text:
                            text_content.append(ocr_text)
                    except Exception as err:
                        logger.debug("OCR on PDF page %d skipped: %s", page_idx, err)

        full_text = "\n\n".join(text_content).strip()
        if not full_text:
            warnings.append(
                "PDF appears to be scanned or contains no selectable text. "
                "Text extraction was minimal or empty."
            )
        elif len(full_text) < 30:
            warnings.append("Extracted text from PDF is very short. Please verify document clarity.")
        return full_text, warnings
    except Exception as exc:
        warnings.append(f"Failed to read PDF: {str(exc)}")
        return "", warnings


def _extract_from_image(file: Any) -> tuple[str, list[str]]:
    """Extract text or visual information from an image file."""
    warnings = []
    extracted_text = ""

    try:
        if isinstance(file, (str, os.PathLike)):
            img = Image.open(file)
        else:
            if hasattr(file, "seek"):
                file.seek(0)
            img = Image.open(file)

        # Convert to RGB if needed (e.g. for RGBA, P, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # 1. Try local OCR via pytesseract
        try:
            ocr_result = pytesseract.image_to_string(img).strip()
            if ocr_result:
                extracted_text = ocr_result
        except Exception as ocr_err:
            logger.debug("Local OCR unavailable or failed: %s", ocr_err)

        # 2. If OCR produced no text, try Gemini Vision fallback if key exists
        if not extracted_text:
            try:
                from core.llm import get_api_key
                api_key = get_api_key()
                from google import genai
                client = genai.Client(api_key=api_key)
                model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
                
                # Convert img to bytes
                buf = io.BytesIO()
                img.save(buf, format="JPEG")
                img_bytes = buf.getvalue()
                
                prompt = (
                    "Extract all readable medical text from this document or photo. "
                    "If this is a photo of a rash, wound, or physical symptom, describe it "
                    "neutrally (color, visible characteristics, approximate location) without "
                    "offering a diagnosis or medical speculation."
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        genai.types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                        prompt,
                    ],
                )
                if response.text and response.text.strip():
                    extracted_text = response.text.strip()
            except Exception as vision_err:
                logger.debug("Vision fallback unavailable or failed: %s", vision_err)

        if not extracted_text:
            warnings.append(
                "No readable text could be extracted from the image. "
                "If this is a physical symptom photo, you may describe it manually in the symptoms box."
            )
        return extracted_text, warnings
    except Exception as exc:
        warnings.append(f"Failed to process image file: {str(exc)}")
        return "", warnings


def _extract_from_docx(file: Any) -> tuple[str, list[str]]:
    """Extract text from a DOCX file."""
    warnings = []
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        doc = docx.Document(file)
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        
        # Also extract table text
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)

        full_text = "\n".join(paragraphs).strip()
        if not full_text:
            warnings.append("The DOCX file contains no text.")
        return full_text, warnings
    except Exception as exc:
        warnings.append(f"Failed to read DOCX file: {str(exc)}")
        return "", warnings


def _extract_from_txt(file: Any) -> tuple[str, list[str]]:
    """Extract text from a TXT file."""
    warnings = []
    try:
        if isinstance(file, (str, os.PathLike)):
            with open(file, "rb") as f:
                content_bytes = f.read()
        else:
            if hasattr(file, "seek"):
                file.seek(0)
            if hasattr(file, "read"):
                content_bytes = file.read()
                if isinstance(content_bytes, str):
                    content_bytes = content_bytes.encode("utf-8")
            else:
                content_bytes = b""

        # Try UTF-8 then latin-1
        try:
            text = content_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1", errors="replace").strip()

        if not text:
            warnings.append("The TXT file is empty.")
        return text, warnings
    except Exception as exc:
        warnings.append(f"Failed to read TXT file: {str(exc)}")
        return "", warnings


def read_file(file: Any) -> dict:
    """Read an uploaded file and extract text and metadata.

    Supports: PDF, JPG, JPEG, PNG, WEBP, HEIC, DOCX, TXT.
    Enforces maximum file size limit of 10 MB.

    Args:
        file: Uploaded file object or filesystem path.

    Returns:
        dict: {'text': str, 'kind': str, 'warnings': list[str], 'filename': str}
    """
    filename = _get_filename(file)
    size = _get_file_size(file)

    if size > MAX_FILE_SIZE_BYTES:
        return {
            "text": "",
            "kind": "error",
            "warnings": [
                f"File '{filename}' exceeds maximum allowed size of 10 MB ({size / (1024*1024):.1f} MB)."
            ],
            "filename": filename,
        }

    ext = os.path.splitext(filename)[1].lower()
    
    if ext == ".pdf":
        text, warnings = _extract_from_pdf(file)
        kind = "pdf"
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
        text, warnings = _extract_from_image(file)
        kind = "image"
    elif ext in (".docx", ".doc"):
        text, warnings = _extract_from_docx(file)
        kind = "docx"
    elif ext in (".txt", ".text", ".log", ".csv"):
        text, warnings = _extract_from_txt(file)
        kind = "txt"
    else:
        # Attempt fallback to text decoding if unknown extension
        text, warnings = _extract_from_txt(file)
        kind = "unknown"
        if not text:
            warnings.append(f"Unsupported file format '{ext}' for file '{filename}'.")

    return {
        "text": text,
        "kind": kind,
        "warnings": warnings,
        "filename": filename,
    }


def classify_document(text_or_info: str | dict) -> str:
    """Classify document into one of the designated categories.

    Categories:
    - lab_report
    - prescription
    - doctor_notes_or_discharge_summary
    - imaging_report
    - symptom_photo
    - other
    - unknown

    Args:
        text_or_info: Extracted text string or file info dict.

    Returns:
        Standardized document type string.
    """
    text = text_or_info if isinstance(text_or_info, str) else text_or_info.get("text", "")
    text_lower = text.lower()

    # Rule/heuristic pre-check for high-confidence matching and offline resilience
    # 1. Symptom photo / visual skin or lesion description
    if any(k in text_lower for k in ["erythematous", "maculopapular", "rash", "skin lesion", "swelling on", "redness and swelling", "photo of rash", "symptom photo"]):
        return "symptom_photo"
    
    # 2. Imaging report (X-ray, CT, MRI, Ultrasound, PET)
    if any(k in text_lower for k in ["x-ray", "ct scan", "mri", "ultrasound", "sonography", "radiograph", "impression:", "findings:", "chest x-ray"]):
        if any(k in text_lower for k in ["impression:", "findings:", "radiology", "radiograph", "x-ray", "computed tomography"]):
            return "imaging_report"

    # 3. Lab report (CBC, hemoglobin, reference range, platelets, etc.)
    if any(k in text_lower for k in ["reference interval", "ref range", "hemoglobin", "platelet count", "wbc count", "fasting blood sugar", "serum creatinine", "esr", "laboratory report", "lab report", "test name"]):
        return "lab_report"

    # 4. Prescription (Rx, tablets, dosage, frequency, days)
    if any(k in text_lower for k in ["rx", "tab.", "capsule", "mg once daily", "bid", "tid", "od", "po", "dispense", "prescription", "sig:"]):
        return "prescription"

    # 5. Doctor notes or discharge summary
    if any(k in text_lower for k in ["discharge summary", "chief complaint", "clinical notes", "admission date", "history of present illness", "assessment and plan", "hospital course"]):
        return "doctor_notes_or_discharge_summary"

    # If heuristics do not match, attempt LLM classification
    try:
        prompt = (
            f"Classify the following medical document text into exactly ONE category:\n"
            f"- lab_report\n"
            f"- prescription\n"
            f"- doctor_notes_or_discharge_summary\n"
            f"- imaging_report\n"
            f"- symptom_photo\n"
            f"- other\n\n"
            f"Document text:\n\"\"\"\n{text[:2000]}\n\"\"\"\n\n"
            f"Respond with JSON format: {{\"doc_type\": \"<category>\", \"confidence\": \"high|medium|low\"}}"
        )
        res = call_llm(prompt, as_json=True)
        if isinstance(res, dict):
            doc_type = res.get("doc_type", "").strip().lower()
            confidence = res.get("confidence", "high").strip().lower()
            if confidence == "low":
                return "unknown"
            if doc_type in VALID_DOC_TYPES:
                return doc_type
    except Exception as err:
        logger.debug("LLM document classification skipped or failed: %s", err)

    if not text.strip():
        return "unknown"
    return "other"


def process_documents(files: list[Any]) -> list[dict]:
    """Batch process multiple files.

    Args:
        files: List of uploaded files or file paths.

    Returns:
        List of dicts: [{'file': file, 'doc_type': str, 'text': str, 'warnings': list[str]}, ...]
    """
    results = []
    for f in files:
        extracted = read_file(f)
        doc_type = classify_document(extracted["text"])
        results.append({
            "file": f,
            "filename": extracted.get("filename", _get_filename(f)),
            "doc_type": doc_type,
            "text": extracted["text"],
            "warnings": extracted["warnings"],
        })
    return results
