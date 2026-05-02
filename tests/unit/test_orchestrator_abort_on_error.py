from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.application.services.chapter_translator import ChapterTranslator
from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.errors import RetryableTranslationError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    EpubBook,
    RunReport,
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import (
    EpubRepositoryPort,
    ReportWriterPort,
    TranslatorPort,
)
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
)


@dataclass(frozen=True)
class FakeRepo(EpubRepositoryPort):
    book: EpubBook

    def load(self, input_path: Path) -> EpubBook:
        return self.book

    def save(self, book: EpubBook, output_path: Path) -> None:
        raise AssertionError("save() must not be called when abort-on-error triggers")


@dataclass(frozen=True)
class AlwaysFailTranslator(TranslatorPort):
    def translate(self, request: TranslationRequest) -> TranslationResponse:
        raise RetryableTranslationError("transient")


@dataclass(frozen=True)
class SinkReportWriter(ReportWriterPort):
    last: RunReport | None = None

    def write(self, report: RunReport, report_path: Path) -> None:
        object.__setattr__(self, "last", report)


def test_abort_on_error_skips_save(tmp_path: Path) -> None:
    xhtml = (
        b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        b"<body><p>Hello</p></body></html>"
    )
    book = EpubBook(
        items={"mimetype": b"application/epub+zip", "OEBPS/ch1.xhtml": xhtml},
        chapters=[ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=xhtml)],
        compression_types={},
    )

    settings = TranslationSettings(
        source_lang="en",
        target_lang="it",
        model="x",
        temperature=0.2,
        retries=0,
        abort_on_error=True,
    )

    input_path = tmp_path / "in.epub"
    output_path = tmp_path / "out.epub"
    report_path = tmp_path / "report.json"

    translator = AlwaysFailTranslator()
    chapter_processor = ChapterTranslator(
        translator=translator,
        settings=settings,
        xhtml_parser=XHTMLTranslator(),
    )
    stage_store = FilesystemChapterStageStore.for_run(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=settings,
    )

    orchestrator = TranslationOrchestrator(
        epub_repository=FakeRepo(book=book),
        chapter_processor=chapter_processor,
        report_writer=SinkReportWriter(),
        stage_store=stage_store,
    )

    result = orchestrator.translate_epub(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=settings,
    )

    assert result.output_written is False
    assert result.exit_code == 2
