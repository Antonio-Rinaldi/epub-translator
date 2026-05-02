# EPUB Translator CLI — Architecture Document

**Version:** 1.0
**Date:** 2026-05-02
**Status:** Approved for implementation

---

## 1. Current Architecture Overview

The project follows a **hexagonal (ports-and-adapters) architecture** with three declared layers:

```
cli.py  (entry point)
  └── application/services/translation_orchestrator.py
        ├── domain/models.py
        ├── domain/ports.py
        ├── domain/errors.py
        └── infrastructure/  (adapters — DIRECT import, violating the rule below)
              ├── epub/epub_repository.py
              ├── epub/xhtml_parser.py           ← imported directly by orchestrator
              ├── llm/ollama_translator.py
              ├── reporting/chapter_stage_store.py  ← constructed directly by orchestrator
              └── reporting/json_report_writer.py
```

### Current Layer Violations

| Violation | File | Line(s) | Impact |
|-----------|------|---------|--------|
| Application imports infrastructure concretion | `translation_orchestrator.py` | 22–30 | Cannot test orchestrator without real XHTML stack |
| No `ChapterStageStorePort` | `translation_orchestrator.py` | 61–66 | `FilesystemChapterStageStore` constructed directly; no in-memory swap possible |
| No `PromptBuilderPort` | `ollama_translator.py` | 164 | Custom builders cannot be enforced via protocol |
| `EpubBook` lives in `ports.py` | `domain/ports.py` | 43–55 | Domain model placed alongside protocol classes |
| `ChapterTranslationResult` lives in `xhtml_parser.py` | `infrastructure/epub/xhtml_parser.py` | 54–60 | Infrastructure type referenced by application layer |

---

## 2. Proposed Architecture

### 2.1 Dependency Graph (After All Changes)

```
cli.py  (entry point — wires all adapters)
  └── application/services/translation_orchestrator.py
        ├── domain/models.py          (pure data — no deps)
        ├── domain/ports.py           (protocols only — depends on domain/models.py)
        ├── domain/errors.py          (exception hierarchy — no deps)
        └── [no infrastructure imports]

infrastructure/  (depends on domain only, never on application)
  ├── epub/
  │     ├── epub_repository.py        (implements EpubRepositoryPort)
  │     ├── xhtml_parser.py           (implements ChapterProcessorPort; XHTML I/O only)
  │     └── opf_spine_parser.py       (NEW — OPF spine order extraction)
  ├── llm/
  │     ├── ollama_translator.py      (implements TranslatorPort; uses PromptBuilderPort)
  │     └── prompt_builder.py         (NEW — GlossaryAwarePromptBuilder implements PromptBuilderPort)
  ├── reporting/
  │     ├── chapter_stage_store.py    (implements ChapterStageStorePort)
  │     └── json_report_writer.py     (implements ReportWriterPort)
  └── logging/
        └── logger_factory.py
```

The application layer's only external imports after refactoring:

```python
# translation_orchestrator.py — imports after refactoring
from epub_translate_cli.domain.models import (ChapterDocument, RunReport, ...)
from epub_translate_cli.domain.ports import (
    ChapterProcessorPort,      # NEW
    ChapterStageStorePort,     # NEW
    EpubRepositoryPort,
    ReportWriterPort,
    TranslatorPort,
)
from epub_translate_cli.domain.errors import EpubReadError, EpubWriteError
```

---

## 3. Proposed Folder Structure

