from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from epub_translate_cli.application.services.chapter_translator import ChapterTranslator
from epub_translate_cli.application.services.translation_orchestrator import TranslationOrchestrator
from epub_translate_cli.domain.models import TranslationRunResult, TranslationSettings
from epub_translate_cli.infrastructure.epub.epub_repository import ZipEpubRepository
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator
from epub_translate_cli.infrastructure.llm.ollama_translator import OllamaTranslator
from epub_translate_cli.infrastructure.llm.prompt_builder import (
    GlossaryAwarePromptBuilder,
    JsonGlossaryLoader,
    TomlGlossaryLoader,
)
from epub_translate_cli.infrastructure.logging.logger_factory import (
    configure_logging,
    create_logger,
)
from epub_translate_cli.infrastructure.reporting.chapter_stage_store import (
    FilesystemChapterStageStore,
)
from epub_translate_cli.infrastructure.reporting.json_report_writer import JsonReportWriter

console = Console()
logger = create_logger(__name__)


@dataclass(frozen=True)
class TranslateCommand:
    """Validated CLI command payload used by translation pipeline."""

    input_path: Path
    output_path: Path
    source_lang: str
    target_lang: str
    model: str
    temperature: float
    retries: int
    report_path: Path
    abort_on_error: bool
    log_level: str
    ollama_url: str
    workers: int
    context_paragraphs: int
    reset_resume_state: bool
    glossary_path: Path | None = None


def _abort(msg: str) -> None:
    """Print an error and stop command execution with non-zero exit code."""
    console.print(f"[bold red]Error:[/bold red] {msg}")
    raise typer.Exit(code=1)


def _validate_input_path(input_path: Path) -> None:
    """Validate input path exists and points to a file."""
    if not input_path.exists():
        _abort(f"Input file not found: {input_path}")
    if not input_path.is_file():
        _abort(f"--in must point to a file, not a directory: {input_path}")


def _resolve_report_path(output_path: Path, report_out: Path | None) -> Path:
    """Resolve report output path from flag or derived default."""
    return report_out or output_path.with_suffix(output_path.suffix + ".report.json")


