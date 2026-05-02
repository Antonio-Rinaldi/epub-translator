from __future__ import annotations

from pathlib import Path

from epub_translate_cli.domain.models import (
    ChapterReport,
    NodeChange,
    NodeFailure,
    TranslationSettings,
)
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
)


def _settings(**kwargs: object) -> TranslationSettings:
    base = dict(
        source_lang="en",
        target_lang="it",
        model="x",
        temperature=0.2,
        retries=0,
        abort_on_error=False,
        workers=1,
        context_paragraphs=3,
    )
    base.update(kwargs)  # type: ignore[arg-type]
    return TranslationSettings(**base)  # type: ignore[arg-type]


def _empty_report(chapter_path: str) -> ChapterReport:
    return ChapterReport(
        chapter_path=chapter_path,
        changes=(),
        failures=(),
        skips=(),
    )


def _report_with_changes(chapter_path: str) -> ChapterReport:
    return ChapterReport(
        chapter_path=chapter_path,
        changes=(
            NodeChange(
                chapter_path=chapter_path,
                node_path="/html/body/p[1]",
                before="Hello",
                after="Ciao",
            ),
        ),
        failures=(),
        skips=(),
    )


def _report_with_failure(chapter_path: str) -> ChapterReport:
    return ChapterReport(
        chapter_path=chapter_path,
        changes=(),
        failures=(
            NodeFailure(
                chapter_path=chapter_path,
                node_path="/html/body/p[1]",
                text="Hello",
                error_type="RetryableTranslationError",
                message="transient",
                attempts=1,
            ),
        ),
        skips=(),
    )


def test_save_and_resume_completes(tmp_path: Path) -> None:
    input_path = tmp_path / "book.epub"
    input_path.write_bytes(b"epub")
    output_path = tmp_path / "out.epub"
    report_path = tmp_path / "report.json"
    settings = _settings()

    store = FilesystemChapterStageStore.for_run(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=settings,
    )

    xhtml_0 = b"<html><body><p>Ciao</p></body></html>"
    xhtml_1 = b"<html><body><p>Mondo</p></body></html>"

    store.save_chapter(
        chapter_index=0,
        chapter_path="ch1.xhtml",
        xhtml_bytes=xhtml_0,
        report=_report_with_changes("ch1.xhtml"),
    )
    store.save_chapter(
        chapter_index=1,
        chapter_path="ch2.xhtml",
        xhtml_bytes=xhtml_1,
        report=_report_with_changes("ch2.xhtml"),
    )

    completed = store.load_completed()
    assert set(completed.keys()) == {0, 1}
    assert completed[0].xhtml_bytes == xhtml_0
    assert completed[1].xhtml_bytes == xhtml_1


def test_signature_change_resets_workspace(tmp_path: Path) -> None:
    input_path = tmp_path / "book.epub"
    input_path.write_bytes(b"epub")
    output_path = tmp_path / "out.epub"
    report_path = tmp_path / "report.json"

    store1 = FilesystemChapterStageStore.for_run(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=_settings(model="model-a"),
    )
    store1.save_chapter(
        chapter_index=0,
        chapter_path="ch1.xhtml",
        xhtml_bytes=b"<p>x</p>",
        report=_empty_report("ch1.xhtml"),
    )

    store2 = FilesystemChapterStageStore.for_run(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=_settings(model="model-b"),
    )
    completed = store2.load_completed()
    assert completed == {}


def test_chapter_with_failure_is_not_completed(tmp_path: Path) -> None:
    input_path = tmp_path / "book.epub"
    input_path.write_bytes(b"epub")
    output_path = tmp_path / "out.epub"
    report_path = tmp_path / "report.json"

    store = FilesystemChapterStageStore.for_run(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        settings=_settings(),
    )
    store.save_chapter(
        chapter_index=0,
        chapter_path="ch1.xhtml",
        xhtml_bytes=b"<p>x</p>",
        report=_report_with_failure("ch1.xhtml"),
    )

    completed = store.load_completed()
    assert completed == {}
