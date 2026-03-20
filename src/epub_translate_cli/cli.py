from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.models import TranslationSettings
from epub_translate_cli.infrastructure.epub.epub_repository import ZipEpubRepository
from epub_translate_cli.infrastructure.llm.ollama_translator import OllamaTranslator
from epub_translate_cli.infrastructure.logging.logger_factory import configure_logging, create_logger
from epub_translate_cli.infrastructure.reporting.json_report_writer import JsonReportWriter

console = Console()
logger = create_logger(__name__)


def _abort(msg: str) -> None:
    """Print an error and exit with code 1 before any processing begins."""
    console.print(f"[bold red]Error:[/bold red] {msg}")
    raise typer.Exit(code=1)


def translate(
    in_path: Annotated[Path, typer.Option("--in", help="Input EPUB file path")],
    out_path: Annotated[Path, typer.Option("--out", help="Output translated EPUB file path")],
    source_lang: Annotated[str, typer.Option("--source-lang")],
    target_lang: Annotated[str, typer.Option("--target-lang")],
    model: Annotated[str, typer.Option("--model", help="Ollama model for translation")],
    temperature: Annotated[float, typer.Option("--temperature", min=0.0, max=2.0)] = 0.2,
    retries: Annotated[int, typer.Option("--retries", min=0, max=10)] = 3,
    report_out: Annotated[Optional[Path], typer.Option("--report-out")] = None,
    abort_on_error: Annotated[bool, typer.Option("--abort-on-error")] = False,
    log_level: Annotated[
        str, typer.Option("--log-level", help="Logging level: DEBUG or INFO")
    ] = "INFO",
    ollama_url: Annotated[
        str,
        typer.Option("--ollama-url", help="Ollama API base URL for the translation model"),
    ] = "http://localhost:11434",
    workers: Annotated[
        int, typer.Option("--workers", min=1, max=32, help="Parallel chapter workers")
    ] = 1,
    context_paragraphs: Annotated[
        int,
        typer.Option(
            "--context-paragraphs",
            min=0,
            max=20,
            help=(
                "Rolling context: number of preceding translated paragraphs "
                "per request (0 to disable)"
            ),
        ),
    ] = 3,
) -> None:
    """Translate an EPUB using a local Ollama model."""

    configure_logging(log_level)

    # 1. Input EPUB must exist and be a file.
    if not in_path.exists():
        _abort(f"Input file not found: {in_path}")
    if not in_path.is_file():
        _abort(f"--in must point to a file, not a directory: {in_path}")

    # 2. Output EPUB: create parent directory tree if needed.
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report_path = report_out or out_path.with_suffix(out_path.suffix + ".report.json")

    settings = TranslationSettings(
        source_lang=source_lang,
        target_lang=target_lang,
        model=model,
        temperature=temperature,
        retries=retries,
        abort_on_error=abort_on_error,
        workers=workers,
        context_paragraphs=context_paragraphs,
    )

    epub_repo = ZipEpubRepository()
    translator = OllamaTranslator(base_url=ollama_url)
    report_writer = JsonReportWriter()

    orchestrator = TranslationOrchestrator(
        epub_repository=epub_repo,
        translator=translator,
        report_writer=report_writer,
    )

    logger.info(
        "Starting translation | in=%s out=%s source=%s target=%s model=%s",
        in_path,
        out_path,
        source_lang,
        target_lang,
        model,
    )

    start = time.perf_counter()
    result = orchestrator.translate_epub(
        input_path=in_path,
        output_path=out_path,
        report_path=report_path,
        settings=settings,
    )
    end = time.perf_counter()

    elapsed = end - start
    hh, rem = divmod(int(elapsed), 3600)
    mm, ss = divmod(rem, 60)
    duration_hms = f"{hh:02d}:{mm:02d}:{ss:02d}"

    logger.info(
        "Translation finished | output_written=%s failures=%s report=%s exit_code=%s in %s",
        result.output_written,
        result.failures,
        report_path,
        result.exit_code,
        duration_hms,
    )

    console.print(f"Report written: {report_path}")
    console.print(
        json.dumps(
            {
                "output_written": result.output_written,
                "failures": result.failures,
                "duration": duration_hms,
            },
            indent=2,
        )
    )

    raise typer.Exit(code=result.exit_code)
