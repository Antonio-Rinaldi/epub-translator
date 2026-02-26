from __future__ import annotations

import pytest

from epub_translate_cli.infrastructure.llm.ollama_translator import _sanitise_response


class TestSanitiseResponse:
    """Tests for _sanitise_response which strips leaked prompt content."""

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

    def test_strips_leaked_italian_marker(self) -> None:
        raw = (
            "CONTESTO DEL CAPITOLO:\n"
            "Qualche contesto...\n\n"
            "TESTO DA TRADURRE:\n"
            "I Paesi Bassi"
        )
        result = _sanitise_response(raw, "THE NETHERLANDS")
        assert result == "I Paesi Bassi"

    def test_strips_leaked_testo_da_tradurre_with_colon(self) -> None:
        raw = "TESTO DA TRADURRE: Capitolo 1"
        result = _sanitise_response(raw, "Chapter 1")
        assert result == "Capitolo 1"

    def test_warns_on_excessive_length_ratio(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        long_response = "A" * 1000
        with caplog.at_level(logging.WARNING):
            result = _sanitise_response(long_response, "Hi")
        assert result == long_response  # kept but warned
        assert "possible context leak" in caplog.text.lower()

    def test_no_warning_for_normal_ratio(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            _sanitise_response("Ciao mondo", "Hello world")
        assert "context leak" not in caplog.text.lower()

    def test_empty_source_no_crash(self) -> None:
        result = _sanitise_response("Tradotto", "")
        assert result == "Tradotto"

    def test_leaked_prompt_with_only_markers_returns_empty(self) -> None:
        """If the model returns only the marker with nothing after, return marker text."""
        raw = "TEXT TO TRANSLATE:"
        result = _sanitise_response(raw, "Hello")
        # The regex strips everything up to the marker; if nothing is left
        # it falls back to the original text.
        assert result == "TEXT TO TRANSLATE:"
