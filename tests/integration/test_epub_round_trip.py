from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.application.services.chapter_translator import ChapterTranslator
from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.models import (
    RunReport,
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import ReportWriterPort
from epub_translate_cli.infrastructure.epub.epub_repository import ZipEpubRepository
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
)

_CHAPTER_1 = b"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <body><p>First chapter text.</p></body>
</html>"""

_CHAPTER_2 = b"""<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <body><p>Second chapter text.</p></body>
</html>"""

_OPF = b"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns='http://www.idpf.org/2007/opf' version='2.0'>
  <manifest>
    <item id='ch1' href='Text/ch1.xhtml' media-type='application/xhtml+xml'/>
    <item id='ch2' href='Text/ch2.xhtml' media-type='application/xhtml+xml'/>
  </manifest>
  <spine>
    <itemref idref='ch1'/>
    <itemref idref='ch2'/>
  </spine>
</package>"""

_CONTAINER = b"""<?xml version='1.0' encoding='utf-8'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
  <rootfiles>
    <rootfile full-path='OEBPS/content.opf'
              media-type='application/oebps-package+xml'/>
  </rootfiles>
</container>"""


def _build_epub(tmp_path: Path) -> Path:
    epub_path = tmp_path / "book.epub"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER)
        zf.writestr("OEBPS/content.opf", _OPF)
        zf.writestr("OEBPS/Text/ch1.xhtml", _CHAPTER_1)
        zf.writestr("OEBPS/Text/ch2.xhtml", _CHAPTER_2)
    epub_path.write_bytes(buf.getvalue())
    return epub_path


@dataclass(frozen=True)
class PrefixTranslator:
    """Prepends '[T] ' to every text to make translations verifiable."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        return TranslationResponse(translated_text=f"[T] {request.text}")


@dataclass(frozen=True)
class SinkReportWriter(ReportWriterPort):
    last: RunReport | None = None

    def write(self, report: RunReport, report_path: Path) -> None:
        object.__setattr__(self, "last", report)


def test_full_round_trip_preserves_spine_order(tmp_path: Path) -> None:
    epub_path = _build_epub(tmp_path)
    out_path = tmp_path / "out.epub"
    report_path = tmp_path / "report.json"

    settings = TranslationSettings(
        source_lang="en",
        target_lang="it",
        model="test",
        temperature=0.0,
        retries=0,
        abort_on_error=False,
        workers=1,
        context_paragraphs=0,
    )

    translator = PrefixTranslator()
    chapter_processor = ChapterTranslator(
        translator=translator,
        settings=settings,
        xhtml_parser=XHTMLTranslator(),
    )
    stage_store = FilesystemChapterStageStore.for_run(
        input_path=epub_path,
        output_path=out_path,
        report_path=report_path,
        settings=settings,
    )
    writer = SinkReportWriter()
    orchestrator = TranslationOrchestrator(
        epub_repository=ZipEpubRepository(),
        chapter_processor=chapter_processor,
        report_writer=writer,
        stage_store=stage_store,
    )

    result = orchestrator.translate_epub(
        input_path=epub_path,
        output_path=out_path,
        report_path=report_path,
        settings=settings,
    )

    assert result.output_written is True
    assert result.failures == 0

    # Reload translated EPUB and verify chapter content and spine order.
    reloaded = ZipEpubRepository().load(out_path)
    assert len(reloaded.chapters) == 2

    paths = [c.path for c in reloaded.chapters]
    assert paths == ["OEBPS/Text/ch1.xhtml", "OEBPS/Text/ch2.xhtml"]

    assert b"[T]" in reloaded.chapters[0].xhtml_bytes
    assert b"[T]" in reloaded.chapters[1].xhtml_bytes

    assert b"First chapter" in reloaded.chapters[0].xhtml_bytes
    assert b"Second chapter" in reloaded.chapters[1].xhtml_bytes

    assert writer.last is not None
    assert writer.last.totals()["chapters"] == 2
    assert writer.last.totals()["failed"] == 0
