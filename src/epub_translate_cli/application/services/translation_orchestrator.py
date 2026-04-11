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
from epub_translate_cli.domain.ports import (
    EpubBook,
    EpubRepositoryPort,
    ReportWriterPort,
    TranslatorPort,
)
from epub_translate_cli.infrastructure.epub.xhtml_parser import (
    ChapterTranslationResult,
    XHTMLTranslator,
)
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
    StagedChapter,
)

logger = create_logger(__name__)


class _ChapterWork(NamedTuple):
    """Immutable chapter work unit for parallel translation execution."""

    chapter_index: int
    total: int
    chapter: ChapterDocument


@dataclass(frozen=True)
class TranslationOrchestrator:
    """Application facade orchestrating EPUB translation runs."""

    epub_repository: EpubRepositoryPort
    translator: TranslatorPort
    report_writer: ReportWriterPort

    def translate_epub(
        self,
        input_path: Path,
        output_path: Path,
        report_path: Path,
        settings: TranslationSettings,
        reset_resume_state: bool = False,
    ) -> TranslationRunResult:
        """Translate an EPUB and produce translated output and report artifacts."""
        book = self._load_book(input_path)
        stage_store = FilesystemChapterStageStore.for_run(
            input_path=input_path,
            output_path=output_path,
            report_path=report_path,
            settings=settings,
        )
        if reset_resume_state:
            logger.info("Resetting staged resume workspace before translation")
            stage_store.clear()
        resumed = stage_store.load_completed()
        logger.info("Loaded EPUB | chapters=%s workers=%s", len(book.chapters), settings.workers)
        if resumed:
            logger.info(
                "Resuming run from staged chapters | completed=%s",
                len(resumed),
            )

        xhtml_translator = XHTMLTranslator(translator=self.translator, settings=settings)
        chapter_overrides, chapter_reports = self._translate_chapters(
            book,
            xhtml_translator,
            settings.workers,
            stage_store,
            resumed,
        )
        updated_items = self._merged_items(book.items, chapter_overrides)

        report = self._build_run_report(
            input_path=input_path,
            output_path=output_path,
            report_path=report_path,
            settings=settings,
            chapter_reports=chapter_reports,
            output_written=False,
        )

        output_written, exit_code = self._write_output_if_allowed(
            report=report,
            updated_items=updated_items,
            chapters=book.chapters,
            output_path=output_path,
            abort_on_error=settings.abort_on_error,
        )

        report.output_written = output_written
        self.report_writer.write(report, report_path)
        if output_written:
            stage_store.clear()
        totals = report.totals()
        logger.info(
            "Run completed | changed=%s failed=%s skipped=%s output_written=%s",
            totals["changed"],
            totals["failed"],
            totals["skipped"],
            output_written,
        )

        return TranslationRunResult(
            output_written=output_written,
            failures=totals["failed"],
            exit_code=exit_code,
        )

    def _load_book(self, input_path: Path) -> EpubBook:
        """Load input EPUB via repository adapter and normalize read errors."""
        logger.info("Loading EPUB | path=%s", input_path)
        try:
            return self.epub_repository.load(input_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubReadError(str(exc)) from exc

    @staticmethod
    def _chapter_works(chapters: list[ChapterDocument]) -> list[_ChapterWork]:
        """Build ordered chapter work units for thread pool scheduling."""
        total = len(chapters)
        return [
            _ChapterWork(chapter_index=i, total=total, chapter=chapter)
            for i, chapter in enumerate(chapters, start=1)
        ]

    @staticmethod
    def _chapter_report(
        chapter_path: str,
        chapter_result: ChapterTranslationResult,
    ) -> ChapterReport:
        """Convert parser chapter result into report section object."""
        return ChapterReport(
            chapter_path=chapter_path,
            changes=list(chapter_result.changes),
            failures=list(chapter_result.failures),
            skips=list(chapter_result.skips),
        )

    @staticmethod
    def _ordered_reports(chapter_reports: list[ChapterReport | None]) -> list[ChapterReport]:
        """Return ordered chapter reports after validating all entries are populated."""
        if any(report is None for report in chapter_reports):
            missing = sum(1 for report in chapter_reports if report is None)
            raise RuntimeError(f"Missing chapter reports for {missing} chapters")
        return [report for report in chapter_reports if report is not None]

    @staticmethod
    def _merged_items(
        base_items: dict[str, bytes], overrides: dict[str, bytes]
    ) -> dict[str, bytes]:
        """Merge chapter overrides into original EPUB item payload map."""
        return {**base_items, **overrides}

    def _translate_chapters(
        self,
        book: EpubBook,
        xhtml_translator: XHTMLTranslator,
        workers: int,
        stage_store: FilesystemChapterStageStore,
        resumed: dict[int, StagedChapter],
    ) -> tuple[dict[str, bytes], list[ChapterReport]]:
        """Translate pending chapters and merge them with resumed staged chapter snapshots."""
        works = self._chapter_works(book.chapters)
        resumed_indexes = set(resumed)
        pending_works = [work for work in works if (work.chapter_index - 1) not in resumed_indexes]
        updated_items = {staged.chapter_path: staged.xhtml_bytes for staged in resumed.values()}
        chapter_reports: list[ChapterReport | None] = [None] * len(book.chapters)
        for staged in resumed.values():
            chapter_reports[staged.chapter_index] = staged.report

        if not pending_works:
            return updated_items, self._ordered_reports(chapter_reports)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._translate_one_chapter, xhtml_translator, work): work
                for work in pending_works
            }
            for future in as_completed(futures):
                index, updated_xhtml, result = future.result()
                chapter = book.chapters[index]
                updated_items[chapter.path] = updated_xhtml
                chapter_report = self._chapter_report(chapter.path, result)
                chapter_reports[index] = chapter_report
                stage_store.save_chapter(
                    chapter_index=index,
                    chapter_path=chapter.path,
                    xhtml_bytes=updated_xhtml,
                    report=chapter_report,
                )

        return updated_items, self._ordered_reports(chapter_reports)

    @staticmethod
    def _translate_one_chapter(
        xhtml_translator: XHTMLTranslator,
        work: _ChapterWork,
    ) -> tuple[int, bytes, ChapterTranslationResult]:
        """Translate one chapter and return zero-based index, bytes, and report."""
        logger.info(
            "Translating chapter %s/%s | path=%s",
            work.chapter_index,
            work.total,
            work.chapter.path,
        )
        updated_xhtml, result = xhtml_translator.translate_chapter(work.chapter)
        logger.debug(
            "Chapter completed | path=%s changed=%s failed=%s skipped=%s",
            work.chapter.path,
            len(result.changes),
            len(result.failures),
            len(result.skips),
        )
        return work.chapter_index - 1, updated_xhtml, result

    @staticmethod
    def _build_run_report(
        *,
        input_path: Path,
        output_path: Path,
        report_path: Path,
        settings: TranslationSettings,
        chapter_reports: list[ChapterReport],
        output_written: bool,
    ) -> RunReport:
        """Assemble final run report data object."""
        return RunReport(
            input_path=str(input_path),
            output_path=str(output_path),
            report_path=str(report_path),
            model=settings.model,
            source_lang=settings.source_lang,
            target_lang=settings.target_lang,
            temperature=settings.temperature,
            retries=settings.retries,
            abort_on_error=settings.abort_on_error,
            output_written=output_written,
            chapters=chapter_reports,
        )

    def _write_output_if_allowed(
        self,
        *,
        report: RunReport,
        updated_items: dict[str, bytes],
        chapters: list[ChapterDocument],
        output_path: Path,
        abort_on_error: bool,
    ) -> tuple[bool, int]:
        """Write translated EPUB unless abort-on-error policy blocks output creation."""
        failures_count = report.totals()["failed"]
        if abort_on_error and failures_count > 0:
            logger.info("Aborting EPUB write due to failures | failures=%s", failures_count)
            return False, 2

        logger.info("Writing translated EPUB | path=%s", output_path)
        try:
            self.epub_repository.save(EpubBook(items=updated_items, chapters=chapters), output_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubWriteError(str(exc)) from exc

        return True, 0
