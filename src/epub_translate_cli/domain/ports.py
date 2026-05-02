from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from epub_translate_cli.domain.models import (
    ChapterDocument,
    ChapterReport,
    ChapterTranslationResult,
    EpubBook,
    Glossary,
    RunReport,
    StagedChapter,
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)


class EpubRepositoryPort(Protocol):
    """Abstraction for loading and saving EPUB archive content."""

    def load(self, input_path: Path) -> EpubBook:
        """Load EPUB archive from disk into in-memory representation."""
        ...

    def save(self, book: EpubBook, output_path: Path) -> None:
        """Persist in-memory EPUB representation back to archive on disk."""
        ...


class TranslatorPort(Protocol):
    """Abstraction for text translation providers (e.g., Ollama)."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        """Translate one text request and return translated content."""
        ...


class ReportWriterPort(Protocol):
    """Abstraction for writing run reports to persistent storage."""

    def write(self, report: RunReport, report_path: Path) -> None:
        """Write one run report artifact to the given path."""
        ...


class ChapterStageStorePort(Protocol):
    """Abstraction for persisting and resuming per-chapter staged translation state."""

    def load_completed(self) -> dict[int, StagedChapter]:
        """Return all completed staged chapters keyed by zero-based chapter index."""
        ...

    def save_progress(self, *, chapter_index: int, xhtml_bytes: bytes) -> None:
        """Write updated XHTML bytes for an in-progress chapter without touching the manifest.

        Safe to call from worker threads — writes only the XHTML file so concurrent
        chapters translating in parallel never race on the shared manifest.
        """
        ...

    def save_chapter(
        self,
        *,
        chapter_index: int,
        chapter_path: str,
        xhtml_bytes: bytes,
        report: ChapterReport,
    ) -> None:
        """Persist a fully-translated chapter snapshot and update the manifest atomically."""
        ...

    def clear(self) -> None:
        """Remove all staged data (called after successful output write)."""
        ...


class PromptBuilderPort(Protocol):
    """Abstraction for building LLM prompts in system/user role format."""

    def build_system_prompt(self, settings: TranslationSettings) -> str:
        """Build the system role message: persona, rules, language-specific guidance."""
        ...

    def build_user_prompt(self, request: TranslationRequest) -> str:
        """Build the user role message: chapter context, prior translations, text to translate."""
        ...


class ChapterProcessorPort(Protocol):
    """Abstraction for translating one EPUB chapter and returning the updated XHTML bytes."""

    def translate_chapter(
        self,
        chapter: ChapterDocument,
        on_progress: Callable[[bytes], None] | None = None,
    ) -> tuple[bytes, ChapterTranslationResult]:
        """Translate one chapter and return updated XHTML bytes plus chapter result.

        `on_progress` is called after every successfully translated paragraph with
        the current serialised XHTML bytes, so callers can persist intermediate
        progress to disk without waiting for the entire chapter to finish.
        """
        ...


class GlossaryPort(Protocol):
    """Abstraction for loading a term glossary from a flat file."""

    def load(self, path: Path) -> Glossary:
        """Load a glossary from the given path and return a Glossary domain object."""
        ...
