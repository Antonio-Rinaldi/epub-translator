from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from epub_translate_cli.domain.models import (
    ChapterDocument,
    RunReport,
    TranslationRequest,
    TranslationResponse,
)


class EpubRepositoryPort(Protocol):
    """Abstraction for loading and saving EPUB archive content."""

    def load(self, input_path: Path) -> EpubBook:
        """Load EPUB archive from disk into in-memory representation."""
        raise NotImplementedError

    def save(self, book: EpubBook, output_path: Path) -> None:
        """Persist in-memory EPUB representation back to archive on disk."""
        raise NotImplementedError


class TranslatorPort(Protocol):
    """Abstraction for text translation providers (e.g., Ollama)."""

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        """Translate one text request and return translated content."""
        raise NotImplementedError


class ReportWriterPort(Protocol):
    """Abstraction for writing run reports to persistent storage."""

    def write(self, report: RunReport, report_path: Path) -> None:
        """Write one run report artifact to the given path."""
        raise NotImplementedError


@dataclass(frozen=True)
class EpubBook:
    """In-memory EPUB representation used by the application layer.

    `items` maps internal EPUB path -> bytes content.
    `chapters` contains parsed XHTML chapters derived from items.

    Keeping both allows round-trip with minimal loss.
    """

    items: dict[str, bytes]
    chapters: list[ChapterDocument]