```
src/epub_translate_cli/
├── __init__.py
├── main.py
├── cli.py
│
├── domain/
│   ├── __init__.py
│   ├── errors.py          # EpubTranslatorError hierarchy (dead aliases removed)
│   ├── models.py          # All pure domain data classes including EpubBook (moved from ports.py)
│   └── ports.py           # Protocol interfaces only:
│                          #   EpubRepositoryPort, TranslatorPort, ReportWriterPort,
│                          #   ChapterStageStorePort (NEW), ChapterProcessorPort (NEW),
│                          #   PromptBuilderPort (NEW), GlossaryPort (NEW)
│
├── application/
│   └── services/
│       └── translation_orchestrator.py  # No direct infrastructure imports
│
└── infrastructure/
    ├── epub/
    │   ├── __init__.py
    │   ├── epub_repository.py    # ZipEpubRepository — reads OPF spine via OPFSpineParser
    │   ├── xhtml_parser.py       # XHTMLTranslator — XHTML I/O only; node loop moves up
    │   └── opf_spine_parser.py   # NEW — OPFSpineParser.ordered_chapter_paths()
    │
    ├── llm/
    │   ├── __init__.py
    │   ├── ollama_translator.py  # OllamaTranslator — /api/chat endpoint
    │   └── prompt_builder.py     # NEW — PromptBuilder, GlossaryAwarePromptBuilder
    │
    ├── reporting/
    │   ├── __init__.py
    │   ├── chapter_stage_store.py   # FilesystemChapterStageStore implements ChapterStageStorePort
    │   └── json_report_writer.py    # JsonReportWriter implements ReportWriterPort
    │
    └── logging/
        ├── __init__.py
        └── logger_factory.py
```

---

## 4. New and Modified Domain Models

### 4.1 `EpubBook` — moved from `ports.py` to `models.py`

**Current location:** `src/epub_translate_cli/domain/ports.py` lines 43–55
**New location:** `src/epub_translate_cli/domain/models.py`

No structural change; purely a move to the correct module. All importers update their import path.

```python
@dataclass(frozen=True)
class EpubBook:
    """In-memory EPUB representation used by the application layer.

    `items` maps internal EPUB path -> raw bytes (all archive members).
    `chapters` is the ordered list of chapter documents (OPF spine order
    after the fix, lexicographic as fallback).
    `compression_types` maps internal EPUB path -> original ZIP compression
    constant (ZIP_STORED or ZIP_DEFLATED) to preserve fidelity on save.
    """
    items: dict[str, bytes]
    chapters: list[ChapterDocument]
    compression_types: dict[str, int]  # NEW field for per-item compression preservation
```

### 4.2 `GlossaryEntry` and `Glossary` — new in `models.py`

```python
@dataclass(frozen=True)
class GlossaryEntry:
    """One term-to-translation mapping for consistent proper noun handling."""
    source_term: str
    target_term: str

@dataclass(frozen=True)
class Glossary:
    """Ordered collection of glossary entries loaded from a flat file."""
    entries: tuple[GlossaryEntry, ...]

    def as_dict(self) -> dict[str, str]:
        """Return entries as source -> target mapping for prompt injection."""
        return {e.source_term: e.target_term for e in self.entries}
```

### 4.3 `TranslationRequest` — simplified

**Current:** `src/epub_translate_cli/domain/models.py` lines 62–73

Remove redundant fields that duplicate `TranslationSettings`. Add `glossary_terms`.

```python
@dataclass(frozen=True)
class TranslationRequest:
    """Input payload passed to translator adapters.

    Settings fields (source_lang, target_lang, model, temperature) are
    intentionally absent — the TranslatorPort implementation reads them
    from the TranslationSettings it was constructed with.
    """
    chapter_context: str
    text: str
    prior_translations: str = ""
    glossary_terms: dict[str, str] = field(default_factory=dict)
```

**Migration impact:** `xhtml_parser.py:_translation_request` (lines 261–276) drops the four settings fields from construction. `PromptBuilder.build()` receives `TranslationRequest` plus a `TranslationSettings` reference (passed at construction time, not per-call).

### 4.4 `ChapterReport` and `RunReport` — frozen

**Current:** `src/epub_translate_cli/domain/models.py` lines 120–153 (mutable `@dataclass`)

Change to `@dataclass(frozen=True)`. Remove the `output_written=False` placeholder pattern:

```python
@dataclass(frozen=True)
class ChapterReport:
    chapter_path: str
    changes: tuple[NodeChange, ...]    # tuple instead of list for hashability
    failures: tuple[NodeFailure, ...]
    skips: tuple[NodeSkip, ...]

@dataclass(frozen=True)
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
    chapters: tuple[ChapterReport, ...]
```

