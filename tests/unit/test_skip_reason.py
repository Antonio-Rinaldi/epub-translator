from __future__ import annotations

from lxml import etree

from epub_translate_cli.infrastructure.epub.xhtml_parser import _skip_reason


def _parse(xml: str) -> etree._Element:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    return etree.fromstring(xml.encode("utf-8"), parser=parser)


def test_translates_links() -> None:
    """Links are now translated — they should NOT be skipped."""
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <a href='x'><p>Translate me</p></a>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) is None


def test_translates_footnotes() -> None:
    """Footnotes are now translated — they should NOT be skipped."""
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <aside role='doc-footnote'><p>Translate this footnote</p></aside>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) is None


def test_skips_code() -> None:
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <pre><p>Do not translate</p></pre>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) == "protected_code"


def test_skips_head_metadata() -> None:
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <head><title><p>Do not translate</p></title></head>
          <body></body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) == "protected_metadata"


def test_skips_inline_code() -> None:
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <p>Use <code>print()</code> function</p>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) == "protected_code"


def test_no_skip_for_plain_paragraph() -> None:
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <p>Just normal text</p>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) is None
