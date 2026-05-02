from __future__ import annotations

import pytest

from epub_translate_cli.domain.errors import RetryableTranslationError
from epub_translate_cli.infrastructure.llm.ollama_translator import _sanitise_response


class TestSanitiseResponse:
    """Tests for _sanitise_response."""

    def test_clean_response_unchanged(self) -> None:
        result = _sanitise_response("Ciao mondo", "Hello world")
        assert result == "Ciao mondo"

    def test_strips_surrounding_double_quotes(self) -> None:
        result = _sanitise_response('"Ciao mondo"', "Hello world")
        assert result == "Ciao mondo"

    def test_strips_surrounding_single_quotes(self) -> None:
        result = _sanitise_response("'Ciao mondo'", "Hello world")
        assert result == "Ciao mondo"

    def test_strips_leaked_text_to_translate_marker(self) -> None:
        raw = (
            "CHAPTER CONTEXT (for tone/terminology):\n"
            "Some context here about the chapter...\n\n"
            "TEXT TO TRANSLATE:\n"
            "Capitolo 1"
        )
        result = _sanitise_response(raw, "Chapter 1")
        assert result == "Capitolo 1"

    def test_italian_markers_no_longer_stripped(self) -> None:
        """Italian markers from an old prompt version are no longer matched."""
        raw = "CONTESTO DEL CAPITOLO:\nQualche contesto...\n\nTESTO DA TRADURRE:\nI Paesi Bassi"
        # The raw text has no HTML injection and is not excessively long → passes through.
        result = _sanitise_response(raw, "x" * 500)
        assert result == raw

    def test_strips_text_to_translate_marker_with_colon(self) -> None:
        raw = "TEXT TO TRANSLATE: Capitolo 1"
        result = _sanitise_response(raw, "Chapter 1")
        assert result == "Capitolo 1"

    def test_empty_result_raises(self) -> None:
        with pytest.raises(RetryableTranslationError, match="Empty"):
            _sanitise_response("", "Hello")

    def test_html_injection_raises(self) -> None:
        with pytest.raises(RetryableTranslationError, match="HTML tag injection"):
            _sanitise_response("<b>Ciao</b>", "Hello")

    def test_excessive_length_raises(self) -> None:
        with pytest.raises(RetryableTranslationError, match="context leak"):
            _sanitise_response("A" * 1000, "Hi")

    def test_empty_source_no_crash(self) -> None:
        result = _sanitise_response("Tradotto", "")
        assert result == "Tradotto"

    def test_leaked_prompt_with_only_markers_returns_original(self) -> None:
        """If the marker matches but nothing follows, the original text is returned."""
        raw = "TEXT TO TRANSLATE:"
        # Use a source long enough that the length ratio check doesn't trigger.
        result = _sanitise_response(raw, "Hello world and more text here to avoid ratio limit")
        assert result == "TEXT TO TRANSLATE:"

    def test_strips_fence_echoed_block(self) -> None:
        """If model echoes the <<<...>>> block, strip it and return what follows."""
        raw = "<<<\nOriginal source text\n>>>\nCiao mondo tradotto."
        result = _sanitise_response(raw, "Original source text")
        assert result == "Ciao mondo tradotto."