**Migration impact:** `translation_orchestrator.py` line 105 (`report.output_written = output_written`) is replaced by constructing the final `RunReport` once all information is known, eliminating the two-phase construction pattern.

### 4.5 Named Constants — extracted

All magic numbers move to module-level named constants at the top of their respective files:

| Constant | Value | File |
|----------|-------|------|
| `CHAPTER_CONTEXT_MAX_CHARS` | `1500` | `xhtml_parser.py` (replaces `500` at line 174) |
| `REPORT_FIELD_MAX_CHARS` | `200` | `xhtml_parser.py` (replaces `200` at lines 347, 348, 358) |
| `MAX_TRANSLATION_LEN_RATIO` | `3.0` | `ollama_translator.py` (replaces `_MAX_LEN_RATIO` at line 18) |
| `BACKOFF_CAP_SECONDS` | `4.0` | `xhtml_parser.py` (replaces `4.0` at line 409) |
| `CONTEXT_SAMPLE_POINTS` | `3` | `xhtml_parser.py` (new — controls multi-point context extraction) |

---

## 5. New Port Protocols

All four new protocols are added to `src/epub_translate_cli/domain/ports.py`.

### 5.1 `ChapterStageStorePort`

```python
class ChapterStageStorePort(Protocol):
    """Abstraction for chapter translation resume state persistence."""

    def load_completed(self) -> dict[int, StagedChapter]:
        """Return map of zero-based chapter index -> completed staged chapter."""
        ...

    def save_chapter(
        self,
        *,
        chapter_index: int,
        chapter_path: str,
        xhtml_bytes: bytes,
        report: ChapterReport,
    ) -> None:
        """Persist one translated chapter snapshot."""
        ...

    def clear(self) -> None:
        """Remove workspace after successful run."""
        ...
```

`StagedChapter` moves from `chapter_stage_store.py` to `domain/models.py` so that `ChapterStageStorePort` can reference it without importing infrastructure.

### 5.2 `ChapterProcessorPort`

```python
class ChapterProcessorPort(Protocol):
    """Abstraction for translating one chapter document to updated XHTML bytes."""

    def translate_chapter(
        self, chapter: ChapterDocument
    ) -> tuple[bytes, ChapterTranslationResult]:
        """Translate all nodes in one chapter and return updated bytes plus report."""
        ...
```

`ChapterTranslationResult` moves from `xhtml_parser.py` to `domain/models.py`.

### 5.3 `PromptBuilderPort`

```python
class PromptBuilderPort(Protocol):
    """Abstraction for building LLM translation prompts."""

    def build_system_prompt(self, settings: TranslationSettings) -> str:
        """Return the system-role prompt (persona, rules, language instructions)."""
        ...

    def build_user_prompt(self, request: TranslationRequest) -> str:
        """Return the user-role prompt (context block, text to translate)."""
        ...
```

The split into `build_system_prompt` / `build_user_prompt` directly maps to the Ollama `/api/chat` message roles.

### 5.4 `GlossaryPort`

```python
class GlossaryPort(Protocol):
    """Abstraction for loading a terminology glossary from a source."""

    def load(self, path: Path) -> Glossary:
        """Load and parse glossary entries from a flat file (TOML or JSON)."""
        ...
```

---

## 6. Infrastructure Adapter Changes

### 6.1 `OPFSpineParser` — new file `infrastructure/epub/opf_spine_parser.py`

Reads the OPF package document to extract spine reading order.

**Public interface:**

```python
@dataclass(frozen=True)
class OPFSpineParser:
    """Extracts ordered chapter paths from an EPUB OPF package document."""

    @staticmethod
    def find_opf_path(items: dict[str, bytes]) -> str | None:
        """Locate the OPF file path from META-INF/container.xml rootfile element."""
        ...

    @staticmethod
    def ordered_chapter_paths(
        opf_bytes: bytes,
        all_paths: set[str],
    ) -> list[str] | None:
        """Return chapter paths in spine order, or None if OPF is unparseable."""
        ...
```

**Algorithm:**

