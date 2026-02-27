from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    ChapterReport,
    RunReport,
    TranslationRunResult,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import EpubBook, EpubRepositoryPort, ReportWriterPort, TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator, ChapterTranslationResult
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger


logger = create_logger(__name__)


class _ChapterWork(NamedTuple):
    index: int
    total: int
    chapter: ChapterDocument


@dataclass(frozen=True)
class TranslationOrchestrator:
    epub_repository: EpubRepositoryPort
    translator: TranslatorPort
    report_writer: ReportWriterPort

    def translate_epub(
        self,
        input_path: Path,
        output_path: Path,
        report_path: Path,
        settings: TranslationSettings,
    ) -> TranslationRunResult:
        logger.info("Loading EPUB | path=%s", input_path)
        try:
            book = self.epub_repository.load(input_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubReadError(str(exc)) from exc

        logger.info("Loaded EPUB | chapters=%s workers=%s", len(book.chapters), settings.workers)

        xhtml_translator = XHTMLTranslator(translator=self.translator, settings=settings)
        total = len(book.chapters)

        # Pre-populate updated_items with the originals so ordering is stable.
        updated_items = dict(book.items)
        chapter_reports: list[ChapterReport | None] = [None] * total

        def _translate_one(work: _ChapterWork) -> tuple[int, bytes, ChapterTranslationResult]:
            logger.info(
                "Translating chapter %s/%s | path=%s", work.index, work.total, work.chapter.path
            )
            xhtml, result = xhtml_translator.translate_chapter(work.chapter)
            logger.debug(
                "Chapter completed | path=%s changed=%s failed=%s skipped=%s",
                work.chapter.path,
                len(result.changes),
                len(result.failures),
                len(result.skips),
            )
            return work.index - 1, xhtml, result

        works = [
            _ChapterWork(index=i, total=total, chapter=ch)
            for i, ch in enumerate(book.chapters, start=1)
        ]

        # Chapters are translated in parallel (one thread per chapter).
        # Within each chapter, paragraphs are translated sequentially so that
        # a rolling context window (last N translated paragraphs) can be passed
        # to each successive paragraph request for consistent tone/terminology.
        with ThreadPoolExecutor(max_workers=settings.workers) as pool:
            futures = {pool.submit(_translate_one, w): w for w in works}
            for future in as_completed(futures):
                idx, updated_xhtml, chapter_result = future.result()
                chapter = book.chapters[idx]
                updated_items[chapter.path] = updated_xhtml
                chapter_reports[idx] = ChapterReport(
                    chapter_path=chapter.path,
                    changes=list(chapter_result.changes),
                    failures=list(chapter_result.failures),
                    skips=list(chapter_result.skips),
                )

        # chapter_reports is pre-allocated as [None] * total and filled by workers;
        # all slots are guaranteed to be filled by the time the pool exits.
        filled_reports: list[ChapterReport] = [r for r in chapter_reports if r is not None]

        report = RunReport(
            input_path=str(input_path),
            output_path=str(output_path),
            report_path=str(report_path),
            model=settings.model,
            source_lang=settings.source_lang,
            target_lang=settings.target_lang,
            temperature=settings.temperature,
            retries=settings.retries,
            abort_on_error=settings.abort_on_error,
            output_written=False,
            chapters=filled_reports,
        )

        failures_count = report.totals()["failed"]

        output_written = True
        exit_code = 0

        if settings.abort_on_error and failures_count > 0:
            output_written = False
            exit_code = 2
            logger.info("Aborting EPUB write due to failures | failures=%s", failures_count)
        else:
            logger.info("Writing translated EPUB | path=%s", output_path)
            try:
                self.epub_repository.save(
                    EpubBook(items=updated_items, chapters=book.chapters),
                    output_path,
                )
            except Exception as exc:  # noqa: BLE001
                raise EpubWriteError(str(exc)) from exc

        report.output_written = output_written
        self.report_writer.write(report, report_path)
        logger.info(
            "Run completed | changed=%s failed=%s skipped=%s output_written=%s",
            report.totals()["changed"],
            report.totals()["failed"],
            report.totals()["skipped"],
            output_written,
        )

        return TranslationRunResult(
            output_written=output_written,
            failures=failures_count,
            exit_code=exit_code,
        )
