from __future__ import annotations

import json
from dataclasses import dataclass

import requests

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import TranslationRequest, TranslationResponse
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger


logger = create_logger(__name__)


@dataclass(frozen=True)
class OllamaTranslator(TranslatorPort):
    """Translator using Ollama's local HTTP API."""

    base_url: str = "http://localhost:11434"
    timeout_s: float = 120.0

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        prompt = _build_prompt(request)

        logger.debug(
            "Calling Ollama | model=%s source=%s target=%s text_len=%s",
            request.model,
            request.source_lang,
            request.target_lang,
            len(request.text),
        )

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": request.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": request.temperature},
                },
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise RetryableTranslationError(str(exc)) from exc

        if resp.status_code >= 500:
            raise RetryableTranslationError(f"Ollama server error: {resp.status_code}")
        if resp.status_code >= 400:
            raise NonRetryableTranslationError(f"Ollama request failed: {resp.status_code} {resp.text}")

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise RetryableTranslationError("Invalid JSON from Ollama") from exc

        text = (payload.get("response") or "").strip()
        if not text:
            raise RetryableTranslationError("Empty response from Ollama")

        logger.debug("Ollama response received | text_len=%s", len(text))
        return TranslationResponse(translated_text=text)


def _build_prompt(req: TranslationRequest) -> str:
    # Deliberately instruct to output only translated plain text.
    return (
        "You are a professional book translator.\n"
        f"Translate from {req.source_lang} to {req.target_lang}.\n"
        "Preserve meaning, tone, and punctuation.\n"
        "Return ONLY the translated text, no quotes, no explanations.\n\n"
        "CHAPTER CONTEXT (for tone/terminology):\n"
        f"{req.chapter_context}\n\n"
        "TEXT TO TRANSLATE:\n"
        f"{req.text}\n"
    )
