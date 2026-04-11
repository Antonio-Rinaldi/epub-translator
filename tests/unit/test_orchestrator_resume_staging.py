from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.errors import RetryableTranslationError
from epub_translate_cli.domain.models import (
    ChapterDocument,
    RunReport,
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import (
    EpubBook,
    EpubRepositoryPort,
    ReportWriterPort,
    TranslatorPort,
)
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
)


@dataclass
class RecordingRepo(EpubRepositoryPort):
    book: EpubBook
    saves: list[EpubBook] = field(default_factory=list)

    def load(self, input_path: Path) -> EpubBook:
        return self.book

    def save(self, book: EpubBook, output_path: Path) -> None:
        self.saves.append(book)


@dataclass
class FlakyChapterTranslator(TranslatorPort):
    fail_second_once: bool = True
    seen_texts: list[str] = field(default_factory=list)

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        self.seen_texts.append(request.text)
        if request.text == "Second chapter." and self.fail_second_once:
            self.fail_second_once = False
            raise RetryableTranslationError("transient")
        translated = "Primo capitolo." if request.text == "First chapter." else "Secondo capitolo."
        return TranslationResponse(translated_text=translated)


@dataclass
class SinkReportWriter(ReportWriterPort):
    last: RunReport | None = None

    def write(self, report: RunReport, report_path: Path) -> None:
        self.last = report


def _settings(*, abort_on_error: bool) -> TranslationSettings:
    return TranslationSettings(
        source_lang="en",
        target_lang="it",
        model="x",
        temperature=0.2,
        retries=0,
        abort_on_error=abort_on_error,
        workers=1,
        context_paragraphs=3,
    )


def test_resume_retries_failed_chapters_when_input_equals_output(tmp_path: Path) -> None:
    chapter_1 = (
        b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        b"<body><p>First chapter.</p></body></html>"
    )
    chapter_2 = (
        b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        b"<body><p>Second chapter.</p></body></html>"
    )
    book = EpubBook(
        items={
            "mimetype": b"application/epub+zip",
            "OEBPS/ch1.xhtml": chapter_1,
            "OEBPS/ch2.xhtml": chapter_2,
        },
        chapters=[
            ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=chapter_1),
            ChapterDocument(path="OEBPS/ch2.xhtml", xhtml_bytes=chapter_2),
        ],
    )

    repo = RecordingRepo(book=book)
    translator = FlakyChapterTranslator()
    writer = SinkReportWriter()
    orchestrator = TranslationOrchestrator(
        epub_repository=repo,
        translator=translator,
        report_writer=writer,
    )

    input_output_path = tmp_path / "book.epub"
    input_output_path.write_bytes(b"placeholder")
    report_path = tmp_path / "book.report.json"

    first_run = orchestrator.translate_epub(
        input_path=input_output_path,
        output_path=input_output_path,
        report_path=report_path,
        settings=_settings(abort_on_error=True),
    )
    assert first_run.output_written is False
    assert first_run.failures == 1
    assert translator.seen_texts.count("First chapter.") == 1
    assert translator.seen_texts.count("Second chapter.") == 1
    assert repo.saves == []

    stage_dir = FilesystemChapterStageStore.workspace_path(report_path)
    assert stage_dir.exists()

    second_run = orchestrator.translate_epub(
        input_path=input_output_path,
        output_path=input_output_path,
        report_path=report_path,
        settings=_settings(abort_on_error=False),
    )
    assert second_run.output_written is True
    assert second_run.failures == 0
    assert translator.seen_texts.count("First chapter.") == 1
    assert translator.seen_texts.count("Second chapter.") == 2
    assert len(repo.saves) == 1

    saved = repo.saves[0]
    assert b"Primo capitolo." in saved.items["OEBPS/ch1.xhtml"]
    assert b"Secondo capitolo." in saved.items["OEBPS/ch2.xhtml"]
    assert writer.last is not None
    assert writer.last.totals()["failed"] == 0
    assert stage_dir.exists() is False


def test_reset_resume_state_forces_full_retranslation(tmp_path: Path) -> None:
    chapter_1 = (
        b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        b"<body><p>First chapter.</p></body></html>"
    )
    chapter_2 = (
        b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'>"
        b"<body><p>Second chapter.</p></body></html>"
    )
    book = EpubBook(
        items={
            "mimetype": b"application/epub+zip",
            "OEBPS/ch1.xhtml": chapter_1,
            "OEBPS/ch2.xhtml": chapter_2,
        },
        chapters=[
            ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=chapter_1),
            ChapterDocument(path="OEBPS/ch2.xhtml", xhtml_bytes=chapter_2),
        ],
    )

    repo = RecordingRepo(book=book)
    translator = FlakyChapterTranslator()
    writer = SinkReportWriter()
    orchestrator = TranslationOrchestrator(
        epub_repository=repo,
        translator=translator,
        report_writer=writer,
    )

    input_output_path = tmp_path / "book.epub"
    input_output_path.write_bytes(b"placeholder")
    report_path = tmp_path / "book.report.json"

    first_run = orchestrator.translate_epub(
        input_path=input_output_path,
        output_path=input_output_path,
        report_path=report_path,
        settings=_settings(abort_on_error=True),
    )
    assert first_run.output_written is False
    assert first_run.failures == 1

    stage_dir = FilesystemChapterStageStore.workspace_path(report_path)
    assert stage_dir.exists()

    second_run = orchestrator.translate_epub(
        input_path=input_output_path,
        output_path=input_output_path,
        report_path=report_path,
        settings=_settings(abort_on_error=False),
        reset_resume_state=True,
    )
    assert second_run.output_written is True
    assert second_run.failures == 0
    assert translator.seen_texts.count("First chapter.") == 2
    assert translator.seen_texts.count("Second chapter.") == 2
    assert len(repo.saves) == 1
    assert stage_dir.exists() is False
