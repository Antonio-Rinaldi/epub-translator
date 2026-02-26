from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
from epub_translate_cli.domain.models import (
    ChapterReport,
    NodeChange,
    NodeFailure,
    NodeSkip,
    RunReport,
    TranslationRunResult,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import EpubBook, EpubRepositoryPort, ReportWriterPort, TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger


logger = create_logger(__name__)


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

        logger.info("Loaded EPUB | chapters=%s", len(book.chapters))

        xhtml_translator = XHTMLTranslator(translator=self.translator, settings=settings)

        chapter_reports: list[ChapterReport] = []
        updated_items = dict(book.items)

        for index, chapter in enumerate(book.chapters, start=1):
            logger.info("Translating chapter %s/%s | path=%s", index, len(book.chapters), chapter.path)
            changes: list[NodeChange] = []
            failures: list[NodeFailure] = []
            skips: list[NodeSkip] = []

            updated_xhtml, chapter_result = xhtml_translator.translate_chapter(chapter)

            for ch in chapter_result.changes:
                changes.append(ch)
            for fl in chapter_result.failures:
                failures.append(fl)
            for sk in chapter_result.skips:
                skips.append(sk)

            updated_items[chapter.path] = updated_xhtml

            logger.debug(
                "Chapter completed | path=%s changed=%s failed=%s skipped=%s",
                chapter.path,
                len(changes),
                len(failures),
                len(skips),
            )

            chapter_reports.append(
                ChapterReport(
                    chapter_path=chapter.path,
                    changes=changes,
                    failures=failures,
                    skips=skips,
                )
            )

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
            chapters=chapter_reports,
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


