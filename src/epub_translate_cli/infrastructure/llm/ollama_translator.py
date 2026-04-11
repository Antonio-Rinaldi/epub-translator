from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import TranslationRequest, TranslationResponse
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

# Maximum ratio of translated length to source length before we suspect
# the model echoed the context/prompt back in the response.
_MAX_LEN_RATIO = 3.0

# Pattern that matches everything up to (and including) the LAST known
# prompt marker.  Greedy ``.*`` ensures we consume up to the final
# occurrence, so all echoed context/headers are stripped.
_LEAKED_PROMPT_RE = re.compile(
    r"^.*(?:TESTO DA TRADURRE|TEXT TO TRANSLATE|CHAPTER CONTEXT|CONTESTO DEL CAPITOLO)\s*(?::\s*)?",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class PromptBuilder:
    """Builds deterministic translation prompts for Ollama requests."""

    @staticmethod
    def _context_block(chapter_context: str) -> str:
        """Format chapter-level context block used only for style guidance."""
        if not chapter_context:
            return ""
        return (
            "Below is context from the chapter (for tone/terminology only). "
            "Do NOT include this context in your response:\n"
            f"<<<\n{chapter_context}\n>>>\n\n"
        )

    @staticmethod
    def _prior_translations_block(prior_translations: str) -> str:
        """Format rolling prior-translation context block for continuity."""
        if not prior_translations:
            return ""
        return (
            "Below are the last translated paragraphs (for tone/terminology continuity only). "
            "Do NOT repeat or include these in your response:\n"
            f"<<<\n{prior_translations}\n>>>\n\n"
        )

    def build(self, request: TranslationRequest) -> str:
        """Build complete prompt with strict output constraints and fences."""
        return (
            "You are a professional book translator from "
            f"{request.source_lang} to {request.target_lang}.\n\n"
            "RULES:\n"
            "- Output ONLY the translated text.\n"
            "- Do NOT add any commentary, labels, quotes, or explanations.\n"
            "- Do NOT repeat the instructions or the context.\n"
            "- Preserve meaning, tone, and punctuation exactly where natural "
            "in the target language.\n"
            "- Keep sentence-ending punctuation present (., !, ?, ;, :) when the source uses it.\n"
            "- Do not drop commas or full stops; keep punctuation suitable "
            "for natural read-aloud rhythm.\n"
            "- The translated text must have roughly the same length as the original.\n\n"
            f"{self._context_block(request.chapter_context)}"
            f"{self._prior_translations_block(request.prior_translations)}"
            "Translate the following text:\n"
            f"<<<\n{request.text}\n>>>\n"
        )


@dataclass(frozen=True)
class OllamaTranslator(TranslatorPort):
    """Translator adapter that calls Ollama local HTTP API."""

    base_url: str = "http://localhost:11434"
    timeout_s: float = 120.0
    prompt_builder: PromptBuilder = PromptBuilder()

    @staticmethod
    def _generate_url(base_url: str) -> str:
        """Build Ollama generate endpoint URL."""
        return f"{base_url}/api/generate"

    @staticmethod
    def _payload(request: TranslationRequest, prompt: str) -> dict[str, object]:
        """Build Ollama request payload for translation generation."""
        return {
            "model": request.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": request.temperature},
        }

    def _post_generate(self, payload: dict[str, object]) -> requests.Response:
        """Send HTTP request to Ollama and map transport errors to retryable ones."""
        try:
            return requests.post(
                self._generate_url(self.base_url),
                json=payload,
                timeout=self.timeout_s,
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
        """Extract raw translated text field from Ollama payload."""
        raw_text = str(payload.get("response") or "").strip()
        if not raw_text:
            raise RetryableTranslationError("Empty response from Ollama")
        return raw_text

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        """Translate one request via Ollama and return sanitized translated text."""
        prompt = self.prompt_builder.build(request)

        logger.debug(
            "Calling Ollama | model=%s source=%s target=%s text_len=%s",
            request.model,
            request.source_lang,
            request.target_lang,
            len(request.text),
        )

        response = self._post_generate(self._payload(request, prompt))
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
    """Strip leaked prompt/context sections from model response text."""
    text = raw

    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    match = _LEAKED_PROMPT_RE.search(text)
    if match:
        after = text[match.end() :].strip()
        if after:
            logger.warning(
                "Stripped leaked prompt from response | stripped_chars=%d remaining_chars=%d",
                len(text) - len(after),
                len(after),
            )
            text = after

    if source_text and len(text) > _MAX_LEN_RATIO * len(source_text):
        logger.warning(
            "Translation is %.1fx the source length (%d vs %d chars) – possible context leak",
            len(text) / len(source_text),
            len(text),
            len(source_text),
        )

    return text


def _build_prompt(req: TranslationRequest) -> str:
    """Backward-compatible prompt helper preserved for existing imports/tests."""
    return PromptBuilder().build(req)
