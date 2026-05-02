# EPUB Translator CLI — Enhancement Initiative Specification

**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** Approved for development  

---

## 1. Executive Summary

`epub-translator-cli` is a production-quality CLI tool that translates EPUB books paragraph-by-paragraph using a local Ollama LLM. The codebase has a sound hexagonal architecture and a passing test suite. This document specifies a targeted quality-uplift initiative covering five distinct problem areas discovered through deep code review:

1. **Code quality and SOLID principle adherence** — several boundary violations and structural issues that increase coupling and reduce testability.
2. **Architecture improvements** — infrastructure concerns leaking into the application layer, missing ports for swappable components, and fragile algorithms.
3. **Translation quality** — prompt engineering gaps, context-window strategy limitations, missing glossary/terminology consistency, and Italian-specific orthographic issues.
4. **EPUB specification compliance** — chapter ordering is lexicographic rather than OPF-spine-ordered, which produces incorrect reading order for many real-world EPUBs.
5. **Testing and CI infrastructure** — only unit tests exist; no integration tests, no contract tests, no CI pipeline.

---

## 2. Scope

### In Scope

- Refactoring and new code within the `epub-translator-cli` Python package.
- New domain models, ports, and infrastructure adapters.
- New test coverage (unit, integration, contract).
- CI pipeline configuration (GitHub Actions).
- Prompt engineering improvements (no external API changes required).
- EPUB OPF spine parsing (no new external dependencies beyond `lxml` already present).

### Out of Scope

- Switching to a different LLM runtime (OpenAI, Anthropic, etc.) — ports support this but it is not the focus.
- GUI or web interface.
- Translation memory storage in a database (flat-file glossary is in scope; database persistence is not).
- Support for PDF or other non-EPUB formats.

---

## 3. Problem Statement and Findings

### 3.1 Code Quality Issues

#### 3.1.1 Layer Boundary Violation — `XHTMLTranslator` in Infrastructure

**File:** `src/epub_translate_cli/infrastructure/epub/xhtml_parser.py`  
**Lines:** 148–365 (`XHTMLTranslator` class)

`XHTMLTranslator` is responsible for:
- Parsing XHTML (infrastructure concern — correct)
- Orchestrating per-node translation loops with retry logic (application concern — wrong layer)
- Maintaining rolling context across nodes (application concern — wrong layer)
- Building `ChapterTranslationResult` report structures (application concern — wrong layer)

The orchestrator (`translation_orchestrator.py` line 23) directly imports `XHTMLTranslator` from infrastructure, violating the dependency rule: application layer must only depend on domain and ports, never on infrastructure concretions.

**Consequence:** Testing the orchestrator requires instantiating the full XHTML parsing stack. Adding an alternative chapter processor (e.g., one that handles plain HTML differently) requires modifying the application layer import.

#### 3.1.2 `FilesystemChapterStageStore` Is Not Behind a Port

**File:** `src/epub_translate_cli/application/services/translation_orchestrator.py`  
**Lines:** 61–66, 170–176

The orchestrator constructs `FilesystemChapterStageStore` directly by calling `FilesystemChapterStageStore.for_run(...)`. This is a concrete filesystem dependency embedded in the application service — a direct dependency inversion violation. There is no `ChapterStageStorePort` protocol defined in `domain/ports.py`.

**Consequence:** The orchestrator cannot be unit-tested without touching the filesystem. Swapping for an in-memory store (needed for fast unit tests) requires patching.

#### 3.1.3 `PromptBuilder` Is Not Injectable

**File:** `src/epub_translate_cli/infrastructure/llm/ollama_translator.py`  
**Lines:** 94–155, 163–165

`PromptBuilder` is a concrete dataclass hardcoded as the default value for `OllamaTranslator.prompt_builder`. While it is technically injectable (the field is a public slot), there is no `PromptBuilderPort` protocol, no documentation that it is an extension point, and nothing enforces the interface contract for custom prompt builders.

**Consequence:** Custom prompt strategies (e.g., a glossary-aware builder) cannot be swapped without subclassing or monkey-patching.

#### 3.1.4 Serialization/Deserialization Duplication

