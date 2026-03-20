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
    def load(self, input_path: Path) -> "EpubBook":
        raise NotImplementedError

    def save(self, book: "EpubBook", output_path: Path) -> None:
        raise NotImplementedError


class TranslatorPort(Protocol):
    def translate(self, request: TranslationRequest) -> TranslationResponse:
        raise NotImplementedError


class ReportWriterPort(Protocol):
    def write(self, report: RunReport, report_path: Path) -> None:
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
