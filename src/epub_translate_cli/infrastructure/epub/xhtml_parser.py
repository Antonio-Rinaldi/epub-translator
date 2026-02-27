from __future__ import annotations

import re
import time
from collections import deque
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

# ---------------------------------------------------------------------------
# Text-slot helpers
# ---------------------------------------------------------------------------


def _collect_text_slots(elem: etree._Element) -> list[tuple[etree._Element, str]]:
    """Return all non-empty text slots in document order as (element, attr) pairs.

    lxml stores inline text in two places per element:
    * ``elem.text``  – text **before** the first child (or sole text content)
    * ``child.tail`` – text **after** the child element but still inside ``elem``

    We only include slots that contributed characters to the source text so
    that we distribute the translation faithfully.
    """
    slots: list[tuple[etree._Element, str]] = []
    if elem.text:
        slots.append((elem, "text"))
    for child in elem:
        if child.text:
            slots.append((child, "text"))
        if child.tail:
            slots.append((child, "tail"))
    return slots


def _distribute_text(translated: str, slot_lengths: list[int]) -> list[str]:
    """Split *translated* into len(slot_lengths) chunks proportional to
    *slot_lengths*, snapping each split point to the nearest word boundary.

    If there is only one slot, the whole string is returned as-is.
    If the translated string is shorter than the number of slots, excess
    slots get empty strings.
    """
    if not slot_lengths:
        return []
    if len(slot_lengths) == 1:
        return [translated]

    total_orig = sum(slot_lengths)
    if total_orig == 0:
        # Edge case: all slots had zero length — put everything in the first.
        return [translated] + [""] * (len(slot_lengths) - 1)

    result: list[str] = []
    remaining = translated
    remaining_weight = total_orig

    for i, weight in enumerate(slot_lengths[:-1]):
        if not remaining:
            result.append("")
            continue

        # Ideal split position (proportional).
        ideal = round(len(remaining) * weight / remaining_weight)
        ideal = max(0, min(ideal, len(remaining)))

        # Snap to the nearest word boundary (prefer not to split a word).
        split_pos = _nearest_word_boundary(remaining, ideal)

        result.append(remaining[:split_pos])
        # Do NOT lstrip — leading spaces belong to the next slot.
        remaining = remaining[split_pos:]
        remaining_weight -= weight

    # Last chunk gets everything that's left.
    result.append(remaining)
    return result


def _nearest_word_boundary(text: str, pos: int) -> int:
    """Return the index of the nearest word boundary to *pos* in *text*.

    Prefers the boundary immediately after *pos*; falls back to the one
    immediately before it; falls back to *pos* itself if no whitespace found.
    """
    if pos >= len(text):
        return len(text)
    if pos == 0:
        return 0

    # Search forward for whitespace.
    fwd = pos
    while fwd < len(text) and not text[fwd].isspace():
        fwd += 1

    # Search backward for whitespace.
    bwd = pos - 1
    while bwd > 0 and not text[bwd].isspace():
        bwd -= 1

    # Choose closest; prefer forward on a tie.
    dist_fwd = fwd - pos
    dist_bwd = pos - bwd

    if dist_fwd <= dist_bwd:
        return fwd
    else:
        return bwd + 1  # +1: include the space in the previous chunk


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

        # Rolling window of the last N successfully translated paragraph texts.
        # Used as prior-context for the next paragraph request so the LLM
        # can maintain consistent tone and terminology within a chapter.
        n_ctx = self.settings.context_paragraphs
        recent_translations: deque[str] = deque(maxlen=n_ctx if n_ctx > 0 else 1)

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

            # Build prior-translation context string from the rolling window.
            prior_translations = (
                "\n".join(recent_translations) if n_ctx > 0 and recent_translations else ""
            )

            request = TranslationRequest(
                source_lang=self.settings.source_lang,
                target_lang=self.settings.target_lang,
                model=self.settings.model,
                temperature=self.settings.temperature,
                chapter_context=chapter_context,
                text=before,
                prior_translations=prior_translations,
            )

            translated: Optional[str] = None
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

            # Add this translation to the rolling context window.
            if n_ctx > 0:
                recent_translations.append(translated)

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
    """Replace paragraph text, redistributing across child text/tail slots.

    Strategy
    --------
    The source text of a paragraph is spread across multiple lxml text slots
    in document order::

        <p>
          {elem.text}
          <span>{span.text}</span>{span.tail}
          <em>{em.text}</em>{em.tail}
          …
        </p>

    We collect those source slots, compute each slot's share of the total
    character count, then split the *translated* string proportionally at
    word boundaries and write each chunk back to its original slot.

    This keeps each piece of text in its *owner* element so CSS styling
    (font-size, italic, dropcap, etc.) is applied to the right words in the
    translated output – maximally faithful to the original structure.

    Self-closing tag prevention
    ---------------------------
    Setting ``.text = ""`` (empty string, *not* ``None``) on childless
    elements forces lxml's XML serialiser to emit ``<span></span>`` instead
    of ``<span/>``.  HTML-based EPUB readers misinterpret ``<span/>`` as an
    unclosed opening tag, which causes all subsequent text to inherit the
    span's styling (e.g. a dropcap ``font-size: 1.83333em`` bleeding through
    the whole chapter).
    """
    slots = _collect_text_slots(elem)

    if not slots:
        # No text slots at all – place translated text directly.
        elem.text = translated
        return

    # Lengths of the original text in each slot.
    slot_lengths = [len(getattr(owner, attr) or "") for owner, attr in slots]

    # Distribute translated text proportionally across slots.
    chunks = _distribute_text(translated, slot_lengths)

    for (owner, attr), chunk in zip(slots, chunks):
        setattr(owner, attr, chunk)

    # Ensure every child that received no text still gets an empty string
    # (not None) so XML serialises it as <tag></tag> not <tag/>.
    for child in elem:
        if child.text is None:
            child.text = ""
        if child.tail is None:
            child.tail = ""