1. Parse `META-INF/container.xml` to find the `rootfile` `full-path` attribute (the OPF path).
2. Parse the OPF XML; build a manifest dict: `id -> href` from `<manifest><item>` elements.
3. Read `<spine><itemref>` elements in document order; collect `idref` values.
4. Map each `idref` -> manifest `href` -> resolve relative to OPF base path.
5. Filter to paths present in `all_paths` (the archive item keys).
6. Return the ordered list. If any step fails (missing elements, bad XML), return `None`.

`ZipEpubRepository._chapter_documents()` calls `OPFSpineParser` first; falls back to lexicographic sort when `None` is returned.

### 6.2 `OllamaTranslator` — migrate to `/api/chat`

**Current endpoint:** `POST /api/generate` — single `prompt` string.
**New endpoint:** `POST /api/chat` — `messages` array with `role: system` and `role: user`.

```python
# New payload builder
@staticmethod
def _chat_payload(
    request: TranslationRequest,
    settings: TranslationSettings,
    prompt_builder: PromptBuilderPort,
) -> dict[str, object]:
    return {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": prompt_builder.build_system_prompt(settings)},
            {"role": "user",   "content": prompt_builder.build_user_prompt(request)},
        ],
        "stream": False,
        "options": {"temperature": settings.temperature},
    }
```

Response field changes: `/api/chat` returns `message.content` not `response`.

```python
@staticmethod
def _response_text(payload: dict[str, object]) -> str:
    message = payload.get("message")
    if not isinstance(message, dict):
        raise RetryableTranslationError("Missing message field in Ollama chat response")
    raw_text = str(message.get("content") or "").strip()
    if not raw_text:
        raise RetryableTranslationError("Empty content in Ollama chat response")
    return raw_text
```

### 6.3 `GlossaryAwarePromptBuilder` — new in `infrastructure/llm/prompt_builder.py`

Moves `PromptBuilder` out of `ollama_translator.py` into its own module and adds `GlossaryAwarePromptBuilder`:

```python
@dataclass(frozen=True)
class GlossaryAwarePromptBuilder(PromptBuilderPort):
    """Prompt builder that injects a glossary block into the system prompt."""

    def build_system_prompt(self, settings: TranslationSettings) -> str:
        """Builds persona + rules + language rules (same as PromptBuilder)."""
        ...

    def build_user_prompt(self, request: TranslationRequest) -> str:
        """Builds context + glossary block + text to translate."""
        ...

    @staticmethod
    def _glossary_block(glossary_terms: dict[str, str]) -> str:
        """Format glossary as a mandatory term-mapping table."""
        if not glossary_terms:
            return ""
        lines = "\n".join(f"  {src} -> {tgt}" for src, tgt in glossary_terms.items())
        return (
            "MANDATORY TERM TRANSLATIONS (always use these exact translations):\n"
            f"{lines}\n\n"
        )
```

### 6.4 `FilesystemChapterStageStore` — implements `ChapterStageStorePort`

Key changes:

1. Add `workers` to run signature (alongside `model`, `temperature`, etc.) so changing `--workers` invalidates the cached stage.
2. Replace `_serialize_report` / `_deserialize_report` manual field mapping with `dataclasses.asdict` for serialization and a typed reconstruction helper for deserialization.
3. Remove `_SKIP_REASON_MAP` (lines 21–25) — use `cast(SkipReason, ...)` with a validity guard instead.

### 6.5 `ZipEpubRepository` — preserve compression types

```python
@staticmethod
def _read_archive_items(
    input_path: Path,
) -> tuple[dict[str, bytes], dict[str, int]]:
    """Read archive items and record original compression type per member."""
    with zipfile.ZipFile(input_path, "r") as archive:
        items = {}
        compression_types = {}
        for info in archive.infolist():
            items[info.filename] = archive.read(info.filename)
            compression_types[info.filename] = info.compress_type
    return items, compression_types

@staticmethod
def _write_archive_items(book: EpubBook, output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w") as archive:
        if "mimetype" in book.items:
            archive.writestr("mimetype", book.items["mimetype"],
                             compress_type=zipfile.ZIP_STORED)
        for name, content in book.items.items():
            if name == "mimetype":
                continue
            compress = book.compression_types.get(name, zipfile.ZIP_DEFLATED)
            archive.writestr(name, content, compress_type=compress)
```