**Files:** `chapter_stage_store.py` lines 238–327

The `_serialize_report` and `_deserialize_report` methods in `FilesystemChapterStageStore` duplicate the exact same field mappings as `dataclasses.asdict(report)` already used in `json_report_writer.py` (line 22). All `NodeChange`, `NodeFailure`, and `NodeSkip` field names are serialized manually (12 string literals) rather than leveraging `dataclasses.asdict`.

`_SKIP_REASON_MAP` (line 21–25) maps a string to itself for all three valid values — this is dead identity mapping that serves no normalization purpose.

#### 3.1.5 Magic Constants

The following magic numbers and strings appear without named constants:

| Location | Value | Issue |
|---|---|---|
| `xhtml_parser.py:174` | `500` | Chapter context character limit — unnamed |
| `xhtml_parser.py:347,348,358` | `200` | Report field truncation limit — unnamed |
| `ollama_translator.py:18` | `3.0` | Max length ratio for leak detection — unnamed |
| `ollama_translator.py:409` | `4.0` | Backoff cap in seconds — unnamed |
| `xhtml_parser.py:406-408` | `0.25 * (2**attempt)` | Backoff formula duplicated from domain logic |

#### 3.1.6 `RunReport` Is a Mutable Dataclass

**File:** `src/epub_translate_cli/domain/models.py` lines 120–153

`RunReport` and `ChapterReport` use `@dataclass` (mutable) while all other domain models use `@dataclass(frozen=True)`. The orchestrator mutates `report.output_written` at line 105 of `translation_orchestrator.py` after building the report. This mutability is unintentional — the report is constructed with a placeholder `output_written=False` then patched. This pattern breaks immutability expectations and complicates reasoning.

#### 3.1.7 `_ordered_reports` Raises `RuntimeError` for Internal Invariant

**File:** `translation_orchestrator.py` lines 155–160

`_ordered_reports` raises `RuntimeError` if any `None` entries remain in the reports list. This is an internal invariant that can never be violated by user input — it is a programmer error. Using `RuntimeError` conflates internal bugs with domain errors. Additionally, the method contains dead-code: the `if item is not None` filter on line 160 is unreachable (line 157 would have already raised). This should either be an `assert` or the `list` comprehension should be simplified.

#### 3.1.8 `EpubBook` Is Defined in `ports.py`, Not `models.py`

**File:** `src/epub_translate_cli/domain/ports.py` lines 43–55

`EpubBook` is a domain data class, not a port protocol. Its presence in `ports.py` alongside protocol classes is architecturally inconsistent. Domain model classes belong in `models.py`.

#### 3.1.9 `EpubTranslateError` Backward-Compatible Alias Is Dead Code

**File:** `src/epub_translate_cli/domain/errors.py` lines 8–9

`EpubTranslateError = EpubTranslatorError` exists as a "backward-compatible alias." However, there is only one caller codebase (this package), and a grep reveals zero usages of `EpubTranslateError`. This is dead code that adds noise without value.

#### 3.1.10 `ValidationError` Is Defined but Never Raised

**File:** `src/epub_translate_cli/domain/errors.py` line 12

`ValidationError` exists in the error hierarchy but is never raised by any code in the package. All CLI input validation uses `_abort()` which raises `typer.Exit` directly. Either the error should be used or removed.

### 3.2 Translation Quality Issues

#### 3.2.1 Chapter Context Is Truncated to 500 Characters

**File:** `xhtml_parser.py` line 174

The chapter context passed to every translation request is capped at 500 characters — barely enough for 3–5 sentences. For a typical novel chapter, this captures only the opening lines and misses: character relationships introduced later, the chapter's dominant tone, cultural references, and recurring terminology. This context is used for "tone/terminology guidance" but is too thin to be effective.

A smarter strategy would extract a representative sample (e.g., first paragraph + middle paragraph + last paragraph) capped at a larger limit such as 1500–2000 characters, or pass a book-level synopsis rather than chapter-level text.

#### 3.2.2 Rolling Context Carries Translated Text, Not Source-Target Pairs

