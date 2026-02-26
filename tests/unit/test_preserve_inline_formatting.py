from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from epub_translate_cli.domain.models import ChapterDocument, TranslationRequest, TranslationResponse, TranslationSettings
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import XHTMLTranslator


@dataclass(frozen=True)
class EchoTranslator(TranslatorPort):
    translated_text: str

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        return TranslationResponse(translated_text=self.translated_text)


_SETTINGS = TranslationSettings(
    source_lang="en",
    target_lang="it",
    model="x",
    temperature=0.2,
    retries=0,
    abort_on_error=False,
)


def _translate_chapter(xhtml: bytes, translated_text: str) -> tuple[bytes, etree._Element]:
    translator = XHTMLTranslator(
        translator=EchoTranslator(translated_text=translated_text),
        settings=_SETTINGS,
    )
    updated, _ = translator.translate_chapter(ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=xhtml))
    root = etree.fromstring(updated, parser=etree.XMLParser(recover=True, resolve_entities=False))
    return updated, root


def test_translate_removes_children_to_avoid_self_closing_tags() -> None:
    """Child elements must be removed after translation to prevent self-closing
    tags like <span/> which HTML-based EPUB readers interpret as unclosed."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p>Hello <span style='font-size:80%'>small</span> world.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Ciao piccolo mondo tradotto.")
    updated_text = updated.decode("utf-8")

    p = root.xpath("//*[local-name()='p']")[0]
    # Children must be removed — no spans left.
    assert len(list(p)) == 0
    assert p.text == "Ciao piccolo mondo tradotto."
    # No self-closing span tags in the output.
    assert "<span/>" not in updated_text
    assert "<span />" not in updated_text


def test_translate_removes_dropcap_span() -> None:
    """A dropcap span must be removed entirely to prevent font-size bleed."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p><span class='dropcap'>A</span> quick brown fox.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Una volpe marrone veloce.")
    updated_text = updated.decode("utf-8")

    p = root.xpath("//*[local-name()='p']")[0]
    assert len(list(p)) == 0
    assert p.text == "Una volpe marrone veloce."
    assert "dropcap" not in updated_text


def test_translate_plain_paragraph_no_children() -> None:
    """A plain paragraph without children should work normally."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p>Hello world.</p>
      </body>
    </html>"""

    _, root = _translate_chapter(xhtml, "Ciao mondo.")

    p = root.xpath("//*[local-name()='p']")[0]
    assert p.text == "Ciao mondo."
    assert len(list(p)) == 0


def test_translate_preserves_paragraph_class() -> None:
    """The paragraph's own class attribute must be preserved after translation."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p class='calibre3'>Some text <em class='calibre1'>with emphasis</em> here.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Del testo con enfasi qui.")
    updated_text = updated.decode("utf-8")

    p = root.xpath("//*[local-name()='p']")[0]
    assert p.get("class") == "calibre3"
    assert p.text == "Del testo con enfasi qui."
    # The em child must be removed.
    assert len(list(p)) == 0


def test_no_self_closing_tags_in_calibre_epub() -> None:
    """Simulate the real sample1.epub structure (cotx + dropcap) and verify
    no self-closing tags appear in the serialized output."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body class='calibre'>
        <p class='ct'>THE NETHERLANDS</p>
        <p class='cotx'><span class='dropcap'>I</span>t is a fact of human nature.</p>
        <p class='calibre3'>Next paragraph here.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Tradotto.")
    updated_text = updated.decode("utf-8")

    # No self-closing tags anywhere.
    assert "<span/>" not in updated_text
    assert "<span />" not in updated_text
    assert "<em/>" not in updated_text
    assert "<a/>" not in updated_text

    # All paragraph classes preserved.
    paras = root.xpath("//*[local-name()='p']")
    classes = [p.get("class") for p in paras]
    assert "ct" in classes
    assert "cotx" in classes
    assert "calibre3" in classes
