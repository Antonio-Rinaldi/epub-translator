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

        raw_text = (payload.get("response") or "").strip()
        if not raw_text:
            raise RetryableTranslationError("Empty response from Ollama")

        text = _sanitise_response(raw_text, request.text)

        logger.debug("Ollama response received | raw_len=%s clean_len=%s", len(raw_text), len(text))
        return TranslationResponse(translated_text=text)


def _sanitise_response(raw: str, source_text: str) -> str:
    """Strip leaked prompt/context from the model response.

    Some models echo ``CHAPTER CONTEXT …`` or ``TEXT TO TRANSLATE``
    headers back into the response.  We detect this by:
      1. Checking for known prompt marker strings and trimming everything
         before them.
      2. If the response is still implausibly long compared to the source,
         we log a warning (but keep the text – truncating would be worse).
    """
    text = raw

    # Strip surrounding quotes the model sometimes adds.
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1].strip()

    # If the response contains a "TEXT TO TRANSLATE:" marker, keep only
    # what comes after the *last* such marker (the translated text).
    m = _LEAKED_PROMPT_RE.search(text)
    if m:
        after = text[m.end():].strip()
        if after:
            logger.warning(
                "Stripped leaked prompt from response | stripped_chars=%d remaining_chars=%d",
                len(text) - len(after),
                len(after),
            )
            text = after

    # Length-ratio sanity check.
    if source_text and len(text) > _MAX_LEN_RATIO * len(source_text):
        logger.warning(
            "Translation is %.1fx the source length (%d vs %d chars) – possible context leak",
            len(text) / len(source_text),
            len(text),
            len(source_text),
        )

    return text


def _build_prompt(req: TranslationRequest) -> str:
    """Build a translation prompt with clear delimiters.

    Uses ``<<<`` / ``>>>`` fences so the model can clearly distinguish
    context from the actual text to translate, and explicit rules to
    prevent it from echoing the context.
    """
    context_block = ""
    if req.chapter_context:
        context_block = (
            "Below is context from the chapter (for tone/terminology only). "
            "Do NOT include this context in your response:\n"
            f"<<<\n{req.chapter_context}\n>>>\n\n"
        )

    return (
        f"You are a professional book translator from {req.source_lang} to {req.target_lang}.\n\n"
        "RULES:\n"
        "- Output ONLY the translated text.\n"
        "- Do NOT add any commentary, labels, quotes, or explanations.\n"
        "- Do NOT repeat the instructions or the context.\n"
        "- Preserve meaning, tone, and punctuation.\n"
        "- The translated text must have roughly the same length as the original.\n\n"
        f"{context_block}"
        "Translate the following text:\n"
        f"<<<\n{req.text}\n>>>\n"
    )
