from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class TranslationSettings:
    source_lang: str
    target_lang: str
    model: str
    temperature: float
    retries: int
    abort_on_error: bool


@dataclass(frozen=True)
class ParagraphNodeRef:
    """A reference to a paragraph-ish node in a chapter.

    `node_path` is a stable-ish XPath-like string produced by the parser.
    """

    chapter_path: str
    node_path: str
    text: str


@dataclass(frozen=True)
class ChapterDocument:
    path: str
    xhtml_bytes: bytes


@dataclass(frozen=True)
class TranslationRequest:
    source_lang: str
    target_lang: str
    model: str
    temperature: float
    chapter_context: str
    text: str


@dataclass(frozen=True)
class TranslationResponse:
    translated_text: str


SkipReason = Literal[
    "protected_link",
    "protected_code",
    "protected_footnote",
    "protected_metadata",
    "empty",
]


@dataclass(frozen=True)
class NodeChange:
    chapter_path: str
    node_path: str
    before: str
    after: str


@dataclass(frozen=True)
class NodeFailure:
    chapter_path: str
    node_path: str
    text: str
    error_type: str
    message: str
    attempts: int


@dataclass(frozen=True)
class NodeSkip:
    chapter_path: str
    node_path: str
    reason: SkipReason


@dataclass
class ChapterReport:
    chapter_path: str
    changes: list[NodeChange]
    failures: list[NodeFailure]
    skips: list[NodeSkip]


@dataclass
class RunReport:
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
    chapters: list[ChapterReport]

    def totals(self) -> dict[str, Any]:
        return {
            "chapters": len(self.chapters),
            "changed": sum(len(c.changes) for c in self.chapters),
            "failed": sum(len(c.failures) for c in self.chapters),
            "skipped": sum(len(c.skips) for c in self.chapters),
        }


@dataclass(frozen=True)
class TranslationRunResult:
    output_written: bool
    failures: int
    exit_code: int
