from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import requests

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import (
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import PromptBuilderPort, TranslatorPort
from epub_translate_cli.infrastructure.llm.prompt_builder import PromptBuilder
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

# Maximum ratio of translated length to source length before we suspect a context leak.
MAX_TRANSLATION_LEN_RATIO = 3.0

# Naive HTML-tag injection detector: "<" followed by a word character.
_HTML_TAG_RE = re.compile(r"<\w")

# Matches when the model echoes back prompt markers from the user message.
# Covers the current English-only prompt labels and the <<<...>>> fence pattern.
_LEAKED_PROMPT_RE = re.compile(
    r"^.*(?:TEXT TO TRANSLATE|CHAPTER CONTEXT)\s*(?::\s*)?",
    re.IGNORECASE | re.DOTALL,
)

# Matches when the model echoes back the full fence-delimited text block
# (i.e., reproduces the "<<<\n...\n>>>" block from the user prompt).
_FENCE_ECHO_RE = re.compile(r"^.*>>>\s*", re.DOTALL)


@dataclass(frozen=True)
class OllamaTranslator(TranslatorPort):
    """Translator adapter that calls Ollama /api/chat with system/user role split."""

    settings: TranslationSettings
    base_url: str = "http://localhost:11434"
    timeout_s: float = -1.0
    prompt_builder: PromptBuilderPort = field(default_factory=PromptBuilder)

    @staticmethod
    def _chat_url(base_url: str) -> str:
        """Build Ollama chat endpoint URL."""
        return f"{base_url}/api/chat"

    def _chat_payload(self, request: TranslationRequest) -> dict[str, object]:
        """Build Ollama /api/chat request payload."""
        return {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt_builder.build_system_prompt(self.settings),
                },
                {
                    "role": "user",
                    "content": self.prompt_builder.build_user_prompt(request),
                },
            ],
            "stream": False,
            "options": {"temperature": self.settings.temperature},
        }

    def _post_chat(self, payload: dict[str, object]) -> requests.Response:
        """Send HTTP request to Ollama /api/chat and map transport errors to retryable ones."""
        try:
            return requests.post(
                self._chat_url(self.base_url),
                json=payload,
                timeout=None if self.timeout_s < 0 else self.timeout_s,
            )
        except requests.RequestException as exc:
            raise RetryableTranslationError(str(exc)) from exc

    @staticmethod
    def _validate_response_status(resp: requests.Response) -> None:
        """Validate HTTP status code and raise mapped domain errors."""
        if resp.status_code >= 500:
            raise RetryableTranslationError(f"Ollama server error: {resp.status_code}")
        if resp.status_code >= 400:
            raise NonRetryableTranslationError(
                f"Ollama request failed: {resp.status_code} {resp.text}"
            )

    @staticmethod
    def _parse_payload(resp: requests.Response) -> dict[str, object]:
        """Parse Ollama JSON payload and convert malformed JSON to retryable error."""
        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise RetryableTranslationError("Invalid JSON from Ollama") from exc
        if not isinstance(payload, dict):
            raise RetryableTranslationError("Unexpected JSON payload shape from Ollama")
        return payload

    @staticmethod
    def _response_text(payload: dict[str, object]) -> str:
        """Extract raw translated text from Ollama /api/chat response payload."""
        message = payload.get("message")
        if not isinstance(message, dict):
            raise RetryableTranslationError("Missing 'message' field in Ollama response")
        raw_text = str(message.get("content") or "").strip()
        if not raw_text:
            raise RetryableTranslationError("Empty 'message.content' in Ollama response")
        return raw_text

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        """Translate one request via Ollama /api/chat and return sanitized translated text."""
        logger.debug(
            "Calling Ollama | model=%s source=%s target=%s text_len=%s",
            self.settings.model,
            self.settings.source_lang,
            self.settings.target_lang,
            len(request.text),
        )

        response = self._post_chat(self._chat_payload(request))
        self._validate_response_status(response)
        payload = self._parse_payload(response)
        raw_text = self._response_text(payload)
        clean_text = _sanitise_response(raw_text, request.text)

        logger.debug(
            "Ollama response received | raw_len=%s clean_len=%s",
            len(raw_text),
            len(clean_text),
        )
        return TranslationResponse(translated_text=clean_text)


def _sanitise_response(raw: str, source_text: str) -> str:
    """Strip leaked prompt/context sections and surrounding quotes from model response."""
    text = raw

    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    # Strip if model echoed a prompt label (e.g., "TEXT TO TRANSLATE: ...").
    match = _LEAKED_PROMPT_RE.search(text)
    if match:
        after = text[match.end() :].strip()
        if after:
            logger.warning(
                "Stripped leaked prompt marker from response | stripped=%d remaining=%d",
                len(text) - len(after),
                len(after),
            )
            text = after

    # Strip if model echoed the full fence-delimited text block ("<<<\n...\n>>>").
    fence_match = _FENCE_ECHO_RE.search(text)
    if fence_match and "<<<" in text[: fence_match.end()]:
        after = text[fence_match.end() :].strip()
        if after:
            logger.warning(
                "Stripped fence-echoed block from response | stripped=%d remaining=%d",
                len(text) - len(after),
                len(after),
            )
            text = after

    if not text:
        raise RetryableTranslationError("Empty translation after sanitization")

    if _HTML_TAG_RE.search(text):
        raise RetryableTranslationError(
            f"HTML tag injection detected in translation: {text[:100]!r}"
        )

    if source_text and len(text) > MAX_TRANSLATION_LEN_RATIO * len(source_text):
        raise RetryableTranslationError(
            f"Translation is {len(text) / len(source_text):.1f}x the source length "
            f"({len(text)} vs {len(source_text)} chars) – possible context leak"
        )

    return text
