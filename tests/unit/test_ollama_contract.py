from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as req_lib

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import TranslationRequest, TranslationSettings
from epub_translate_cli.infrastructure.llm.ollama_translator import OllamaTranslator
from epub_translate_cli.infrastructure.llm.prompt_builder import PromptBuilder

_SETTINGS = TranslationSettings(
    source_lang="en",
    target_lang="it",
    model="test-model",
    temperature=0.2,
    retries=0,
    abort_on_error=False,
)

_REQUEST = TranslationRequest(
    chapter_context="",
    text="Hello world.",
)


def _translator() -> OllamaTranslator:
    return OllamaTranslator(settings=_SETTINGS, prompt_builder=PromptBuilder())


def _mock_response(status: int, json_data: object = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


def test_success_returns_translation() -> None:
    payload = {"message": {"content": "Ciao mondo."}}
    with patch("requests.post", return_value=_mock_response(200, payload)):
        result = _translator().translate(_REQUEST)
    assert result.translated_text == "Ciao mondo."


def test_http_500_raises_retryable() -> None:
    with patch("requests.post", return_value=_mock_response(500)):  # noqa: SIM117
        with pytest.raises(RetryableTranslationError, match="server error"):
            _translator().translate(_REQUEST)


def test_http_400_raises_non_retryable() -> None:
    with patch("requests.post", return_value=_mock_response(400, text="bad request")):  # noqa: SIM117
        with pytest.raises(NonRetryableTranslationError, match="request failed"):
            _translator().translate(_REQUEST)


def test_json_decode_error_raises_retryable() -> None:
    import json as _json

    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = _json.JSONDecodeError("bad json", "", 0)
    with patch("requests.post", return_value=resp):  # noqa: SIM117
        with pytest.raises(RetryableTranslationError):
            _translator().translate(_REQUEST)


def test_empty_message_content_raises_retryable() -> None:
    payload = {"message": {"content": ""}}
    with patch("requests.post", return_value=_mock_response(200, payload)):  # noqa: SIM117
        with pytest.raises(RetryableTranslationError, match="Empty"):
            _translator().translate(_REQUEST)


def test_missing_message_field_raises_retryable() -> None:
    payload = {"response": "legacy field"}
    with patch("requests.post", return_value=_mock_response(200, payload)):  # noqa: SIM117
        with pytest.raises(RetryableTranslationError, match="Missing 'message'"):
            _translator().translate(_REQUEST)


def test_request_exception_raises_retryable() -> None:
    with patch("requests.post", side_effect=req_lib.RequestException("timeout")):  # noqa: SIM117
        with pytest.raises(RetryableTranslationError, match="timeout"):
            _translator().translate(_REQUEST)
