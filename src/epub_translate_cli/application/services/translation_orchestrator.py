from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    ChapterReport,
    ChapterTranslationResult,
    EpubBook,
    RunReport,
    StagedChapter,
    TranslationRunResult,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import (
    ChapterProcessorPort,
    ChapterStageStorePort,
    EpubRepositoryPort,
    ReportWriterPort,
)
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

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
    chapter_processor: ChapterProcessorPort
    report_writer: ReportWriterPort
    stage_store: ChapterStageStorePort

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

        if reset_resume_state:
            logger.info("Resetting staged resume workspace before translation")
            self.stage_store.clear()

        resumed = self.stage_store.load_completed()
        logger.info("Loaded EPUB | chapters=%s workers=%s", len(book.chapters), settings.workers)
        if resumed:
            logger.info("Resuming run from staged chapters | completed=%s", len(resumed))

        chapter_overrides, chapter_reports = self._translate_chapters(
            book,
            settings.workers,
            resumed,
        )
        updated_items = self._merged_items(book.items, chapter_overrides)

        failures_count = sum(len(r.failures) for r in chapter_reports)
        output_written, exit_code = self._write_output_if_allowed(
            updated_items=updated_items,
            chapters=book.chapters,
            compression_types=book.compression_types,
            output_path=output_path,
            abort_on_error=settings.abort_on_error,
            failures_count=failures_count,
        )

        report = self._build_run_report(
            input_path=input_path,
            output_path=output_path,
            report_path=report_path,
            settings=settings,
            chapter_reports=chapter_reports,
            output_written=output_written,
        )
        self.report_writer.write(report, report_path)

        if output_written:
            self.stage_store.clear()

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
        result: ChapterTranslationResult,
    ) -> ChapterReport:
        """Convert chapter result into a frozen report section."""
        return ChapterReport(
            chapter_path=chapter_path,
            changes=tuple(result.changes),
            failures=tuple(result.failures),
            skips=tuple(result.skips),
        )

    @staticmethod
    def _ordered_reports(chapter_reports: list[ChapterReport | None]) -> list[ChapterReport]:
        """Return ordered chapter reports after validating all entries are populated."""
        missing = sum(1 for r in chapter_reports if r is None)
        assert missing == 0, f"Missing chapter reports for {missing} chapters"
        return [r for r in chapter_reports if r is not None]

    @staticmethod
    def _merged_items(
        base_items: dict[str, bytes], overrides: dict[str, bytes]
    ) -> dict[str, bytes]:
        """Merge chapter overrides into original EPUB item payload map."""
        return {**base_items, **overrides}

    def _translate_chapters(
        self,
        book: EpubBook,
        workers: int,
        resumed: dict[int, StagedChapter],
    ) -> tuple[dict[str, bytes], list[ChapterReport]]:
        """Translate pending chapters and merge with resumed staged chapter snapshots."""
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
                pool.submit(self._translate_one_chapter, work): work for work in pending_works
            }
            for future in as_completed(futures):
                index, updated_xhtml, result = future.result()
                chapter = book.chapters[index]
                updated_items[chapter.path] = updated_xhtml
                chapter_report = self._chapter_report(chapter.path, result)
                chapter_reports[index] = chapter_report
                self.stage_store.save_chapter(
                    chapter_index=index,
                    chapter_path=chapter.path,
                    xhtml_bytes=updated_xhtml,
                    report=chapter_report,
                )

        return updated_items, self._ordered_reports(chapter_reports)

    def _translate_one_chapter(
        self,
        work: _ChapterWork,
    ) -> tuple[int, bytes, ChapterTranslationResult]:
        """Translate one chapter and return zero-based index, bytes, and result."""
        chapter_index = work.chapter_index - 1  # zero-based index used throughout

        logger.info(
            "Translating chapter %s/%s | path=%s",
            work.chapter_index,
            work.total,
            work.chapter.path,
        )

        def _on_progress(xhtml_bytes: bytes) -> None:
            """Write current XHTML state to the staging file after each paragraph.

            Uses save_progress (XHTML-only, no manifest update) so concurrent
            chapters translating in parallel never race on the shared manifest.
            """
            self.stage_store.save_progress(
                chapter_index=chapter_index,
                xhtml_bytes=xhtml_bytes,
            )

        updated_xhtml, result = self.chapter_processor.translate_chapter(
            work.chapter,
            on_progress=_on_progress,
        )
        logger.debug(
            "Chapter completed | path=%s changed=%s failed=%s skipped=%s",
            work.chapter.path,
            len(result.changes),
            len(result.failures),
            len(result.skips),
        )
        return chapter_index, updated_xhtml, result

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
        """Assemble fully-constructed immutable run report."""
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
            chapters=tuple(chapter_reports),
        )

    def _write_output_if_allowed(
        self,
        *,
        updated_items: dict[str, bytes],
        chapters: list[ChapterDocument],
        compression_types: dict[str, int],
        output_path: Path,
        abort_on_error: bool,
        failures_count: int,
    ) -> tuple[bool, int]:
        """Write translated EPUB unless abort-on-error policy blocks output creation."""
        if abort_on_error and failures_count > 0:
            logger.info("Aborting EPUB write due to failures | failures=%s", failures_count)
            return False, 2

        logger.info("Writing translated EPUB | path=%s", output_path)
        try:
            self.epub_repository.save(
                EpubBook(
                    items=updated_items,
                    chapters=chapters,
                    compression_types=compression_types,
                ),
                output_path,
            )
        except Exception as exc:  # noqa: BLE001
            raise EpubWriteError(str(exc)) from exc

        return True, 0
