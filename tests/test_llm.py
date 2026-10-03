"""Unit tests for core/llm.py."""

import json
from unittest.mock import MagicMock, patch
import pytest

from core.llm import (
    call_llm,
    get_api_key,
    parse_json_safely,
    strip_code_fences,
)


def test_missing_api_key_raises_friendly_error(monkeypatch):
    """Test that missing or placeholder GEMINI_API_KEY raises a friendly ValueError."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY is missing or invalid"):
        get_api_key()

    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_api_key_here")
    with pytest.raises(ValueError, match="GEMINI_API_KEY is missing or invalid"):
        get_api_key()


def test_strip_code_fences():
    """Test that code fences are correctly stripped."""
    fenced_json = "```json\n{\"test\": 123}\n```"
    assert strip_code_fences(fenced_json) == '{"test": 123}'

    fenced_generic = "```\n{\"status\": \"ok\"}\n```"
    assert strip_code_fences(fenced_generic) == '{"status": "ok"}'

    unfenced = '{"status": "ok"}'
    assert strip_code_fences(unfenced) == '{"status": "ok"}'


def test_parse_json_safely():
    """Test safe JSON parsing with code fences and surrounding text."""
    # Standard clean JSON
    assert parse_json_safely('{"key": "value"}') == {"key": "value"}
    
    # Fenced JSON
    assert parse_json_safely('```json\n{"verdict": "AGREE"}\n```') == {"verdict": "AGREE"}

    # JSON with conversational preamble
    with_preamble = 'Here is your result:\n{"verdict": "ESCALATE", "urgency": "soon"}\nHope this helps!'
    assert parse_json_safely(with_preamble) == {"verdict": "ESCALATE", "urgency": "soon"}

    # Array JSON
    assert parse_json_safely('```\n[1, 2, 3]\n```') == [1, 2, 3]


def test_call_llm_valid_json(monkeypatch):
    """Test call_llm returning valid JSON when API key is present."""
    monkeypatch.setenv("GEMINI_API_KEY", "valid_test_api_key")

    mock_response = '```json\n{"verdict": "AGREE", "score": 0.95}\n```'
    with patch("core.llm._invoke_gemini", return_value=mock_response) as mock_invoke:
        result = call_llm("Analyze symptoms", as_json=True)
        assert result == {"verdict": "AGREE", "score": 0.95}
        assert mock_invoke.call_count == 1


def test_call_llm_retry_on_invalid_json(monkeypatch):
    """Test that invalid JSON triggers retry and succeeds on valid response."""
    monkeypatch.setenv("GEMINI_API_KEY", "valid_test_api_key")

    # First attempt returns malformed JSON, second attempt returns valid JSON
    responses = [
        "This is not valid JSON at all {broken",
        '```json\n{"verdict": "ESCALATE", "retry_success": true}\n```',
    ]

    with patch("core.llm._invoke_gemini", side_effect=responses) as mock_invoke:
        result = call_llm("Analyze case", as_json=True, max_retries=2)
        assert result == {"verdict": "ESCALATE", "retry_success": True}
        assert mock_invoke.call_count == 2
        # Verify the second prompt contained retry guidance
        second_prompt = mock_invoke.call_args_list[1][0][0]
        assert "SYSTEM INSTRUCTION" in second_prompt


def test_call_llm_exhausted_retries_raises_error(monkeypatch):
    """Test that exhausting retries raises a clear ValueError."""
    monkeypatch.setenv("GEMINI_API_KEY", "valid_test_api_key")

    with patch("core.llm._invoke_gemini", return_value="Invalid json text") as mock_invoke:
        with pytest.raises(ValueError, match="Failed to obtain valid JSON from LLM after 2 retries"):
            call_llm("Analyze case", as_json=True, max_retries=2)
        assert mock_invoke.call_count == 3  # initial + 2 retries


def test_call_llm_as_text(monkeypatch):
    """Test call_llm with as_json=False returns raw string."""
    monkeypatch.setenv("GEMINI_API_KEY", "valid_test_api_key")

    with patch("core.llm._invoke_gemini", return_value="  Plain text response  ") as mock_invoke:
        result = call_llm("Summarize", as_json=False)
        assert result == "Plain text response"
        assert mock_invoke.call_count == 1
