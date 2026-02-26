from __future__ import annotations

from lxml import etree

from epub_translate_cli.infrastructure.epub.xhtml_parser import _skip_reason


def _parse(xml: str) -> etree._Element:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    return etree.fromstring(xml.encode("utf-8"), parser=parser)


def test_skips_links() -> None:
    root = _parse(
        """<?xml version='1.0' encoding='utf-8'?>
        <html xmlns='http://www.w3.org/1999/xhtml'>
          <body>
            <a href='x'><p>Do not translate</p></a>
          </body>
        </html>"""
    )
    p = root.xpath("//*[local-name()='p']")[0]
    assert _skip_reason(p) == "protected_link"


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