---

## 7. Application Layer Changes

### 7.1 `TranslationOrchestrator` — inject ports, eliminate direct imports

```python
@dataclass(frozen=True)
class TranslationOrchestrator:
    epub_repository: EpubRepositoryPort
    translator: TranslatorPort
    report_writer: ReportWriterPort
    stage_store: ChapterStageStorePort   # NEW — injected, not constructed internally
    chapter_processor_factory: ...       # produces ChapterProcessorPort instances per-settings
```

The `stage_store` parameter replaces the internal `FilesystemChapterStageStore.for_run(...)` call (lines 61–66). The CLI wires the concrete store.

The direct import of `XHTMLTranslator` (line 22) and `FilesystemChapterStageStore` (lines 27–30) are removed from the orchestrator. The orchestrator only references `ChapterProcessorPort` and `ChapterStageStorePort`.

### 7.2 Remove Two-Phase `RunReport` Construction

Current pattern (lines 88–105):

```python
report = self._build_run_report(..., output_written=False)  # placeholder
output_written, exit_code = self._write_output_if_allowed(...)
report.output_written = output_written  # mutation of frozen-should-be model
```

New pattern after freezing `RunReport`:

```python
output_written, exit_code = self._write_output_if_allowed(...)
report = self._build_run_report(..., output_written=output_written)  # one construction
```

### 7.3 Fix `_ordered_reports` Dead Code

Current (lines 154–160):

```python
missing = sum(1 for report in chapter_reports if report is None)
if missing:
    raise RuntimeError(...)          # never triggered by user input
return [report for report in chapter_reports if report is not None]  # unreachable filter
```

New:

```python
assert all(r is not None for r in chapter_reports), \
    f"Internal error: {sum(1 for r in chapter_reports if r is None)} missing chapter reports"
return [r for r in chapter_reports if r is not None]
```

---

## 8. Architecture Decision Records

### ADR-001: Introduce `ChapterStageStorePort` to Domain

**Status:** Accepted
**Date:** 2026-05-02

**Context:**
`TranslationOrchestrator` constructs `FilesystemChapterStageStore` directly at lines 61–66 of `translation_orchestrator.py`. This embeds a concrete filesystem dependency in the application service, preventing unit tests from running without touching disk and preventing easy swap for an in-memory implementation in tests.

**Decision:**
Define `ChapterStageStorePort` in `domain/ports.py` as a `Protocol` with three methods: `load_completed`, `save_chapter`, and `clear`. The orchestrator accepts the port via constructor injection. `FilesystemChapterStageStore` declares it implements the protocol. The CLI layer wires the concrete implementation.

**Consequences:**
- Positive: Orchestrator can be unit-tested with an in-memory fake that satisfies the protocol.
- Positive: Future alternate stores (e.g., SQLite-backed) require only implementing the protocol.
- Negative: `StagedChapter` must move from `chapter_stage_store.py` to `domain/models.py` so the port protocol can reference it without importing infrastructure. This is a one-time migration.

---

### ADR-002: Migrate `OllamaTranslator` to `/api/chat` Endpoint

**Status:** Accepted
**Date:** 2026-05-02

**Context:**
`OllamaTranslator` currently uses `POST /api/generate` with a single concatenated `prompt` string (lines 167–179 of `ollama_translator.py`). Modern instruction-tuned models (Llama 3, Mistral, Phi-3, Gemma 2) are optimized for the chat format, where persona/rules go in the `system` role and the translatable content goes in the `user` role. The current approach puts both in a single string, which degrades instruction following for these models.

**Decision:**
Switch to `POST /api/chat`. Introduce `PromptBuilderPort` with `build_system_prompt(settings)` and `build_user_prompt(request)`. The system prompt carries: persona declaration, output rules, language-specific orthographic rules. The user prompt carries: chapter context block, glossary block, prior-translations block, and the text to translate.