**File:** `xhtml_parser.py` lines 254–259

The `_prior_translations` window contains only the translated text of the previous N paragraphs. The LLM has no visibility into what source text those translations correspond to. For terminology consistency, showing the LLM source→target pairs (e.g., "Original: 'D' was moving silently through the darkness. Translation: 'D' si muoveva silenziosamente nell'oscurità.") would be significantly more effective for maintaining terminology consistency for character names, place names, and recurring phrases.

#### 3.2.3 No Glossary / Terminology Consistency Mechanism

There is no mechanism for forcing consistent translation of recurring terms: character names, place names, titles, invented words. For a novel like Vampire Hunter D, character names like "D", "Doris", "Magnus Lee" must remain consistent. Without a glossary, each paragraph is translated in isolation and the LLM is free to render proper names inconsistently.

The prompt carries language-specific rules (e.g., Italian accent rules) but has no slot for "these terms must be preserved as-is or mapped to these specific translations."

#### 3.2.4 `_sanitise_response` Contains Italian-Specific Prompt Markers

**File:** `ollama_translator.py` lines 23–27

The `_LEAKED_PROMPT_RE` regex matches `TESTO DA TRADURRE` and `CONTESTO DEL CAPITOLO` — Italian-language echoes of the English prompt labels. These Italian strings arise only because previous versions of the prompt used Italian labels. The current prompt uses English labels only (`TEXT TO TRANSLATE`, `CHAPTER CONTEXT`). This is a language-specific hardcoding that does not generalize cleanly to other translation directions and couples the response sanitizer to a specific historical prompt phrasing.

The comment says "known prompt marker" but the markers come from two different versions of the system. The regex should either be fully parameterized or scoped to the actual current prompt markers only.

#### 3.2.5 No Post-Translation Validation

After sanitization, there is no check for:
- **Untranslated text detection**: detecting if the output still contains substantial source-language text.
- **HTML injection**: checking if the model injected markup tags into the plain-text translation.
- **Numeric/proper noun preservation**: verifying that numbers and known proper nouns survived the translation.
- **Empty output detection after strip**: `_sanitise_response` returns the stripped text but does not raise if the result is empty — an empty translated text will silently replace the source paragraph.

#### 3.2.6 Length Ratio Check Warns but Does Not Retry

**File:** `ollama_translator.py` lines 267–274

When the translated text is more than 3× the source length, a warning is logged but the result is returned unchanged. This should trigger a retry with an explicit prompt constraint.

#### 3.2.7 Prompt Length Guidance Is Vague

**File:** `ollama_translator.py` line 149

The prompt rule states "The translated text must have roughly the same length as the original." This is a weak constraint. Italian translations of English prose are typically 5–15% longer, and the model should be guided on realistic expansion expectations rather than being asked to match the source character-for-character, which can cause compression artifacts.

#### 3.2.8 No System Prompt Separation

