from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from typing import cast

from lxml import etree

from epub_translate_cli.domain.errors import (
    NonRetryableTranslationError,
    RetryableTranslationError,
)
from epub_translate_cli.domain.models import (
    DEFAULT_TRANSLATABLE_TAGS,
    ChapterDocument,
    NodeChange,
    NodeFailure,
    NodeSkip,
    SkipReason,
    TranslatableNode,
    TranslatableTag,
    TranslationRequest,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

# Regex to strip ``<<<`` / ``>>>`` fence markers the model might echo.
_FENCE_RE = re.compile(r"^<<<\s*|\s*>>>$")

# Common HTML named entities often found in EPUB XHTML that are not predefined
# XML entities. Convert them to numeric character references before XML parse.
_HTML_ENTITY_TO_NUMERIC: dict[bytes, bytes] = {
    b"&nbsp;": b"&#160;",
    b"&ndash;": b"&#8211;",
    b"&mdash;": b"&#8212;",
    b"&lsquo;": b"&#8216;",
    b"&rsquo;": b"&#8217;",
    b"&ldquo;": b"&#8220;",
    b"&rdquo;": b"&#8221;",
    b"&hellip;": b"&#8230;",
}

# Node types whose .text attribute is read-only (they are _Element subclasses
# in lxml but only hold content, not writable text slots).
_CONTENT_ONLY_TYPES = (etree._Entity, etree._Comment, etree._ProcessingInstruction)
_TRANSLATABLE_TAG_SET = frozenset(DEFAULT_TRANSLATABLE_TAGS)


@dataclass(frozen=True)
class ChapterTranslationResult:
    """Per-chapter translation processing report."""

    changes: list[NodeChange]
    failures: list[NodeFailure]
    skips: list[NodeSkip]


def _normalize_non_xml_entities(xhtml_bytes: bytes) -> bytes:
    """Replace non-XML named entities with numeric references before parsing."""
    normalized = xhtml_bytes
    for src, dst in _HTML_ENTITY_TO_NUMERIC.items():
        normalized = normalized.replace(src, dst)
    return normalized


def _translatable_xpath(tags: tuple[TranslatableTag, ...]) -> str:
    """Build local-name XPath predicate for the configured translatable tags."""
    predicates = " or ".join(f"local-name()='{tag}'" for tag in tags)
    return f"//*[{predicates}]"


def _is_writable_element(node: etree._Element) -> bool:
    """Return True only for regular element nodes with writable .text/.tail."""
    return not isinstance(node, _CONTENT_ONLY_TYPES)


def _collect_text_slots(elem: etree._Element) -> list[tuple[etree._Element, str]]:
    """Return all non-empty text slots in document order as (element, attr) pairs."""
    slots: list[tuple[etree._Element, str]] = []
    if elem.text:
        slots.append((elem, "text"))
    for child in elem:
        if not _is_writable_element(child):
            continue
        if child.text:
            slots.append((child, "text"))
        if child.tail:
            slots.append((child, "tail"))
    return slots


def _distribute_text(translated: str, slot_lengths: list[int]) -> list[str]:
    """Split translated text proportionally across source text slots."""
    if not slot_lengths:
        return []
    if len(slot_lengths) == 1:
        return [translated]

    total_orig = sum(slot_lengths)
    if total_orig == 0:
        return [translated] + [""] * (len(slot_lengths) - 1)

    result: list[str] = []
    remaining = translated
    remaining_weight = total_orig

    for weight in slot_lengths[:-1]:
        if not remaining:
            result.append("")
            continue

        ideal = round(len(remaining) * weight / remaining_weight)
        ideal = max(0, min(ideal, len(remaining)))
        split_pos = _nearest_word_boundary(remaining, ideal)

        result.append(remaining[:split_pos])
        remaining = remaining[split_pos:]
        remaining_weight -= weight

    result.append(remaining)
    return result


def _nearest_word_boundary(text: str, pos: int) -> int:
    """Return the nearest split position around ``pos`` that avoids breaking words."""
    if pos >= len(text):
        return len(text)
    if pos == 0:
        return 0

    forward = pos
    while forward < len(text) and not text[forward].isspace():
        forward += 1

    backward = pos - 1
    while backward > 0 and not text[backward].isspace():
        backward -= 1

    return forward if (forward - pos) <= (pos - backward) else backward + 1


@dataclass(frozen=True)
class XHTMLTranslator:
    """Translate chapter XHTML while preserving inline formatting structure."""

    translator: TranslatorPort
    settings: TranslationSettings
    translatable_tags: tuple[TranslatableTag, ...] = DEFAULT_TRANSLATABLE_TAGS

    def translate_chapter(self, chapter: ChapterDocument) -> tuple[bytes, ChapterTranslationResult]:
        """Translate one chapter and return updated XHTML bytes plus chapter report."""
        root = self._parse_root(chapter.xhtml_bytes)
        chapter_context = self._chapter_context(root)
        report = self._translate_nodes(root, chapter.path, chapter_context)
        updated = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        return updated, report

    @staticmethod
    def _parse_root(xhtml_bytes: bytes) -> etree._Element:
        """Parse XHTML bytes into an lxml root with robust entity handling."""
        parser = etree.XMLParser(recover=True, resolve_entities=True)
        normalized_xhtml = _normalize_non_xml_entities(xhtml_bytes)
        return etree.fromstring(normalized_xhtml, parser=parser)

    @staticmethod
    def _chapter_context(root: etree._Element) -> str:
        """Build short chapter context used only for translation guidance."""
        full_text = " ".join(str(text).strip() for text in root.itertext() if str(text).strip())
        return _limit(full_text, 500)

    def _translate_nodes(
        self,
        root: etree._Element,
        chapter_path: str,
        chapter_context: str,
    ) -> ChapterTranslationResult:
        """Translate all eligible nodes and build chapter report sections."""
        changes: list[NodeChange] = []
        failures: list[NodeFailure] = []
        skips: list[NodeSkip] = []

        context_size = self.settings.context_paragraphs
        recent_translations: deque[str] = deque(maxlen=context_size if context_size > 0 else 1)

        for elem, node in self._candidate_nodes(root, chapter_path):
            reason = _skip_reason(elem)
            if reason is not None:
                skips.append(self._skip_entry(node, reason))
                continue
            if not node.source_text:
                skips.append(self._skip_entry(node, "empty"))
                continue

            translated, attempts, error = self._translate_node(
                elem=elem,
                node=node,
                chapter_context=chapter_context,
                prior_translations=self._prior_translations(recent_translations, context_size),
            )

            if translated is None:
                failures.append(self._failure_entry(node, error, attempts))
                continue

            changes.append(self._change_entry(node, translated))
            logger.debug(
                "Translated node | chapter=%s node=%s tag=%s",
                chapter_path,
                node.node_path,
                node.tag,
            )
            if context_size > 0:
                recent_translations.append(translated)

        return ChapterTranslationResult(changes=changes, failures=failures, skips=skips)

    def _candidate_nodes(
        self,
        root: etree._Element,
        chapter_path: str,
    ) -> list[tuple[etree._Element, TranslatableNode]]:
        """Collect translatable node candidates in document order."""
        xpath = _translatable_xpath(self.translatable_tags)
        raw_nodes = root.xpath(xpath)
        if not isinstance(raw_nodes, list):
            return []

        def _to_node(elem: etree._Element) -> tuple[etree._Element, TranslatableNode] | None:
            """Convert one lxml element into typed translatable node payload when eligible."""
            if not isinstance(elem.tag, str):
                return None
            local_tag = etree.QName(elem.tag).localname.lower()
            if local_tag not in _TRANSLATABLE_TAG_SET:
                return None
            node = TranslatableNode(
                chapter_path=chapter_path,
                node_path=root.getroottree().getpath(elem),
                tag=cast(TranslatableTag, local_tag),
                source_text="".join(str(text) for text in elem.itertext()).strip(),
            )
            return elem, node

        return [
            item
            for item in (_to_node(elem) for elem in raw_nodes if isinstance(elem, etree._Element))
            if item is not None
        ]

    @staticmethod
    def _prior_translations(window: deque[str], context_size: int) -> str:
        """Build prior translation context block from rolling window."""
        if context_size <= 0 or not window:
            return ""
        return "\n".join(window)

    def _translation_request(
        self,
        chapter_context: str,
        source_text: str,
        prior_translations: str,
    ) -> TranslationRequest:
        """Create translation request payload for one source node text."""
        return TranslationRequest(
            source_lang=self.settings.source_lang,
            target_lang=self.settings.target_lang,
            model=self.settings.model,
            temperature=self.settings.temperature,
            chapter_context=chapter_context,
            text=source_text,
            prior_translations=prior_translations,
        )

    def _translate_node(
        self,
        *,
        elem: etree._Element,
        node: TranslatableNode,
        chapter_context: str,
        prior_translations: str,
    ) -> tuple[str | None, int, Exception | None]:
        """Translate one node and apply translated text in place when successful."""
        request = self._translation_request(chapter_context, node.source_text, prior_translations)
        translated, attempts, error = self._translate_with_retries(
            request,
            node.chapter_path,
            node.node_path,
        )
        if translated is not None:
            _replace_element_text(elem, translated)
        return translated, attempts, error

    def _translate_with_retries(
        self,
        request: TranslationRequest,
        chapter_path: str,
        node_path: str,
    ) -> tuple[str | None, int, Exception | None]:
        """Translate request with retry policy and return translated text or failure metadata."""
        attempts = 0
        last_error: Exception | None = None

        for attempt in range(self.settings.retries + 1):
            attempts = attempt + 1
            try:
                raw = self.translator.translate(request).translated_text
                return _FENCE_RE.sub("", raw).strip(), attempts, None
            except RetryableTranslationError as exc:
                last_error = exc
                logger.debug(
                    "Retryable translation error | chapter=%s node=%s attempt=%s/%s error=%s",
                    chapter_path,
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
                    chapter_path,
                    node_path,
                    attempts,
                    str(exc),
                )
                break

        return None, attempts, last_error

    @staticmethod
    def _skip_entry(node: TranslatableNode, reason: SkipReason) -> NodeSkip:
        """Build skip report entry for one node."""
        return NodeSkip(chapter_path=node.chapter_path, node_path=node.node_path, reason=reason)

    @staticmethod
    def _change_entry(node: TranslatableNode, translated_text: str) -> NodeChange:
        """Build change report entry for one successful node translation."""
        return NodeChange(
            chapter_path=node.chapter_path,
            node_path=node.node_path,
            before=_limit(node.source_text, 200),
            after=_limit(translated_text, 200),
        )

    @staticmethod
    def _failure_entry(
        node: TranslatableNode,
        error: Exception | None,
        attempts: int,
    ) -> NodeFailure:
        """Build failure report entry for one unsuccessful node translation."""
        return NodeFailure(
            chapter_path=node.chapter_path,
            node_path=node.node_path,
            text=_limit(node.source_text, 200),
            error_type=type(error).__name__ if error else "UnknownError",
            message=str(error) if error else "unknown",
            attempts=attempts,
        )


_PROTECTED_ANCESTORS: dict[str, SkipReason] = {
    "code": "protected_code",
    "pre": "protected_code",
}


def _skip_reason(elem: etree._Element) -> SkipReason | None:
    """Return skip reason for protected elements, metadata areas, or embedded code."""
    for anc in [elem, *elem.iterancestors()]:
        tag = etree.QName(anc.tag).localname.lower() if isinstance(anc.tag, str) else ""
        if tag in _PROTECTED_ANCESTORS:
            return _PROTECTED_ANCESTORS[tag]
        if tag in ("head", "title", "style", "script"):
            return "protected_metadata"

    for descendant in elem.iterdescendants():
        d_tag = (
            etree.QName(descendant.tag).localname.lower() if isinstance(descendant.tag, str) else ""
        )
        if d_tag in ("code", "pre"):
            return "protected_code"
        if d_tag in ("style", "script"):
            return "protected_metadata"

    return None


_ws_re = re.compile(r"\s+")


def _limit(text: str, max_len: int) -> str:
    """Normalize whitespace and truncate text for compact reporting fields."""
    cleaned = _ws_re.sub(" ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _backoff_seconds(attempt: int) -> float:
    """Compute exponential retry backoff capped at four seconds."""
    delay = 0.25 * (2**attempt)
    return 4.0 if delay > 4.0 else delay


def _replace_element_text(elem: etree._Element, translated: str) -> None:
    """Replace node text while preserving inline markup ownership of text slots."""
    slots = _collect_text_slots(elem)

    if not slots:
        elem.text = translated
        return

    slot_lengths = [len(getattr(owner, attr) or "") for owner, attr in slots]
    chunks = _distribute_text(translated, slot_lengths)

    for (owner, attr), chunk in zip(slots, chunks):
        setattr(owner, attr, chunk)

    for child in elem:
        if not _is_writable_element(child):
            continue
        if child.text is None:
            child.text = ""
        if child.tail is None:
            child.tail = ""
