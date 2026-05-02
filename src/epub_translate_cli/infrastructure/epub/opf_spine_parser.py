from __future__ import annotations

import posixpath

from lxml import etree

from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

_CONTAINER_PATH = "META-INF/container.xml"


class OPFSpineParser:
    """Parses EPUB OPF package documents to determine spine-ordered chapter paths."""

    @staticmethod
    def find_opf_path(items: dict[str, bytes]) -> str | None:
        """Return the OPF rootfile path from META-INF/container.xml, or None."""
        container_bytes = items.get(_CONTAINER_PATH)
        if not container_bytes:
            return None
        try:
            root = etree.fromstring(container_bytes)
            results = root.xpath("//*[local-name()='rootfile']/@full-path")
            if isinstance(results, list) and results and isinstance(results[0], str):
                return results[0]
        except etree.XMLSyntaxError:
            logger.warning("Failed to parse META-INF/container.xml")
        return None

    @staticmethod
    def ordered_chapter_paths(
        opf_bytes: bytes,
        all_paths: set[str],
        opf_path: str,
    ) -> list[str] | None:
        """Return chapter paths in spine reading order, or None if OPF is invalid.

        `opf_path` is the path of the OPF file within the archive (needed to resolve
        relative manifest hrefs). `all_paths` is the set of all archive item paths —
        only paths present there are returned.
        """
        opf_dir = posixpath.dirname(opf_path)

        try:
            root = etree.fromstring(opf_bytes)
        except etree.XMLSyntaxError:
            logger.warning("Failed to parse OPF file | path=%s", opf_path)
            return None

        # Build manifest: id -> resolved archive path
        manifest: dict[str, str] = {}
        item_results = root.xpath("//*[local-name()='item']")
        if isinstance(item_results, list):
            for item in item_results:
                if not isinstance(item, etree._Element):
                    continue
                item_id = item.get("id")
                href = item.get("href")
                if not item_id or not href:
                    continue
                resolved = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
                manifest[item_id] = resolved

        if not manifest:
            logger.warning("OPF manifest is empty | path=%s", opf_path)
            return None

        # Walk spine itemrefs in order
        ordered: list[str] = []
        itemref_results = root.xpath("//*[local-name()='itemref']")
        if isinstance(itemref_results, list):
            for itemref in itemref_results:
                if not isinstance(itemref, etree._Element):
                    continue
                idref = itemref.get("idref")
                if not idref or idref not in manifest:
                    continue
                resolved_path = manifest[idref]
                if resolved_path in all_paths:
                    ordered.append(resolved_path)

        if not ordered:
            logger.warning("OPF spine yielded no known chapter paths | path=%s", opf_path)
            return None

        return ordered