The entire prompt is a single user-turn string. Modern LLM APIs (and Ollama's `/api/chat` endpoint) support a separate `system` role message. Moving the persona and rules to a `system` role and the translatable text to a `user` role would improve response quality for models that are instruction-tuned for chat-style prompting.

### 3.3 Architecture Issues

#### 3.3.1 No EPUB OPF Spine Reading

**File:** `epub_repository.py` lines 36–45

Chapter ordering is determined by `sorted(..., key=lambda doc: doc.path)` — lexicographic sorting on the internal EPUB path. The EPUB specification mandates that reading order is defined by the `<spine>` element in the OPF package document (`content.opf`). Lexicographic order is often wrong:

- Chapters named `ch01.xhtml`, `ch02.xhtml`, ... happen to sort correctly.
- Chapters named `GeographyofBli_body_split_000.html` ... sort correctly by coincidence.
- Chapters in the test resources are named with numeric suffixes and also sort correctly.
- But EPUBs generated by Calibre, Adobe Digital Editions, or InDesign may have non-sequential filenames (e.g., `part-i-chapter-3.xhtml` before `part-i-chapter-1.xhtml`), causing out-of-order translation and incorrect rolling context.

The OPF file is already loaded into `items` dict — parsing it requires only XPath on the already-available bytes.

#### 3.3.2 `_distribute_text` Algorithm Is Fragile

**File:** `xhtml_parser.py` lines 97–125

The proportional distribution algorithm splits translated text based on the character-length ratios of the original source slots. This is fragile because:
1. Italian translations of English prose can be 10–20% longer per slot, causing the last slot to absorb disproportionate content.
2. For dropcap paragraphs (a 1-character `<span>` followed by the rest of the paragraph), a 1:30 ratio will try to assign 1 character to the dropcap slot. Italian translations may not cleanly produce a single-character first token.
3. The word-boundary search `_nearest_word_boundary` scans character-by-character but does not handle Unicode word boundaries (e.g., it treats CJK ideographs as non-space characters).

A better strategy for most inline cases is to assign the dropcap slot its first "grapheme cluster" (single character) and give the remainder to the tail, rather than using character-length proportions.

#### 3.3.3 Stage Store Signature Does Not Include `workers` Count

**File:** `chapter_stage_store.py` lines 62–76

The run signature used to validate resume compatibility includes model, temperature, retries, and context_paragraphs — but not `workers`. Changing `--workers` between a partial run and its resume does not invalidate the stage. This is not a correctness issue (the staged chapter content is independent of workers), but it does mean two runs with different worker counts can share the same staging workspace, which may produce unexpected behavior when debugging parallel processing issues.

#### 3.3.4 ZIP Compression Is Always `ZIP_DEFLATED` for All Non-Mimetype Items

**File:** `epub_repository.py` line 61

The original EPUB archive may have stored some items as `ZIP_STORED` (uncompressed) — e.g., pre-compressed image formats (JPEG, PNG) that do not benefit from deflate. The current save code applies `ZIP_DEFLATED` to everything except `mimetype`, which is correct for text content but wasteful for binary content and also changes the byte-for-byte identity of untranslated assets. Preserving original compression type per item would be more faithful.

#### 3.3.5 `TranslationRequest` Carries Settings Fields Redundantly

**File:** `domain/models.py` lines 64–73

`TranslationRequest` contains `source_lang`, `target_lang`, `model`, and `temperature` — all fields also present in `TranslationSettings`. These are duplicated every time a request is built (in `xhtml_parser.py:_translation_request` lines 262–276). The translator port only needs the text content and the model configuration — it does not need to re-read languages from the request when they are already in settings. This redundancy inflates the request object and means future additions to `TranslationSettings` must also be added to `TranslationRequest` to be available in the translator.

### 3.4 Infrastructure Gaps

#### 3.4.1 No Integration Tests

The test suite contains only unit tests using fakes and test fixtures. There are no integration tests that exercise:
- A real EPUB file loaded, translated with a fake LLM, and saved, then round-tripped back through the repository.
- The full stage store lifecycle (save → crash simulation → resume).
- The OPF spine parsing end-to-end.

#### 3.4.2 No CI Configuration

There is no `.github/workflows/` directory. The quality gates documented in `PLAN.md` (ruff, mypy, pytest) are manually executed. Any PR that accidentally breaks linting or tests will not be caught automatically.

#### 3.4.3 No Coverage Measurement

`pyproject.toml` has no `pytest-cov` configuration. Code coverage is not measured or enforced.

#### 3.4.4 `XHTMLTranslator` Is Tested via Internal API

**File:** `tests/unit/test_preserve_inline_formatting.py` lines 14–17

The test imports `_collect_text_slots`, `_distribute_text`, and `_nearest_word_boundary` as internal (underscore-prefixed) functions. This creates a tight test–implementation coupling that makes refactoring costly. These helpers should be either promoted to public functions or moved to a dedicated module with a public interface.

---

## 4. Proposed Enhancement Areas

### 4.1 Code Quality and SOLID Refactoring

- Extract `ChapterProcessor` port to domain/ports; adapt `XHTMLTranslator` to implement it.
- Move `EpubBook` from `ports.py` to `models.py`.
- Add `ChapterStageStorePort` to domain/ports and make orchestrator depend on the port.
- Add `PromptBuilderPort` protocol; make `OllamaTranslator` depend on the protocol.
- Replace manual serialization in `chapter_stage_store.py` with `dataclasses.asdict`.
- Remove dead code: `EpubTranslateError` alias, `_SKIP_REASON_MAP` identity map, unused `ValidationError`.
- Replace `RunReport`/`ChapterReport` mutable dataclasses with immutable frozen variants.
- Extract named constants for magic numbers (`CHAPTER_CONTEXT_MAX_CHARS`, `REPORT_FIELD_MAX_CHARS`, `MAX_TRANSLATION_LEN_RATIO`, `BACKOFF_CAP_SECONDS`).

### 4.2 Architecture Improvements

- Implement EPUB OPF spine parser in `ZipEpubRepository` to determine correct chapter order.
- Extract `PromptBuilderPort` as a domain port; implement a `GlossaryAwarePromptBuilder`.
- Add `workers` to stage store signature.
- Preserve original ZIP compression modes for non-text items.
- Introduce a `ChapterProcessorPort` in the domain layer.

### 4.3 Translation Quality

- Redesign chapter context extraction: representative multi-point sample instead of first-500-chars.
- Change rolling context to source→target pairs for better terminology consistency.
- Implement a flat-file glossary mechanism (`--glossary` flag pointing to a TOML/JSON file).
- Generalize `_LEAKED_PROMPT_RE` to exclude Italian-specific markers; derive markers from prompt structure.
- Add post-translation validation: empty output guard, HTML injection detection, length-ratio retry.
- Use Ollama `/api/chat` endpoint with `system`/`user` role separation.
- Refine Italian language rules: stronger accent guidance, more complete apostrophe guidance.

### 4.4 EPUB Spec Compliance

- Parse `content.opf` OPF file to extract `<spine>` `<itemref>` order.
- Map spine `idref` values to manifest `item` `href` values to get ordered chapter paths.
- Fall back to lexicographic ordering when no OPF is found (backward compatibility).

### 4.5 Testing and CI

- Add integration test fixtures using real EPUB structures.
- Add contract tests for the Ollama HTTP boundary.
- Configure GitHub Actions CI with ruff, mypy strict, and pytest gates.
- Add `pytest-cov` with minimum coverage threshold.
- Promote underscore-prefixed helpers to a testable public surface.

---

## 5. Quality Attributes

| Attribute | Current State | Target State |
|---|---|---|
| Testability | Unit tests only; mocked dependencies | Integration + contract tests; stage store port mockable |
| Correctness (chapter order) | Lexicographic (works by coincidence) | OPF spine order (EPUB spec compliant) |
| Translation consistency | Stateless per-paragraph; no glossary | Glossary-anchored; rolling source+target pairs |
| Maintainability | Infrastructure imported by application | Full layer isolation via ports |
| CI coverage | None | GitHub Actions with ruff/mypy/pytest/cov gates |
| Italian quality | Rules defined but prompt structure weak | Stronger rules; system/user split; post-validation |

---

## 6. Constraints and Non-Goals

- All changes must maintain `mypy --strict` compliance.
- All changes must pass `ruff check` and `ruff format --check` without disabling rules.
- Python 3.9 compatibility must be maintained (no walrus operator in critical paths, no `match`, no `3.10+` union syntax in annotations).
- The Ollama API is the only supported LLM runtime for this initiative. New provider ports are out of scope.
- The CLI contract (flag names, exit codes, report schema) must remain backward-compatible.

---

## 7. Acceptance Criteria Summary

1. All five epics in the backlog have all stories at "done" (acceptance criteria met).
2. `mypy --strict src tests/unit` passes with zero errors.
3. `ruff check src tests` and `ruff format --check src tests` pass with zero violations.
4. `pytest -q` passes with zero failures.
5. Code coverage is at or above 80% for `src/` as measured by `pytest-cov`.
6. A real EPUB loaded with OPF spine ordering produces chapters in spine order, not lexicographic order.
7. A glossary file with character names produces consistent name translations across all chapters.
8. The orchestrator unit test can be run without a filesystem side effect by using an in-memory stage store.