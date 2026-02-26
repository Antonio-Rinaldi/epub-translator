from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    NodeChange,
    NodeFailure,
    NodeSkip,
    SkipReason,
    TranslationRequest,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger


logger = create_logger(__name__)

# Regex to strip ``<<<`` / ``>>>`` fence markers the model might echo.
_FENCE_RE = re.compile(r"^<<<\s*|\s*>>>$")


@dataclass(frozen=True)
class XHTMLTranslator:
    translator: TranslatorPort
    settings: TranslationSettings

    def translate_chapter(self, chapter: ChapterDocument) -> tuple[bytes, ChapterTranslationResult]:
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        root = etree.fromstring(chapter.xhtml_bytes, parser=parser)

        # Build a short context from the whole document text.
        # Keep it small (500 chars) to reduce LLM confusion/context echo.
        full_text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
        chapter_context = _limit(full_text, 500)

        changes: list[NodeChange] = []
        failures: list[NodeFailure] = []
        skips: list[NodeSkip] = []

        # Translate only paragraph-like elements.
        for elem in root.xpath("//*[local-name()='p']"):
            node_path = root.getroottree().getpath(elem)

            reason = _skip_reason(elem)
            if reason is not None:
                skips.append(NodeSkip(chapter_path=chapter.path, node_path=node_path, reason=reason))
                continue

            before = "".join(elem.itertext()).strip()
            if not before:
                skips.append(NodeSkip(chapter_path=chapter.path, node_path=node_path, reason="empty"))
                continue

            request = TranslationRequest(
                source_lang=self.settings.source_lang,
                target_lang=self.settings.target_lang,
                model=self.settings.model,
                temperature=self.settings.temperature,
                chapter_context=chapter_context,
                text=before,
            )

            translated = None
            attempts = 0
            last_error: Optional[Exception] = None

            for attempt in range(self.settings.retries + 1):
                attempts = attempt + 1
                try:
                    raw = self.translator.translate(request).translated_text
                    # Strip any ``<<<``/``>>>`` fences the model may echo.
                    translated = _FENCE_RE.sub("", raw).strip()
                    break
                except RetryableTranslationError as exc:
                    last_error = exc
                    logger.debug(
                        "Retryable translation error | chapter=%s node=%s attempt=%s/%s error=%s",
                        chapter.path,
                        node_path,
                        attempts,
                        self.settings.retries + 1,
                        str(exc),
                    )
                    time.sleep(_backoff_seconds(attempt))
                except NonRetryableTranslationError as exc:
                    last_error = exc
                    logger.debug(
                        "Non-retryable translation error | chapter=%s node=%s attempt=%s error=%s",
                        chapter.path,
                        node_path,
                        attempts,
                        str(exc),
                    )
                    break

            if translated is None:
                failures.append(
                    NodeFailure(
                        chapter_path=chapter.path,
                        node_path=node_path,
                        text=_limit(before, 200),
                        error_type=type(last_error).__name__ if last_error else "UnknownError",
                        message=str(last_error) if last_error else "unknown",
                        attempts=attempts,
                    )
                )
                continue

            # Replace text while preserving inline tags/attributes (e.g., spans with font-size styles).
            _replace_element_text(elem, translated)

            logger.debug("Translated node | chapter=%s node=%s", chapter.path, node_path)

            changes.append(
                NodeChange(
                    chapter_path=chapter.path,
                    node_path=node_path,
                    before=_limit(before, 200),
                    after=_limit(translated, 200),
                )
            )

        updated = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        return updated, ChapterTranslationResult(changes=changes, failures=failures, skips=skips)


@dataclass(frozen=True)
class ChapterTranslationResult:
    changes: list[NodeChange]
    failures: list[NodeFailure]
    skips: list[NodeSkip]


_PROTECTED_ANCESTORS = {
    "code": "protected_code",
    "pre": "protected_code",
}


def _skip_reason(elem: etree._Element) -> Optional[SkipReason]:
    # Protected: code blocks and metadata regions.
    for anc in [elem, *elem.iterancestors()]:
        tag = etree.QName(anc.tag).localname.lower() if isinstance(anc.tag, str) else ""
        if tag in _PROTECTED_ANCESTORS:
            return _PROTECTED_ANCESTORS[tag]  # type: ignore[return-value]

        # Metadata-ish regions.
        if tag in ("head", "title", "style", "script"):
            return "protected_metadata"

    # Also protect inline descendants containing code blocks or metadata.
    for descendant in elem.iterdescendants():
        d_tag = etree.QName(descendant.tag).localname.lower() if isinstance(descendant.tag, str) else ""
        if d_tag in ("code", "pre"):
            return "protected_code"

        if d_tag in ("style", "script"):
            return "protected_metadata"

    return None


_ws_re = re.compile(r"\s+")
def _limit(text: str, max_len: int) -> str:
    cleaned = _ws_re.sub(" ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _backoff_seconds(attempt: int) -> float:
    return min(4.0, 0.25 * (2**attempt))


def _replace_element_text(elem: etree._Element, translated: str) -> None:
    """Replace text content and remove all child elements.

    Child elements (spans, em, a, etc.) are removed entirely to avoid
    producing self-closing tags like ``<span class="dropcap"/>`` which
    HTML-based EPUB readers interpret as unclosed tags — causing all
    subsequent content to inherit the child's styling (e.g. large font-size).
    """
    # Remove all direct children (and their descendants).
    for child in list(elem):
        elem.remove(child)

    # Place full translated text as the element's own text.
    elem.text = translated
