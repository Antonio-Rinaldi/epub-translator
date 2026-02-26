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


@dataclass(frozen=True)
class XHTMLTranslator:
    translator: TranslatorPort
    settings: TranslationSettings

    def translate_chapter(self, chapter: ChapterDocument) -> tuple[bytes, ChapterTranslationResult]:
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        root = etree.fromstring(chapter.xhtml_bytes, parser=parser)

        # Build a coarse context from the whole document text (bounded).
        full_text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
        chapter_context = _limit(full_text, 2000)

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
                    translated = self.translator.translate(request).translated_text
                    break
                except RetryableTranslationError as exc:
                    last_error = exc
                    time.sleep(_backoff_seconds(attempt))
                except NonRetryableTranslationError as exc:
                    last_error = exc
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

            # Replace text: normalize by placing all translated text into the element and clearing children.
            # This allows minor normalization while preserving overall structure.
            _replace_element_text(elem, translated)

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
    "a": "protected_link",
    "code": "protected_code",
    "pre": "protected_code",
}


def _skip_reason(elem: etree._Element) -> Optional[SkipReason]:
    # Protected: links and code blocks.
    for anc in [elem, *elem.iterancestors()]:
        tag = etree.QName(anc.tag).localname.lower() if isinstance(anc.tag, str) else ""
        if tag in _PROTECTED_ANCESTORS:
            return _PROTECTED_ANCESTORS[tag]  # type: ignore[return-value]

        # Footnote-ish heuristics: epub:type, role, or class.
        footnote_reason = _footnote_reason(anc)
        if footnote_reason is not None:
            return footnote_reason

        # Metadata-ish regions.
        if tag in ("head", "title", "style", "script"):
            return "protected_metadata"

    # Also protect inline descendants so links/code inside <p> are never modified.
    for descendant in elem.iterdescendants():
        d_tag = etree.QName(descendant.tag).localname.lower() if isinstance(descendant.tag, str) else ""
        if d_tag == "a":
            return "protected_link"
        if d_tag in ("code", "pre"):
            return "protected_code"

        footnote_reason = _footnote_reason(descendant)
        if footnote_reason is not None:
            return footnote_reason

        if d_tag in ("style", "script"):
            return "protected_metadata"

    return None


def _footnote_reason(elem: etree._Element) -> Optional[SkipReason]:
    epub_type = (elem.get("{http://www.idpf.org/2007/ops}type") or "").lower()
    role = (elem.get("role") or "").lower()
    classes = (elem.get("class") or "").lower()
    if any(k in epub_type for k in ("noteref", "footnote", "endnote")):
        return "protected_footnote"
    if any(k in role for k in ("doc-noteref", "doc-footnote", "doc-endnote")):
        return "protected_footnote"
    if any(k in classes for k in ("footnote", "endnote", "noteref")):
        return "protected_footnote"
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
    # Preserve tag/attributes but allow normalization by flattening children.
    for child in list(elem):
        elem.remove(child)
    elem.text = translated
