from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from epub_translate_cli.application.services.chapter_translator import ChapterTranslator
from epub_translate_cli.domain.models import (
    ChapterDocument,
    TranslationRequest,
    TranslationResponse,
    TranslationSettings,
)
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import (
    XHTMLTranslator,
    collect_text_slots,
    distribute_text,
    nearest_word_boundary,
)


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


def _xpath_first(root: etree._Element, query: str) -> etree._Element:
    """Return first element for XPath query with runtime guards for strict typing."""
    matches = root.xpath(query)
    assert isinstance(matches, list) and matches
    first = matches[0]
    assert isinstance(first, etree._Element)
    return first


def _xpath_elements(root: etree._Element, query: str) -> list[etree._Element]:
    """Return element-only XPath results."""
    matches = root.xpath(query)
    assert isinstance(matches, list)
    elements = [node for node in matches if isinstance(node, etree._Element)]
    assert elements
    return elements


def _itertext_str(element: etree._Element) -> str:
    """Collapse itertext output to text-only content."""
    return "".join(chunk for chunk in element.itertext() if isinstance(chunk, str)).strip()


def _translate_chapter(xhtml: bytes, translated_text: str) -> tuple[bytes, etree._Element]:
    processor = ChapterTranslator(
        translator=EchoTranslator(translated_text=translated_text),
        settings=_SETTINGS,
        xhtml_parser=XHTMLTranslator(),
    )
    updated, _ = processor.translate_chapter(
        ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=xhtml)
    )
    root = etree.fromstring(updated, parser=etree.XMLParser(recover=True, resolve_entities=False))
    return updated, root


# ---------------------------------------------------------------------------
# Unit tests for slot helpers (public API)
# ---------------------------------------------------------------------------


def test_collect_text_slots_plain_paragraph() -> None:
    """Plain paragraph – only elem.text slot."""
    xhtml = b"<p>Hello world.</p>"
    elem = etree.fromstring(xhtml)
    slots = collect_text_slots(elem)
    assert slots == [(elem, "text")]


def test_collect_text_slots_dropcap() -> None:
    """Dropcap paragraph has span.text and span.tail slots."""
    xhtml = b"<p><span>I</span>t is a fact.</p>"
    elem = etree.fromstring(xhtml)
    span = list(elem)[0]
    slots = collect_text_slots(elem)
    assert (span, "text") in slots
    assert (span, "tail") in slots


def test_collect_text_slots_mixed() -> None:
    """p with direct text, then inline child, includes all non-empty slots."""
    xhtml = b"<p>Lead <em>italic</em> tail text.</p>"
    elem = etree.fromstring(xhtml)
    em = list(elem)[0]
    slots = collect_text_slots(elem)
    owners = [o for o, _ in slots]
    assert elem in owners  # p.text = "Lead "
    assert em in owners  # em.text = "italic", em.tail = " tail text."


def test_distribute_text_single_slot() -> None:
    assert distribute_text("Ciao mondo.", [11]) == ["Ciao mondo."]


def test_distribute_text_two_equal_slots() -> None:
    translated = "Hello world"
    chunks = distribute_text(translated, [5, 6])
    assert len(chunks) == 2
    assert "".join(chunks) == translated


def test_distribute_text_proportional() -> None:
    """1-char slot (dropcap 'I') and 30-char slot → first chunk should be 1 char."""
    translated = "È un fatto della natura umana."
    chunks = distribute_text(translated, [1, 30])
    assert len(chunks) == 2
    combined = chunks[0] + chunks[1]
    assert combined.replace("  ", " ") == translated or "".join(chunks) == translated


def test_distribute_text_dropcap_first_char() -> None:
    """Dropcap slot (length 1) receives exactly the first character."""
    assert distribute_text("Hello world", [1, 10]) == ["H", "ello world"]
    assert distribute_text("Ciao mondo", [1, 20]) == ["C", "iao mondo"]


