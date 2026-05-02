from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from lxml import etree

from epub_translate_cli.domain.errors import NonRetryableTranslationError, RetryableTranslationError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    ChapterTranslationResult,
    NodeChange,
    NodeFailure,
    NodeSkip,
    TranslatableNode,
    TranslationRequest,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import (
    REPORT_FIELD_MAX_CHARS,
    XHTMLTranslator,
    _backoff_seconds,
    _format_prior_pairs,
    _limit,
    skip_reason,
)
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

_FENCE_RE = re.compile(r"^<<<\s*|\s*>>>$")

_NodePair = tuple[etree._Element, TranslatableNode]


@dataclass(frozen=True)
class ChapterTranslator:
    """Application service that drives the per-node translation loop for one EPUB chapter.

    Implements ChapterProcessorPort. Delegates all XHTML I/O to XHTMLTranslator
    and all LLM calls to a TranslatorPort adapter.
    """

    translator: TranslatorPort
    settings: TranslationSettings
    xhtml_parser: XHTMLTranslator
    glossary_terms: dict[str, str] = field(default_factory=dict)

    def translate_chapter(
        self,
        chapter: ChapterDocument,
        on_progress: Callable[[bytes], None] | None = None,
    ) -> tuple[bytes, ChapterTranslationResult]:
        """Translate one chapter and return updated XHTML bytes plus chapter result.

        `on_progress` is called after every successfully translated paragraph with
        the current serialised XHTML bytes so callers can write intermediate progress
        to disk without waiting for the whole chapter to finish.
        """
        root, nodes = self.xhtml_parser.parse_chapter(chapter)
        chapter_ctx = self.xhtml_parser.chapter_context(root)
        result = self._translate_nodes(
            chapter.path,
            chapter_ctx,
            nodes,
            root=root,
            on_progress=on_progress,
        )
        updated = self.xhtml_parser.serialize_chapter(root)
        return updated, result

    def _translate_nodes(
        self,
        chapter_path: str,
        chapter_context: str,
        nodes: list[_NodePair],
        root: etree._Element,
        on_progress: Callable[[bytes], None] | None = None,
    ) -> ChapterTranslationResult:
        changes: list[NodeChange] = []
        failures: list[NodeFailure] = []
        skips: list[NodeSkip] = []

        context_size = self.settings.context_paragraphs
        recent_pairs: deque[tuple[str, str]] = deque(maxlen=context_size if context_size > 0 else 1)

        for elem, node in nodes:
            reason = skip_reason(elem)
            if reason is not None:
                skips.append(
                    NodeSkip(
                        chapter_path=node.chapter_path,
                        node_path=node.node_path,
                        reason=reason,
                    )
                )
                continue
            if not node.source_text:
                skips.append(
                    NodeSkip(
                        chapter_path=node.chapter_path,
                        node_path=node.node_path,
                        reason="empty",
                    )
                )
                continue

            translated, attempts, error = self._translate_with_retries(
                elem=elem,
                node=node,
                chapter_context=chapter_context,
                prior_translations=_format_prior_pairs(recent_pairs, context_size),
            )

            if translated is None:
                failures.append(
                    NodeFailure(
                        chapter_path=node.chapter_path,
                        node_path=node.node_path,
                        text=_limit(node.source_text, REPORT_FIELD_MAX_CHARS),
                        error_type=type(error).__name__ if error else "UnknownError",
                        message=str(error) if error else "unknown",
                        attempts=attempts,
                    )
                )
                continue

            self.xhtml_parser.replace_node_text(elem, translated)
            changes.append(
                NodeChange(
                    chapter_path=node.chapter_path,
                    node_path=node.node_path,
                    before=_limit(node.source_text, REPORT_FIELD_MAX_CHARS),
                    after=_limit(translated, REPORT_FIELD_MAX_CHARS),
                )
            )
            logger.debug(
                "Translated node | chapter=%s node=%s",
                chapter_path,
                node.node_path,
            )
            if context_size > 0:
                recent_pairs.append((node.source_text, translated))

            # Write current XHTML state to disk after every successful paragraph
            # so the staging file reflects live progress.
            if on_progress is not None:
                on_progress(self.xhtml_parser.serialize_chapter(root))

        return ChapterTranslationResult(changes=changes, failures=failures, skips=skips)

    def _translate_with_retries(
        self,
        *,
        elem: etree._Element,
        node: TranslatableNode,
        chapter_context: str,
        prior_translations: str,
    ) -> tuple[str | None, int, Exception | None]:
        request = TranslationRequest(
            chapter_context=chapter_context,
            text=node.source_text,
            prior_translations=prior_translations,
            glossary_terms=self.glossary_terms,
        )

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
                    "Retryable error | node=%s attempt=%s/%s error=%s",
                    node.node_path,
                    attempts,
                    self.settings.retries + 1,
                    str(exc),
                )
                time.sleep(_backoff_seconds(attempt))
            except NonRetryableTranslationError as exc:
                last_error = exc
                logger.debug(
                    "Non-retryable error | node=%s attempt=%s error=%s",
                    node.node_path,
                    attempts,
                    str(exc),
                )
                break

        return None, attempts, last_error
