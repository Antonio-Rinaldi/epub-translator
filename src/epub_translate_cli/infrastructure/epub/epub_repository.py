from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
from epub_translate_cli.domain.models import ChapterDocument, EpubBook
from epub_translate_cli.domain.ports import EpubRepositoryPort
from epub_translate_cli.infrastructure.epub.opf_spine_parser import OPFSpineParser
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)


@dataclass(frozen=True)
class ZipEpubRepository(EpubRepositoryPort):
    """Load and save EPUBs as zip archives.

    Notes:
    - EPUB is a zip container with specific constraints (mimetype must be first and stored).
    - Chapter reading order follows the OPF spine; falls back to lexicographic order.
    - Per-item compression type is preserved on save so binary assets are not re-compressed.
    """

    @staticmethod
    def _read_archive_items(
        input_path: Path,
    ) -> tuple[dict[str, bytes], dict[str, int]]:
        """Read every ZIP member from EPUB archive into memory with original compression types."""
        items: dict[str, bytes] = {}
        compression_types: dict[str, int] = {}
        with zipfile.ZipFile(input_path, "r") as archive:
            for info in archive.infolist():
                items[info.filename] = archive.read(info.filename)
                compression_types[info.filename] = info.compress_type
        return items, compression_types

    @staticmethod
    def _is_chapter_resource(resource_path: str) -> bool:
        """Return True when resource path likely contains chapter markup."""
        return resource_path.lower().endswith((".xhtml", ".html", ".htm"))

    @classmethod
    def _chapter_documents(
        cls,
        items: dict[str, bytes],
    ) -> list[ChapterDocument]:
        """Return chapter documents in OPF spine order, falling back to lexicographic."""
        chapter_paths = {path for path in items if cls._is_chapter_resource(path)}

        opf_path = OPFSpineParser.find_opf_path(items)
        if opf_path and opf_path in items:
            spine_order = OPFSpineParser.ordered_chapter_paths(
                opf_bytes=items[opf_path],
                all_paths=chapter_paths,
                opf_path=opf_path,
            )
            if spine_order is not None:
                logger.debug(
                    "Using OPF spine order | opf=%s chapters=%s",
                    opf_path,
                    len(spine_order),
                )
                return [ChapterDocument(path=p, xhtml_bytes=items[p]) for p in spine_order]

        logger.warning("OPF spine unavailable — falling back to lexicographic chapter order")
        return sorted(
            (ChapterDocument(path=p, xhtml_bytes=items[p]) for p in chapter_paths),
            key=lambda doc: doc.path,
        )

    @staticmethod
    def _write_archive_items(book: EpubBook, output_path: Path) -> None:
        """Write EPUB items preserving mimetype ordering and original compression modes."""
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
                compress_type = book.compression_types.get(name, zipfile.ZIP_DEFLATED)
                archive.writestr(name, content, compress_type=compress_type)

    def load(self, input_path: Path) -> EpubBook:
        """Load EPUB archive and return chapter-aware in-memory representation."""
        try:
            items, compression_types = self._read_archive_items(input_path)
        except Exception as exc:  # noqa: BLE001
            raise EpubReadError(str(exc)) from exc

        chapters = self._chapter_documents(items)

        logger.debug(
            "EPUB repository load completed | items=%s chapters=%s",
            len(items),
            len(chapters),
        )
        return EpubBook(items=items, chapters=chapters, compression_types=compression_types)

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
