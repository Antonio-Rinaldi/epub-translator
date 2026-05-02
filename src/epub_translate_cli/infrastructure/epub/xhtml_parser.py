from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import cast

from lxml import etree

from epub_translate_cli.domain.models import (
    DEFAULT_TRANSLATABLE_TAGS,
    ChapterDocument,
    SkipReason,
    TranslatableNode,
    TranslatableTag,
)
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

# Named constants.
CHAPTER_CONTEXT_MAX_CHARS: int = 1500
REPORT_FIELD_MAX_CHARS: int = 200
BACKOFF_CAP_SECONDS: float = 4.0
BACKOFF_BASE: float = 0.25

# Regex to strip ``<<<`` / ``>>>`` fence markers the model might echo.
_FENCE_RE = re.compile(r"^<<<\s*|\s*>>>$")

# Common HTML named entities often found in EPUB XHTML that are not predefined XML entities.
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

_CONTENT_ONLY_TYPES = (etree._Entity, etree._Comment, etree._ProcessingInstruction)
_TRANSLATABLE_TAG_SET = frozenset(DEFAULT_TRANSLATABLE_TAGS)

_PROTECTED_ANCESTORS: dict[str, SkipReason] = {
    "code": "protected_code",
    "pre": "protected_code",
}

_ws_re = re.compile(r"\s+")


def _normalize_non_xml_entities(xhtml_bytes: bytes) -> bytes:
    normalized = xhtml_bytes
    for src, dst in _HTML_ENTITY_TO_NUMERIC.items():
        normalized = normalized.replace(src, dst)
    return normalized


def _translatable_xpath(tags: tuple[TranslatableTag, ...]) -> str:
    predicates = " or ".join(f"local-name()='{tag}'" for tag in tags)
    return f"//*[{predicates}]"


def _is_writable_element(node: etree._Element) -> bool:
    return not isinstance(node, _CONTENT_ONLY_TYPES)


def collect_text_slots(elem: etree._Element) -> list[tuple[etree._Element, str]]:
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


def distribute_text(translated: str, slot_lengths: list[int]) -> list[str]:
    """Split translated text across source text slots.

    When the first slot has length 1 (dropcap), assigns exactly the first
    grapheme cluster to it and distributes the remainder proportionally.
    """
    if not slot_lengths:
        return []
    if len(slot_lengths) == 1:
        return [translated]

    if slot_lengths[0] == 1 and translated:
        rest = distribute_text(translated[1:], slot_lengths[1:])
        return [translated[:1]] + rest

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
        split_pos = nearest_word_boundary(remaining, ideal)
        result.append(remaining[:split_pos])
        remaining = remaining[split_pos:]
        remaining_weight -= weight

    result.append(remaining)
    return result


def nearest_word_boundary(text: str, pos: int) -> int:
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


def skip_reason(elem: etree._Element) -> SkipReason | None:
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


# Keep the private alias so existing imports continue to work during migration.
_skip_reason = skip_reason


def _limit(text: str, max_len: int) -> str:
    """Normalize whitespace and truncate text for compact reporting fields."""
    cleaned = _ws_re.sub(" ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def _backoff_seconds(attempt: int) -> float:
    """Compute exponential retry backoff capped at BACKOFF_CAP_SECONDS."""
    delay = BACKOFF_BASE * (2**attempt)
    return BACKOFF_CAP_SECONDS if delay > BACKOFF_CAP_SECONDS else delay


def _format_prior_pairs(window: deque[tuple[str, str]], context_size: int) -> str:
    """Format rolling source→target pairs for prior-translations context block."""
    if context_size <= 0 or not window:
        return ""
    return "\n\n".join(f"Original: {src}\nTranslation: {tgt}" for src, tgt in window)


@dataclass(frozen=True)
class XHTMLTranslator:
    """Parse and serialize EPUB chapter XHTML.

    Responsible only for XHTML I/O: parsing, candidate node collection,
    text replacement, and serialization. The translation loop lives in
    ChapterTranslator (application layer).
    """

    translatable_tags: tuple[TranslatableTag, ...] = DEFAULT_TRANSLATABLE_TAGS

    def parse_chapter(
        self, chapter: ChapterDocument
    ) -> tuple[etree._Element, list[tuple[etree._Element, TranslatableNode]]]:
        """Parse chapter XHTML and collect translatable node candidates."""
        root = self._parse_root(chapter.xhtml_bytes)
        nodes = self._candidate_nodes(root, chapter.path)
        return root, nodes

    @staticmethod
    def serialize_chapter(root: etree._Element) -> bytes:
        """Serialize lxml element tree back to XHTML bytes."""
        result: bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True)
        return result

    @staticmethod
    def chapter_context(root: etree._Element) -> str:
        """Build representative chapter context from start, middle, and end paragraphs."""
        raw = root.xpath("//*[local-name()='p']")
        para_elems = (
            [e for e in raw if isinstance(e, etree._Element)] if isinstance(raw, list) else []
        )
        para_texts = ["".join(str(t) for t in e.itertext()).strip() for e in para_elems]
        para_texts = [t for t in para_texts if t]

        if not para_texts:
            return ""
        if len(para_texts) == 1:
            return _limit(para_texts[0], CHAPTER_CONTEXT_MAX_CHARS)

        n = len(para_texts)
        if n == 2:
            samples = [para_texts[0], "[...]", para_texts[-1]]
        else:
            samples = [para_texts[0], "[...]", para_texts[n // 2], "[...]", para_texts[-1]]

        return _limit(" ".join(samples), CHAPTER_CONTEXT_MAX_CHARS)

    @staticmethod
    def replace_node_text(elem: etree._Element, translated: str) -> None:
        """Replace node text in-place while preserving inline markup structure."""
        _replace_element_text(elem, translated)

    @staticmethod
    def _parse_root(xhtml_bytes: bytes) -> etree._Element:
        parser = etree.XMLParser(recover=True, resolve_entities=True)
        normalized_xhtml = _normalize_non_xml_entities(xhtml_bytes)
        return etree.fromstring(normalized_xhtml, parser=parser)

    def _candidate_nodes(
        self,
        root: etree._Element,
        chapter_path: str,
    ) -> list[tuple[etree._Element, TranslatableNode]]:
        xpath = _translatable_xpath(self.translatable_tags)
        raw_nodes = root.xpath(xpath)
        if not isinstance(raw_nodes, list):
            return []

        def _to_node(elem: etree._Element) -> tuple[etree._Element, TranslatableNode] | None:
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


def _replace_element_text(elem: etree._Element, translated: str) -> None:
    """Replace node text while preserving inline markup ownership of text slots."""
    slots = collect_text_slots(elem)

    if not slots:
        elem.text = translated
        return

    slot_lengths = [len(getattr(owner, attr) or "") for owner, attr in slots]
    chunks = distribute_text(translated, slot_lengths)

    for (owner, attr), chunk in zip(slots, chunks):
        setattr(owner, attr, chunk)

    for child in elem:
        if not _is_writable_element(child):
            continue
        if child.text is None:
            child.text = ""
        if child.tail is None:
            child.tail = ""