def _build_command(
    *,
    input_path: Path,
    output_path: Path,
    source_lang: str,
    target_lang: str,
    model: str,
    temperature: float,
    retries: int,
    report_out: Path | None,
    abort_on_error: bool,
    log_level: str,
    ollama_url: str,
    workers: int,
    context_paragraphs: int,
    reset_resume_state: bool,
    glossary_path: Path | None,
) -> TranslateCommand:
    """Build immutable validated command object from raw CLI arguments."""
    _validate_input_path(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return TranslateCommand(
        input_path=input_path,
        output_path=output_path,
        source_lang=source_lang,
        target_lang=target_lang,
        model=model,
        temperature=temperature,
        retries=retries,
        report_path=_resolve_report_path(output_path, report_out),
        abort_on_error=abort_on_error,
        log_level=log_level,
        ollama_url=ollama_url,
        workers=workers,
        context_paragraphs=context_paragraphs,
        reset_resume_state=reset_resume_state,
        glossary_path=glossary_path,
    )


def _build_settings(command: TranslateCommand) -> TranslationSettings:
    """Map validated command data to domain translation settings."""
    return TranslationSettings(
        source_lang=command.source_lang,
        target_lang=command.target_lang,
        model=command.model,
        temperature=command.temperature,
        retries=command.retries,
        abort_on_error=command.abort_on_error,
        workers=command.workers,
        context_paragraphs=command.context_paragraphs,
    )


def _duration_hms(total_seconds: float) -> str:
    """Convert elapsed seconds to HH:MM:SS."""
    hh, rem = divmod(int(total_seconds), 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _load_glossary_terms(glossary_path: Path | None) -> dict[str, str]:
    """Load glossary terms from file if path is provided, otherwise return empty dict."""
    if glossary_path is None:
        return {}
    suffix = glossary_path.suffix.lower()
    if suffix == ".toml":
        return TomlGlossaryLoader().load(glossary_path).as_dict()
    if suffix == ".json":
        return JsonGlossaryLoader().load(glossary_path).as_dict()
    _abort(f"Unsupported glossary file format: {suffix} (use .toml or .json)")
    return {}  # unreachable, but needed for type checker


def _run_translation(
    command: TranslateCommand,
    settings: TranslationSettings,
) -> tuple[TranslationRunResult, float]:
    """Wire all adapters and execute the orchestrator translation run."""
    glossary_terms = _load_glossary_terms(command.glossary_path)
    translator = OllamaTranslator(
        settings=settings,
        base_url=command.ollama_url,
        prompt_builder=GlossaryAwarePromptBuilder(),
    )
    chapter_processor = ChapterTranslator(
        translator=translator,
        settings=settings,
        xhtml_parser=XHTMLTranslator(),
        glossary_terms=glossary_terms,
    )
    stage_store = FilesystemChapterStageStore.for_run(
        input_path=command.input_path,
        output_path=command.output_path,
        report_path=command.report_path,
        settings=settings,
    )
    orchestrator = TranslationOrchestrator(
        epub_repository=ZipEpubRepository(),
        chapter_processor=chapter_processor,
        report_writer=JsonReportWriter(),
        stage_store=stage_store,
    )

    start = time.perf_counter()
    result = orchestrator.translate_epub(
        input_path=command.input_path,
        output_path=command.output_path,
        report_path=command.report_path,
        settings=settings,
        reset_resume_state=command.reset_resume_state,
    )
    elapsed = time.perf_counter() - start
    return result, elapsed


def _print_summary(
    report_path: Path,
    output_written: bool,
    failures: int,
    elapsed_seconds: float,
) -> None:
    """Print terminal summary after run completion."""
    console.print(f"Report written: {report_path}")
    console.print(
        json.dumps(
            {
                "output_written": output_written,
                "failures": failures,
                "duration": _duration_hms(elapsed_seconds),
            },
            indent=2,
        )
    )


def translate(
    in_path: Annotated[Path, typer.Option("--in", help="Input EPUB file path")],
    out_path: Annotated[Path, typer.Option("--out", help="Output translated EPUB file path")],
    source_lang: Annotated[str, typer.Option("--source-lang")],
    target_lang: Annotated[str, typer.Option("--target-lang")],
    model: Annotated[str, typer.Option("--model", help="Ollama model for translation")],
    temperature: Annotated[float, typer.Option("--temperature", min=0.0, max=2.0)] = 0.2,
    retries: Annotated[int, typer.Option("--retries", min=0, max=10)] = 3,
    report_out: Annotated[Path | None, typer.Option("--report-out")] = None,
    abort_on_error: Annotated[bool, typer.Option("--abort-on-error")] = False,
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Logging level: DEBUG or INFO"),
    ] = "INFO",
    ollama_url: Annotated[
        str,
        typer.Option("--ollama-url", help="Ollama API base URL for the translation model"),
    ] = "http://localhost:11434",
    workers: Annotated[
        int,
        typer.Option("--workers", min=1, max=32, help="Parallel chapter workers"),
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
    reset_resume_state: Annotated[
        bool,
        typer.Option(
            "--reset-resume-state",
            help="Clear staged chapter resume data before starting this run",
        ),
    ] = False,
    glossary: Annotated[
        Path | None,
        typer.Option(
            "--glossary",
            help="Optional glossary file (.toml or .json) with term→translation mappings",
        ),
    ] = None,
) -> None:
    """Translate an EPUB using a local Ollama model."""
    command = _build_command(
        input_path=in_path,
        output_path=out_path,
        source_lang=source_lang,
        target_lang=target_lang,
        model=model,
        temperature=temperature,
        retries=retries,
        report_out=report_out,
        abort_on_error=abort_on_error,
        log_level=log_level,
        ollama_url=ollama_url,
        workers=workers,
        context_paragraphs=context_paragraphs,
        reset_resume_state=reset_resume_state,
        glossary_path=glossary,
    )

    configure_logging(command.log_level)
    settings = _build_settings(command)

    logger.info(
        "Starting translation | in=%s out=%s source=%s target=%s model=%s",
        command.input_path,
        command.output_path,
        command.source_lang,
        command.target_lang,
        command.model,
    )

    result, elapsed = _run_translation(command, settings)
    duration_hms = _duration_hms(elapsed)

    logger.info(
        "Translation finished | output_written=%s failures=%s report=%s exit_code=%s in %s",
        result.output_written,
        result.failures,
        command.report_path,
        result.exit_code,
        duration_hms,
    )

    _print_summary(command.report_path, result.output_written, result.failures, elapsed)
    raise typer.Exit(code=result.exit_code)
