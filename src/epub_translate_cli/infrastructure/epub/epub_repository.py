from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
from epub_translate_cli.domain.models import ChapterDocument
from epub_translate_cli.domain.ports import EpubBook, EpubRepositoryPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)


@dataclass(frozen=True)
class ZipEpubRepository(EpubRepositoryPort):
    """Load and save EPUBs as zip archives.

    Notes:
    - EPUB is a zip container with specific constraints (mimetype must be first and stored).
    - This implementation preserves all non-chapter items byte-for-byte.
    """

    @staticmethod
    def _read_archive_items(input_path: Path) -> dict[str, bytes]:
        """Read every ZIP member from EPUB archive into memory."""
        with zipfile.ZipFile(input_path, "r") as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    @staticmethod
    def _is_chapter_resource(resource_path: str) -> bool:
        """Return True when resource path likely contains chapter markup."""
        return resource_path.lower().endswith((".xhtml", ".html", ".htm"))

    @classmethod
    def _chapter_documents(cls, items: dict[str, bytes]) -> list[ChapterDocument]:
        """Convert archive items into ordered chapter document objects."""
        return [
            ChapterDocument(path=resource_path, xhtml_bytes=content)
            for resource_path, content in items.items()
            if cls._is_chapter_resource(resource_path)
        ]

    @staticmethod
    def _write_archive_items(book: EpubBook, output_path: Path) -> None:
        """Write EPUB items preserving `mimetype` ordering constraints."""
        with zipfile.ZipFile(output_path, "w") as archive:
            if "mimetype" in book.items:
                archive.writestr(
                    "mimetype",
                    book.items["mimetype"],
                    compress_type=zipfile.ZIP_STORED,
                )

            for name, content in book.items.items():
                if name == "mimetype":
                    continue
                archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)

    def load(self, input_path: Path) -> EpubBook:
        """Load EPUB archive and return chapter-aware in-memory representation."""
        try:
            items = self._read_archive_items(input_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubReadError(str(exc)) from exc

        chapters = self._chapter_documents(items)

        logger.debug(
            "EPUB repository load completed | items=%s chapters=%s",
            len(items),
            len(chapters),
        )
        return EpubBook(items=items, chapters=chapters)

    def save(self, book: EpubBook, output_path: Path) -> None:
        """Persist in-memory EPUB book representation to archive file."""
        try:
            self._write_archive_items(book, output_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubWriteError(str(exc)) from exc

        logger.debug(
            "EPUB repository save completed | items=%s path=%s",
            len(book.items),
            output_path,
        )
