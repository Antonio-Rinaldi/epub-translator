from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.errors import RetryableTranslationError
from epub_translate_cli.domain.models import TranslationRequest, TranslationResponse, TranslationSettings
from epub_translate_cli.domain.ports import EpubBook, EpubRepositoryPort, ReportWriterPort, TranslatorPort


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
    last = None

    def write(self, report, report_path: Path) -> None:  # type: ignore[no-untyped-def]
        object.__setattr__(self, "last", report)


def test_abort_on_error_skips_save(tmp_path: Path) -> None:
    from epub_translate_cli.domain.models import ChapterDocument

    xhtml = b"<?xml version='1.0' encoding='utf-8'?><html xmlns='http://www.w3.org/1999/xhtml'><body><p>Hello</p></body></html>"
    book = EpubBook(items={"mimetype": b"application/epub+zip", "OEBPS/ch1.xhtml": xhtml}, chapters=[ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=xhtml)])

    repo = FakeRepo(book=book)
    translator = AlwaysFailTranslator()
    writer = SinkReportWriter()

    orchestrator = TranslationOrchestrator(epub_repository=repo, translator=translator, report_writer=writer)

    settings = TranslationSettings(
        source_lang="en",
        target_lang="it",
        model="x",
        temperature=0.2,
        retries=0,
        abort_on_error=True,
    )

    result = orchestrator.translate_epub(
        input_path=tmp_path / "in.epub",
        output_path=tmp_path / "out.epub",
        report_path=tmp_path / "report.json",
        settings=settings,
    )

    assert result.output_written is False
    assert result.exit_code == 2