**Consequences:**
- Positive: Instruction following improves for chat-tuned models.
- Positive: `TranslationRequest` can be simplified — `source_lang`, `target_lang`, `model`, `temperature` are no longer needed per-request since the system prompt is built from `TranslationSettings` once.
- Negative: `/api/generate` callers must update. Response parsing changes from `payload["response"]` to `payload["message"]["content"]`.
- Neutral: `_LEAKED_PROMPT_RE` must be updated to match current prompt marker labels only (removes the Italian-legacy `TESTO DA TRADURRE` / `CONTESTO DEL CAPITOLO` strings).

---

### ADR-003: OPF Spine Reading for Chapter Ordering

**Status:** Accepted
**Date:** 2026-05-02

**Context:**
`ZipEpubRepository._chapter_documents()` (lines 36–45 of `epub_repository.py`) orders chapters by lexicographic sort of their internal ZIP path. The EPUB specification (EPUB 3.3 §3.4.1) mandates that reading order is defined by the `<spine>` element in the OPF package document. Lexicographic order works by coincidence for many test EPUBs but fails for EPUBs generated by Calibre, InDesign, or Adobe Digital Editions, which may use non-sequential filenames or numeric suffixes that do not sort naturally.

**Decision:**
Add `OPFSpineParser` to `infrastructure/epub/opf_spine_parser.py`. Parse `META-INF/container.xml` to locate the OPF file, then parse the OPF `<spine><itemref>` order to derive the correct chapter path sequence. Fall back to lexicographic order when the OPF file is absent or unparseable. No new runtime dependencies — `lxml` is already present.

**Consequences:**
- Positive: Correct reading order for all spec-compliant EPUBs.
- Positive: Rolling context window sees paragraphs in the correct narrative order, improving translation quality.
- Negative: The new code path requires integration testing with a real multi-chapter EPUB to verify spine traversal.
- Neutral: The fallback guarantees backward compatibility with any EPUB that currently works correctly.

---

### ADR-004: Glossary as a Flat-File Domain Concept

**Status:** Accepted
**Date:** 2026-05-02

**Context:**
There is no mechanism for enforcing consistent translation of recurring terms (character names, place names, invented vocabulary). Without a glossary, each paragraph is translated in isolation, and the LLM is free to render proper nouns inconsistently across the novel.

**Decision:**
Add `GlossaryEntry` and `Glossary` domain models to `models.py`. Add `GlossaryPort` to `ports.py` for loading a glossary from a flat file (TOML or JSON). Add `--glossary` flag to the CLI accepting a path to a glossary file. The loaded `Glossary` is converted to `dict[str, str]` and injected into each `TranslationRequest` as `glossary_terms`. `GlossaryAwarePromptBuilder` formats these terms into a mandatory-translation block in the user prompt.

The glossary is flat (no translation memory database, no fuzzy matching), which satisfies the scope constraint in the initiative spec. The `GlossaryPort` protocol allows future alternative loaders (e.g., loading from a TOML file vs. a JSON file) without changing the application layer.

**Consequences:**
- Positive: Character names and terminology stay consistent across all chapters.
- Positive: No new runtime dependencies (standard library `tomllib` / `json` handles parsing).
- Negative: The glossary file must be manually curated by the user.
- Neutral: When no `--glossary` flag is provided, `glossary_terms` defaults to an empty dict and the behavior is identical to the current implementation.

---

### ADR-005: Freeze `RunReport` and `ChapterReport`

**Status:** Accepted
**Date:** 2026-05-02

**Context:**
`RunReport` and `ChapterReport` use mutable `@dataclass` (lines 120–153 of `models.py`), inconsistent with every other domain model in the file which uses `@dataclass(frozen=True)`. The orchestrator exploits this mutability at line 105 (`report.output_written = output_written`) by constructing a report with a placeholder `False` value and patching it after the write attempt. This two-phase construction is error-prone and complicates reasoning about report state.

**Decision:**
Change both dataclasses to `@dataclass(frozen=True)`. Change `changes`, `failures`, and `skips` fields in `ChapterReport` from `list` to `tuple` to maintain hashability. Eliminate the two-phase construction in the orchestrator by determining `output_written` before constructing `RunReport`. `json_report_writer.py` already uses `dataclasses.asdict` which works identically for frozen dataclasses.

