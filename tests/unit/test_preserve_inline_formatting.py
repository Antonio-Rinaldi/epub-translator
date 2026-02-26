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


def test_translate_preserves_child_elements_and_attributes() -> None:
    """Child elements (spans with style/class) must stay in the DOM after translation."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p>Hello <span style='font-size:80%'>small</span> world.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Ciao piccolo mondo tradotto.")

    updated_text = updated.decode("utf-8")
    # The span element and its style attribute must still be present.
    assert "font-size:80%" in updated_text
    assert "<span" in updated_text

    p = root.xpath("//*[local-name()='p']")[0]
    rendered = "".join(p.itertext())
    assert rendered == "Ciao piccolo mondo tradotto."


def test_translate_does_not_inflate_dropcap() -> None:
    """A dropcap span must remain in the DOM but not absorb translated text."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p><span class='dropcap'>A</span> quick brown fox jumps over the lazy dog.</p>
      </body>
    </html>"""

    _, root = _translate_chapter(xhtml, "Un testo tradotto molto piu lungo della versione originale.")

    span = root.xpath("//*[local-name()='span']")[0]
    p = root.xpath("//*[local-name()='p']")[0]

    # The dropcap span must still exist with its class.
    assert span.get("class") == "dropcap"

    # The span text must be empty (cleared) — all translated text is in elem.text.
    assert (span.text or "") == ""

    # Full paragraph text must still equal the translation.
    rendered = "".join(p.itertext())
    assert rendered == "Un testo tradotto molto piu lungo della versione originale."


def test_translate_preserves_multiple_styled_children() -> None:
    """Multiple children with different styles must all be preserved in the DOM."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p><span class='title-big'>Chapter One:</span> <em>The Beginning</em> of something great.</p>
      </body>
    </html>"""

    _, root = _translate_chapter(xhtml, "Capitolo Uno: L'Inizio di qualcosa di grande.")

    updated_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

    # Both child elements must survive.
    assert "title-big" in updated_bytes
    assert "<em" in updated_bytes

    p = root.xpath("//*[local-name()='p']")[0]
    rendered = "".join(p.itertext())
    assert rendered == "Capitolo Uno: L'Inizio di qualcosa di grande."


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
    assert len(list(p)) == 0  # no children
