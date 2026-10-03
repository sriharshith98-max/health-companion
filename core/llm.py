"""LLM wrapper for Second-Opinion Companion.

Handles communication with the Google Gemini API, enforces JSON-only responses,
and performs retries on invalid output.
"""

import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Ensure environment variables from .env are loaded
load_dotenv()


def get_api_key() -> str:
    """Retrieve and validate the Gemini API key from environment variables.
    
    Returns:
        The valid API key string.
        
    Raises:
        ValueError: If GEMINI_API_KEY is not set or placeholder.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not api_key.strip() or api_key.strip().startswith("your_"):
        raise ValueError(
            "GEMINI_API_KEY is missing or invalid. "
            "Please configure your Gemini API key in the .env file or environment variables."
        )
    return api_key.strip()


def strip_code_fences(text: str) -> str:
    """Strip markdown code block fences (e.g., ```json ... ```) from text."""
    text = text.strip()
    # Match markdown code block ```json ... ``` or ``` ... ```
    fence_pattern = r"^```(?:json|JSON)?\s*\n?(.*?)\n?```$"
    match = re.search(fence_pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback line-by-line check if regex didn't catch nested formatting
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
    return text


def parse_json_safely(raw_text: str) -> dict | list:
    """Parse JSON text after stripping code fences and extracting JSON structures."""
    cleaned = strip_code_fences(raw_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Attempt to locate first { ... } or [ ... ] block
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        first_bracket = cleaned.find("[")
        last_bracket = cleaned.rfind("]")
        
        # Decide if candidate is object or array
        is_object = (first_brace != -1 and last_brace != -1 and 
                     (first_bracket == -1 or first_brace < first_bracket))
        if is_object:
            candidate = cleaned[first_brace : last_brace + 1]
            return json.loads(candidate)
        elif first_bracket != -1 and last_bracket != -1:
            candidate = cleaned[first_bracket : last_bracket + 1]
            return json.loads(candidate)
        raise


FALLBACK_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-3.5-flash",
]


def _invoke_gemini(prompt: str, model_name: str, api_key: str) -> str:
    """Invoke the Gemini model with automatic candidate fallback if model is deprecated or busy."""
    candidates = [model_name] + [m for m in FALLBACK_MODELS if m != model_name]
    last_exc = None

    for candidate in candidates:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=candidate,
                contents=prompt,
            )
            if response.text is not None:
                return response.text
        except Exception as exc:
            last_exc = exc
            # Fallback to legacy client if needed
            try:
                import google.generativeai as legacy_genai
                legacy_genai.configure(api_key=api_key)
                model = legacy_genai.GenerativeModel(candidate)
                response = model.generate_content(prompt)
                if response.text is not None:
                    return response.text
            except Exception:
                pass
            logger.warning("Model %s invocation error: %s. Trying fallback...", candidate, exc)

    if last_exc:
        raise last_exc
    raise ValueError("Gemini returned an empty response.")


def call_llm(
    prompt: str,
    as_json: bool = True,
    model_name: str | None = None,
    max_retries: int = 2,
) -> Any:
    """Send prompt to Gemini model and optionally parse JSON response with retries.

    Args:
        prompt: The input prompt string.
        as_json: If True, strips code fences and parses JSON, retrying on failure.
        model_name: Optional override for model name. Defaults to GEMINI_MODEL env var or 'gemini-flash-latest'.
        max_retries: Maximum number of retry attempts on invalid JSON (default: 2).

    Returns:
        Parsed dict/list if as_json=True, else raw text string.

    Raises:
        ValueError: If GEMINI_API_KEY is missing or if JSON parsing fails after retries.
    """
    api_key = get_api_key()
    resolved_model = model_name or os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    current_prompt = prompt
    last_error: Exception | None = None
    raw_response: str = ""

    attempts = max_retries + 1
    for attempt in range(attempts):
        raw_response = _invoke_gemini(current_prompt, resolved_model, api_key)
        
        if not as_json:
            return raw_response.strip()

        try:
            parsed = parse_json_safely(raw_response)
            return parsed
        except (json.JSONDecodeError, ValueError) as err:
            last_error = err
            logger.warning(
                "LLM output was not valid JSON (attempt %d/%d): %s",
                attempt + 1,
                attempts,
                err,
            )
            if attempt < max_retries:
                # Add retry instructions
                current_prompt = (
                    f"{prompt}\n\n"
                    f"[SYSTEM INSTRUCTION: Your previous response could not be parsed as valid JSON.\n"
                    f"Error: {err}\n"
                    f"Output received was:\n{raw_response}\n"
                    f"Please output ONLY strictly valid, RFC 8259 compliant JSON without any code fences, "
                    f"markdown backticks, or conversational commentary.]"
                )

    raise ValueError(
        f"Failed to obtain valid JSON from LLM after {max_retries} retries. "
        f"Last error: {last_error}\nRaw output received: {raw_response}"
    )