**Consequences:**
- Positive: All domain models are consistently immutable.
- Positive: Frozen dataclasses are hashable and safe to use in sets/dicts if needed.
- Positive: Eliminates a class of mutation bugs where report state could be modified after construction.
- Negative: Callers constructing `ChapterReport` must use `tuple(...)` instead of `list(...)`.
- Neutral: `chapter_stage_store.py` serialization/deserialization code already treats these as value objects; the change requires only wrapping list literals in `tuple()`.

---

## 9. Data Flow: Before and After

### 9.1 Current Translation Flow

```
CLI
 └─ orchestrator.translate_epub()
      ├─ ZipEpubRepository.load()           → EpubBook (chapters sorted lexicographically)
      ├─ FilesystemChapterStageStore.for_run()   ← constructed directly (no port)
      ├─ XHTMLTranslator(translator, settings)   ← imported from infrastructure directly
      │    └─ translate_chapter(chapter)
      │         ├─ lxml parse XHTML
      │         ├─ chapter_context = first 500 chars
      │         ├─ for each node:
      │         │    TranslationRequest(source_lang, target_lang, model, temperature, ...)
      │         │    OllamaTranslator.translate(request)
      │         │       └─ POST /api/generate  {"prompt": "<all text concatenated>"}
      │         └─ ChapterTranslationResult
      ├─ RunReport(output_written=False)     ← placeholder
      ├─ ZipEpubRepository.save()
      └─ report.output_written = True        ← post-construction mutation
```

### 9.2 Proposed Translation Flow

```
CLI
 └─ orchestrator.translate_epub()
      ├─ ZipEpubRepository.load()
      │    ├─ OPFSpineParser.ordered_chapter_paths()   → spine-ordered chapter list
      │    └─ EpubBook (chapters in OPF spine order; compression_types preserved)
      ├─ stage_store: ChapterStageStorePort  ← injected by CLI
      ├─ chapter_processor: ChapterProcessorPort  ← injected or created by CLI
      │    └─ XHTMLTranslator(translator, settings)  ← implements ChapterProcessorPort
      │         └─ translate_chapter(chapter)
      │              ├─ lxml parse XHTML  (infrastructure concern, stays here)
      │              ├─ chapter_context = multi-point sample, 1500-char limit
      │              ├─ for each node:
      │              │    TranslationRequest(chapter_context, text, prior_translations,
      │              │                       glossary_terms)  ← no settings fields
      │              │    OllamaTranslator.translate(request, settings)
      │              │       ├─ prompt_builder.build_system_prompt(settings)
      │              │       ├─ prompt_builder.build_user_prompt(request)  ← glossary injected
      │              │       └─ POST /api/chat  {"messages": [system, user]}
      │              └─ ChapterTranslationResult
      ├─ output_written, exit_code = _write_output_if_allowed(...)
      └─ RunReport(output_written=output_written)  ← single construction, no mutation
```

---

## 10. CLI Wiring Changes

`cli.py` gains one new optional parameter and wires two additional port implementations:

```python
# New flag
glossary: Annotated[Path | None, typer.Option("--glossary",
    help="Path to TOML/JSON glossary file for terminology consistency")] = None

# New wiring in _run_translation()
glossary_obj = TomlGlossaryLoader().load(glossary) if glossary else Glossary(entries=())
stage_store = FilesystemChapterStageStore.for_run(
    input_path=command.input_path,
    output_path=command.output_path,
    report_path=command.report_path,
    settings=settings,
)
orchestrator = TranslationOrchestrator(
    epub_repository=ZipEpubRepository(),
    translator=OllamaTranslator(
        base_url=command.ollama_url,
        prompt_builder=GlossaryAwarePromptBuilder(),
        settings=settings,
    ),
    report_writer=JsonReportWriter(),
    stage_store=stage_store,
    glossary=glossary_obj,
)
```

The existing flag names and exit codes are unchanged, preserving backward compatibility.