def test_nearest_word_boundary_at_space() -> None:
    """Ideal split is already at a space – returns that position."""
    text = "Hello world"
    result = nearest_word_boundary(text, 5)
    assert result == 5


def test_nearest_word_boundary_mid_word_prefers_forward() -> None:
    """Mid-word split should choose the end of the word (forward)."""
    text = "Hello world"
    result = nearest_word_boundary(text, 3)
    assert result == 5


def test_nearest_word_boundary_at_end() -> None:
    result = nearest_word_boundary("Hello", 10)
    assert result == 5  # clamped to len


# ---------------------------------------------------------------------------
# Integration tests via _translate_chapter
# ---------------------------------------------------------------------------


def test_no_self_closing_tags_dropcap() -> None:
    """Dropcap span must not produce a self-closing tag."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p class='cotx'><span class='dropcap'>I</span>t is a fact of human nature.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "È un fatto della natura umana.")
    updated_text = updated.decode("utf-8")

    assert "<span/>" not in updated_text
    assert "<span />" not in updated_text

    p = _xpath_first(root, "//*[local-name()='p']")
    children = list(p)
    assert len(children) == 1
    assert children[0].get("class") == "dropcap"


def test_translate_plain_paragraph_no_children() -> None:
    """A plain paragraph without children should work normally."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p>Hello world.</p>
      </body>
    </html>"""

    _, root = _translate_chapter(xhtml, "Ciao mondo.")

    p = _xpath_first(root, "//*[local-name()='p']")
    assert p.text == "Ciao mondo."
    assert len(list(p)) == 0


def test_translate_preserves_paragraph_class() -> None:
    """The paragraph's own class attribute must survive translation."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p class='calibre3'>Some text <em class='calibre1'>with emphasis</em> here.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Del testo con enfasi qui.")

    p = _xpath_first(root, "//*[local-name()='p']")
    assert p.get("class") == "calibre3"
    children = list(p)
    assert len(children) == 1
    assert children[0].get("class") == "calibre1"


def test_no_self_closing_tags_in_calibre_epub() -> None:
    """Full chapter structure: no self-closing inline tags in serialized output."""
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

    assert "<span/>" not in updated_text
    assert "<span />" not in updated_text
    assert "<em/>" not in updated_text
    assert "<a/>" not in updated_text

    paras = _xpath_elements(root, "//*[local-name()='p']")
    classes = [p.get("class") for p in paras]
    assert "ct" in classes
    assert "cotx" in classes
    assert "calibre3" in classes


def test_full_text_preserved_across_slots() -> None:
    """Concatenating all text slots should equal the full translated string."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p class='cotx'><span class='dropcap'>I</span>t is a fact of human nature.</p>
      </body>
    </html>"""

    translated = "È un fatto della natura umana."
    updated, root = _translate_chapter(xhtml, translated)

    p = _xpath_first(root, "//*[local-name()='p']")
    full = _itertext_str(p)
    assert full == translated


def test_non_xml_named_entity_is_normalized() -> None:
    """Named HTML entities like &mdash; must not leak into XML output."""
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <p>Hello &mdash; world.</p>
      </body>
    </html>"""

    updated, root = _translate_chapter(xhtml, "Ciao mondo.")
    updated_text = updated.decode("utf-8")

    assert "&mdash;" not in updated_text
    etree.fromstring(updated, parser=etree.XMLParser(recover=False, resolve_entities=False))

    p = _xpath_first(root, "//*[local-name()='p']")
    assert "Ciao" in _itertext_str(p)


def test_translates_heading_tags_not_only_paragraphs() -> None:
    xhtml = b"""<?xml version='1.0' encoding='utf-8'?>
    <html xmlns='http://www.w3.org/1999/xhtml'>
      <body>
        <h1><span>THE NETHERLANDS</span></h1>
      </body>
    </html>"""

    _, root = _translate_chapter(xhtml, "I PAESI BASSI")

    heading = _xpath_first(root, "//*[local-name()='h1']")
    assert _itertext_str(heading) == "I PAESI BASSI"
