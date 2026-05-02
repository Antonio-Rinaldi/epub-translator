from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TranslatableTag = Literal["p", "h1", "h2", "h3", "h4", "h5", "h6"]
DEFAULT_TRANSLATABLE_TAGS: tuple[TranslatableTag, ...] = (
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
)


@dataclass(frozen=True)
class TranslationSettings:
    """Runtime settings controlling translation behavior for one run."""

    source_lang: str
    target_lang: str
    model: str
    temperature: float
    retries: int
    abort_on_error: bool
    workers: int = 1
    context_paragraphs: int = 3


@dataclass(frozen=True)
class ChapterDocument:
    """Chapter XHTML resource extracted from the EPUB archive."""

    path: str
    xhtml_bytes: bytes


@dataclass(frozen=True)
class EpubBook:
    """In-memory EPUB representation used by the application layer.

    `items` maps internal EPUB path -> bytes content.
    `chapters` contains parsed XHTML chapters derived from items.
    `compression_types` maps each path to its original ZIP compression constant.

    Keeping all three allows faithful round-trip with minimal loss.
    """

    items: dict[str, bytes]
    chapters: list[ChapterDocument]
    compression_types: dict[str, int]


@dataclass(frozen=True)
class GlossaryEntry:
    """One term→translation pair in a user-supplied glossary."""

    term: str
    translation: str


@dataclass(frozen=True)
class Glossary:
    """Collection of glossary entries loaded from a flat file."""

    entries: tuple[GlossaryEntry, ...]

    def as_dict(self) -> dict[str, str]:
        """Return entries as a plain term→translation mapping."""
        return {entry.term: entry.translation for entry in self.entries}


@dataclass(frozen=True)
class TranslatableNode:
    """Resolved translatable node payload used by chapter parser pipeline."""

    chapter_path: str
    node_path: str
    tag: TranslatableTag
    source_text: str


@dataclass(frozen=True)
class TranslationRequest:
    """Input payload passed to translator adapters.

    Contains only per-node content fields. Settings fields (source_lang, target_lang,
    model, temperature) are held by the translator and not duplicated here.
    """

    chapter_context: str
    text: str
    prior_translations: str = ""
    glossary_terms: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TranslationResponse:
    """Output payload returned by translator adapters."""

    translated_text: str


SkipReason = Literal[
    "protected_code",
    "protected_metadata",
    "empty",
]


@dataclass(frozen=True)
class NodeChange:
    """One successfully translated node diff entry for reporting."""

    chapter_path: str
    node_path: str
    before: str
    after: str


@dataclass(frozen=True)
class NodeFailure:
    """One failed node translation entry for reporting."""

    chapter_path: str
    node_path: str
    text: str
    error_type: str
    message: str
    attempts: int


@dataclass(frozen=True)
class NodeSkip:
    """One skipped node entry describing why translation was not attempted."""

    chapter_path: str
    node_path: str
    reason: SkipReason


@dataclass(frozen=True)
class ChapterTranslationResult:
    """Per-chapter translation processing report produced by ChapterProcessorPort."""

    changes: list[NodeChange]
    failures: list[NodeFailure]
    skips: list[NodeSkip]


@dataclass(frozen=True)
class ChapterReport:
    """Per-chapter report section used in final run report."""

    chapter_path: str
    changes: tuple[NodeChange, ...]
    failures: tuple[NodeFailure, ...]
    skips: tuple[NodeSkip, ...]


@dataclass(frozen=True)
class StagedChapter:
    """Chapter bytes/report snapshot loaded from persistent staging workspace."""

    chapter_index: int
    chapter_path: str
    xhtml_bytes: bytes
    report: ChapterReport
    completed: bool


@dataclass(frozen=True)
class RunReport:
    """Aggregate translation report serialized after each run."""

    input_path: str
    output_path: str
    report_path: str
    model: str
    source_lang: str
    target_lang: str
    temperature: float
    retries: int
    abort_on_error: bool
    output_written: bool
    chapters: tuple[ChapterReport, ...]

    def totals(self) -> dict[str, Any]:
        """Compute aggregate counters across all chapter report sections."""
        return {
            "chapters": len(self.chapters),
            "changed": sum(len(c.changes) for c in self.chapters),
            "failed": sum(len(c.failures) for c in self.chapters),
            "skipped": sum(len(c.skips) for c in self.chapters),
        }


@dataclass(frozen=True)
class TranslationRunResult:
    """Result envelope returned by the orchestrator to CLI layer."""

    output_written: bool
    failures: int
    exit_code: int
