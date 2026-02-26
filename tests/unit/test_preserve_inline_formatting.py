from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from epub_translate_cli.domain.models import ChapterDocument, TranslationRequest, TranslationResponse, TranslationSettings
from epub_translate_cli.domain.ports import TranslatorPort
from epub_translate_cli.infrastructure.epub.xhtml_parser import (
    XHTMLTranslator,
    _collect_text_slots,
    _distribute_text,
    _nearest_word_boundary,
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


def _translate_chapter(xhtml: bytes, translated_text: str) -> tuple[bytes, etree._Element]:
    translator = XHTMLTranslator(
        translator=EchoTranslator(translated_text=translated_text),
        settings=_SETTINGS,
    )
    updated, _ = translator.translate_chapter(ChapterDocument(path="OEBPS/ch1.xhtml", xhtml_bytes=xhtml))
    root = etree.fromstring(updated, parser=etree.XMLParser(recover=True, resolve_entities=False))
    return updated, root


# ---------------------------------------------------------------------------
# Unit tests for slot helpers
# ---------------------------------------------------------------------------

def test_collect_text_slots_plain_paragraph() -> None:
    """Plain paragraph – only elem.text slot."""
    xhtml = b"<p>Hello world.</p>"
    elem = etree.fromstring(xhtml)
    slots = _collect_text_slots(elem)
    assert slots == [(elem, "text")]


def test_collect_text_slots_dropcap() -> None:
    """Dropcap paragraph has span.text and span.tail slots."""
    xhtml = b"<p><span>I</span>t is a fact.</p>"
    elem = etree.fromstring(xhtml)
    span = list(elem)[0]
    slots = _collect_text_slots(elem)
    # elem.text is None/empty so NOT included; span.text and span.tail are.
    assert (span, "text") in slots
    assert (span, "tail") in slots


def test_collect_text_slots_mixed() -> None:
    """p with direct text, then inline child, includes all non-empty slots."""
    xhtml = b"<p>Lead <em>italic</em> tail text.</p>"
    elem = etree.fromstring(xhtml)
    em = list(elem)[0]
    slots = _collect_text_slots(elem)
    owners = [o for o, _ in slots]
    assert elem in owners       # p.text = "Lead "
    assert em in owners         # em.text = "italic", em.tail = " tail text."


def test_distribute_text_single_slot() -> None:
    assert _distribute_text("Ciao mondo.", [11]) == ["Ciao mondo."]


def test_distribute_text_two_equal_slots() -> None:
    translated = "Hello world"
    chunks = _distribute_text(translated, [5, 6])  # roughly equal
    assert len(chunks) == 2
    assert "".join(chunks) == translated


def test_distribute_text_proportional() -> None:
    """1-char slot (dropcap 'I') and 30-char slot → first chunk should be 1 char."""
    translated = "È un fatto della natura umana."
    # Original: "I" (1 char) + "t is a fact of human nature." (30 chars)
    chunks = _distribute_text(translated, [1, 30])
    assert len(chunks) == 2
    # Combined text equals the full translation.
    combined = chunks[0] + chunks[1]
    assert combined.replace("  ", " ") == translated or "".join(chunks) == translated


def test_nearest_word_boundary_at_space() -> None:
    """Ideal split is already at a space – returns that position."""
    text = "Hello world"
    # pos=5 is a space → nearest boundary is 5 itself (forward scan hits 5).
    result = _nearest_word_boundary(text, 5)
    assert result == 5


def test_nearest_word_boundary_mid_word_prefers_forward() -> None:
    """Mid-word split should choose the end of the word (forward)."""
    text = "Hello world"
    # pos=3 ('lo') – forward to space at 5 (dist=2), backward to start at 0 (dist=3)
    result = _nearest_word_boundary(text, 3)
    assert result == 5


def test_nearest_word_boundary_at_end() -> None:
    result = _nearest_word_boundary("Hello", 10)
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

    p = root.xpath("//*[local-name()='p']")[0]
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

    p = root.xpath("//*[local-name()='p']")[0]
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

    p = root.xpath("//*[local-name()='p']")[0]
    assert p.get("class") == "calibre3"
    # em child must still be present with its class.
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

    paras = root.xpath("//*[local-name()='p']")
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

    p = root.xpath("//*[local-name()='p']")[0]
    # Reconstruct all text from the paragraph using itertext.
    full = "".join(t for t in p.itertext()).strip()
    assert full == translated
