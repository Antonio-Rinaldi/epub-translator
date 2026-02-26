from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.models import TranslationSettings
from epub_translate_cli.infrastructure.epub.epub_repository import ZipEpubRepository
from epub_translate_cli.infrastructure.llm.ollama_translator import OllamaTranslator
from epub_translate_cli.infrastructure.reporting.json_report_writer import JsonReportWriter

console = Console()


def translate(
    in_path: Annotated[Path, typer.Option("--in", exists=True, file_okay=True, dir_okay=False, readable=True)],
    out_path: Annotated[Path, typer.Option("--out", file_okay=True, dir_okay=False)],
    source_lang: Annotated[str, typer.Option("--source-lang")],
    target_lang: Annotated[str, typer.Option("--target-lang")],
    model: Annotated[str, typer.Option("--model")],
    temperature: Annotated[float, typer.Option("--temperature", min=0.0, max=2.0)] = 0.2,
    retries: Annotated[int, typer.Option("--retries", min=0, max=10)] = 3,
    report_out: Annotated[Optional[Path], typer.Option("--report-out")] = None,
    abort_on_error: Annotated[bool, typer.Option("--abort-on-error")] = False,
) -> None:
    """Translate an EPUB using a local Ollama model."""

    report_path = report_out or out_path.with_suffix(out_path.suffix + ".report.json")

    settings = TranslationSettings(
        source_lang=source_lang,
        target_lang=target_lang,
        model=model,
        temperature=temperature,
        retries=retries,
        abort_on_error=abort_on_error,
    )

    epub_repo = ZipEpubRepository()
    translator = OllamaTranslator()
    report_writer = JsonReportWriter()

    orchestrator = TranslationOrchestrator(
        epub_repository=epub_repo,
        translator=translator,
        report_writer=report_writer,
    )

    result = orchestrator.translate_epub(
        input_path=in_path,
        output_path=out_path,
        report_path=report_path,
        settings=settings,
    )

    console.print(f"Report written: {report_path}")
    console.print(json.dumps({"output_written": result.output_written, "failures": result.failures}, indent=2))

    raise typer.Exit(code=result.exit_code)
