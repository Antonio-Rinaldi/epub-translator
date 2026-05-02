# EPUB Translator CLI — Product Backlog

**Version:** 1.0
**Date:** 2026-05-02
**Status:** Ready for sprint planning

---

## Priority Matrix

| Story ID | Title | Epic | Points | Priority | Dependencies | Status |
| --- | --- | --- | --- | --- | --- | --- |
| E1S1 | Move `EpubBook` from `ports.py` to `models.py` | E1 | 1 | P1 Critical | — | ✅ Done |
| E1S6 | Freeze `RunReport` and `ChapterReport`; remove post-construction mutation | E1 | 2 | P1 Critical | E1S1 | ✅ Done |
| E1S2 | Add `ChapterStageStorePort` and make orchestrator depend on it | E1 | 3 | P1 Critical | E1S1 | ✅ Done |
| E1S3 | Add `PromptBuilderPort` and make `OllamaTranslator` depend on it | E1 | 3 | P1 Critical | E1S1 | ✅ Done |
| E1S8 | Add `ChapterProcessorPort` to domain; adapt `XHTMLTranslator` | E1 | 5 | P1 Critical | E1S1, E1S2, E1S3 | ✅ Done |
| E2S6 | Migrate `OllamaTranslator` to `/api/chat` with system/user role split | E2 | 5 | P1 Critical | E1S3 | ✅ Done |
| E3S1 | Parse OPF `content.opf` to extract `<spine>` `<itemref>` reading order | E3 | 5 | P1 Critical | E1S1 | ✅ Done |
| E1S4 | Replace manual serialization in `chapter_stage_store.py` with `dataclasses.asdict` | E1 | 2 | P2 High | E1S2, E1S6 | ✅ Done |
| E1S5 | Remove dead code (`EpubTranslateError` alias, `_SKIP_REASON_MAP`, unused `ValidationError`) | E1 | 1 | P2 High | — | ✅ Done |
| E1S7 | Extract named constants for all magic numbers | E1 | 1 | P2 High | — | ✅ Done |
| E2S1 | Redesign chapter context extraction (multi-point sample, 1500-char limit) | E2 | 3 | P2 High | E1S8 | ✅ Done |
| E2S2 | Change rolling context to source→target pairs | E2 | 3 | P2 High | E1S8 | ✅ Done |
| E2S3 | Implement flat-file glossary (`--glossary` flag, `GlossaryPort`) | E2 | 5 | P2 High | E1S3, E2S6 | ✅ Done |
| E2S4 | Generalize `_LEAKED_PROMPT_RE` to remove Italian-specific hardcoded markers | E2 | 2 | P2 High | E2S6 | ✅ Done |
| E2S8 | Implement `GlossaryAwarePromptBuilder` | E2 | 3 | P2 High | E1S3, E2S6, E2S3 | ✅ Done |
| E3S2 | Map spine `idref` → manifest `href` → chapter path | E3 | 2 | P2 High | E3S1 | ✅ Done |
| E3S3 | Fall back to lexicographic order when OPF is absent | E3 | 1 | P2 High | E3S1, E3S2 | ✅ Done |
| E4S1 | Separate XHTML node orchestration from parsing (move node loop to application) | E4 | 5 | P2 High | E1S8 | ✅ Done |
| E4S3 | Simplify `TranslationRequest` (remove redundant settings fields; add `glossary_terms`) | E4 | 3 | P2 High | E1S3, E2S6, E2S3 | ✅ Done |
| E2S5 | Add post-translation validators (empty guard, HTML injection, length-ratio retry) | E2 | 5 | P3 Medium | E2S6, E4S1 | ✅ Done |
| E2S7 | Strengthen Italian language rules in `PromptBuilder` | E2 | 2 | P3 Medium | E1S3, E2S6 | ✅ Done |
| E3S4 | Preserve original ZIP compression modes per item on save | E3 | 2 | P3 Medium | E1S1 | ✅ Done |
| E4S2 | Add `workers` to stage store run signature | E4 | 1 | P3 Medium | E1S2 | ✅ Done |
| E4S4 | Fix `_distribute_text` for dropcap case (first grapheme cluster strategy) | E4 | 3 | P3 Medium | E5S4 | ✅ Done |
| E5S1 | Add integration test: full EPUB round-trip with fake LLM | E5 | 5 | P2 High | E1S8, E3S3 | ✅ Done |
| E5S2 | Add integration test: stage store save/resume lifecycle | E5 | 3 | P2 High | E1S2 | ✅ Done |
| E5S3 | Add contract tests for Ollama HTTP boundary | E5 | 3 | P3 Medium | E2S6 | ✅ Done |
| E5S4 | Promote `_collect_text_slots`, `_distribute_text`, `_nearest_word_boundary` to public surface | E5 | 1 | P3 Medium | — | ✅ Done |
| E5S5 | Configure GitHub Actions CI (ruff, mypy, pytest) | E5 | 3 | P3 Medium | — | ✅ Done |
| E5S6 | Add pytest-cov with 80% threshold | E5 | 2 | P4 Low | E5S5 | ✅ Done |

---

## Epic 1: Code Quality and SOLID Refactoring

> Eliminate layer boundary violations, remove dead code, enforce immutability, and extract magic constants so the
> codebase fully adheres to SOLID principles and the hexagonal architecture contract.

---

### E1S1 — Move `EpubBook` from `ports.py` to `models.py`

**Status: ✅ Done**

**As a** developer maintaining the domain layer,
**I want** `EpubBook` defined alongside other domain data classes in `models.py`,
**So that** `ports.py` contains only protocol classes and the module boundary is unambiguous.

**Context:**
`EpubBook` is a plain domain data class (`@dataclass(frozen=True)`) currently at `domain/ports.py` lines 43–55. Its
presence alongside protocol classes is architecturally inconsistent. Every other data class (`TranslationSettings`,
`ChapterDocument`, `RunReport`, etc.) lives in `models.py`.

**Acceptance Criteria:**

- `EpubBook` is defined in `src/epub_translate_cli/domain/models.py`.
- `EpubBook` is removed from `src/epub_translate_cli/domain/ports.py`.
- All import sites update their import path (`epub_repository.py`, `translation_orchestrator.py`, `cli.py`).
- `mypy --strict` passes with zero errors.
- All existing tests pass without modification.

**Story Points:** 1
**Dependencies:** None
**Priority:** P1 Critical

---

### E1S2 — Add `ChapterStageStorePort` and make orchestrator depend on it

**Status: ✅ Done**

**As a** developer writing unit tests for the orchestrator,
**I want** the orchestrator to accept a `ChapterStageStorePort` dependency via constructor injection,
**So that** I can pass an in-memory fake stage store without any filesystem side effects.

**Context:**
`TranslationOrchestrator` constructs `FilesystemChapterStageStore.for_run(...)` directly at lines 61–66 of
`translation_orchestrator.py`. There is no `ChapterStageStorePort` in `domain/ports.py`. This violates the dependency
inversion principle and forces every orchestrator test to touch disk.

`StagedChapter` (currently in `chapter_stage_store.py`) must move to `domain/models.py` so the port can reference it
without importing infrastructure.

**Acceptance Criteria:**

- `ChapterStageStorePort` protocol is defined in `domain/ports.py` with methods:
  `load_completed() -> dict[int, StagedChapter]`, `save_chapter(...)`, `clear()`.
- `StagedChapter` is defined in `domain/models.py` (moved from `chapter_stage_store.py`).
- `FilesystemChapterStageStore` satisfies `ChapterStageStorePort` (verified by `isinstance` check in a test or by `mypy`
  structural subtyping).
- `TranslationOrchestrator` accepts `stage_store: ChapterStageStorePort` as a constructor field.
- `TranslationOrchestrator` no longer imports `FilesystemChapterStageStore`.
- The CLI wires `FilesystemChapterStageStore.for_run(...)` and passes it to the orchestrator.
- Unit test demonstrates orchestrator can run with an in-memory `ChapterStageStorePort` implementation without any
  filesystem side effect.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E1S1
**Priority:** P1 Critical

---

### E1S3 — Add `PromptBuilderPort` and make `OllamaTranslator` depend on it

**Status: ✅ Done**

**As a** developer building a glossary-aware prompt builder,
**I want** a formal `PromptBuilderPort` protocol in the domain layer,
**So that** alternative prompt strategies can be injected into `OllamaTranslator` with a guaranteed interface contract.

**Context:**
`PromptBuilder` is a concrete dataclass hardcoded as the default for `OllamaTranslator.prompt_builder` at line 164 of
`ollama_translator.py`. There is no protocol enforcing the interface. A `GlossaryAwarePromptBuilder` (story E2S8) cannot
be type-safely swapped without a protocol.

The protocol must be split into `build_system_prompt(settings)` and `build_user_prompt(request)` to support the
`/api/chat` endpoint migration (story E2S6).

**Acceptance Criteria:**

- `PromptBuilderPort` protocol is defined in `domain/ports.py` with methods:
  `build_system_prompt(settings: TranslationSettings) -> str` and
  `build_user_prompt(request: TranslationRequest) -> str`.
- `PromptBuilder` is moved from `ollama_translator.py` to `infrastructure/llm/prompt_builder.py` and implements
  `PromptBuilderPort`.
- `OllamaTranslator.prompt_builder` field type is `PromptBuilderPort`.
- `OllamaTranslator` no longer contains the `PromptBuilder` class definition.
- `mypy --strict` passes with zero errors.
- All existing prompt-related unit tests pass without modification.

**Story Points:** 3
**Dependencies:** E1S1
**Priority:** P1 Critical

---

### E1S4 — Replace manual serialization in `chapter_stage_store.py` with `dataclasses.asdict`

**Status: ✅ Done**

**As a** developer maintaining the stage store,
**I want** the report serialization to use `dataclasses.asdict` instead of 12 hand-written field mappings,
**So that** adding a field to `NodeChange`, `NodeFailure`, or `NodeSkip` does not require a matching manual update in
the serializer.

**Context:**
`FilesystemChapterStageStore._serialize_report` (lines 238–269 of `chapter_stage_store.py`) manually enumerates every
field of `NodeChange`, `NodeFailure`, and `NodeSkip`. `json_report_writer.py` line 21 already calls
`dataclasses.asdict(report)` for the same purpose. This duplication means any future field addition must be made in two
places.

`_SKIP_REASON_MAP` (lines 21–25) maps each `SkipReason` string to itself — a pure identity mapping that serves no
purpose. It should be removed.

**Acceptance Criteria:**

- `_serialize_report` is replaced by `dataclasses.asdict(report)` with any necessary post-processing (e.g., converting
  `tuple` to `list` for JSON round-trip if `ChapterReport` fields become tuples after E1S6).
- `_SKIP_REASON_MAP` is removed.
- `_deserialize_report` validates the raw string against the `SkipReason` `Literal` type members directly (e.g., using a
  set or `get_args(SkipReason)`).
- Stage store round-trip integration test passes (save a report, reload it, assert field equality).
- `mypy --strict` passes with zero errors.

**Story Points:** 2
**Dependencies:** E1S2, E1S6
**Priority:** P2 High

---

### E1S5 — Remove dead code (`EpubTranslateError` alias, `_SKIP_REASON_MAP`, unused `ValidationError`)

**Status: ✅ Done**

**As a** developer reading the error hierarchy,
**I want** dead code removed from `domain/errors.py` and `chapter_stage_store.py`,
**So that** the codebase only contains code that is actually used.

**Context:**

- `EpubTranslateError = EpubTranslatorError` at `domain/errors.py` lines 8–9: backward-compatible alias with zero usages
  in the package (confirmed by `grep -r EpubTranslateError src/`).
- `ValidationError` at `domain/errors.py` line 12: defined but never raised; all CLI validation uses `_abort()` →
  `typer.Exit`.
- `_SKIP_REASON_MAP` at `chapter_stage_store.py` lines 21–25: identity mapping. Removed as part of E1S4 but listed here
  as a separate acceptance criterion so it can be tracked independently.

**Acceptance Criteria:**

- `EpubTranslateError` alias is removed from `domain/errors.py`.
- `ValidationError` is removed from `domain/errors.py`.
- `grep -r "EpubTranslateError\|ValidationError" src/` returns zero results.
- `mypy --strict` passes with zero errors.
- All existing tests pass.

**Story Points:** 1
**Dependencies:** None
**Priority:** P2 High

---

### E1S6 — Freeze `RunReport` and `ChapterReport`; remove post-construction mutation

**Status: ✅ Done**

**As a** developer reasoning about report state,
**I want** `RunReport` and `ChapterReport` to be immutable frozen dataclasses,
**So that** report state cannot be accidentally mutated after construction.

**Context:**
`RunReport` and `ChapterReport` use mutable `@dataclass` at `models.py` lines 120 and 130, inconsistent with all other
domain models. The orchestrator mutates `report.output_written` at line 105 of `translation_orchestrator.py` — a
two-phase construction pattern that is error-prone.

**Acceptance Criteria:**

- `ChapterReport` uses `@dataclass(frozen=True)` with `changes: tuple[NodeChange, ...]`,
  `failures: tuple[NodeFailure, ...]`, `skips: tuple[NodeSkip, ...]`.
- `RunReport` uses `@dataclass(frozen=True)` with `chapters: tuple[ChapterReport, ...]`.
- The two-phase construction pattern in `translation_orchestrator.py` (lines 88–105) is eliminated: `output_written` is
  determined before `RunReport` is constructed.
- `TranslationOrchestrator._build_run_report` receives `output_written: bool` as a parameter and returns a
  fully-constructed `RunReport`.
- All code that previously used `list` for chapter report fields now uses `tuple(...)`.
- `mypy --strict` passes with zero errors.
- All existing tests pass.

**Story Points:** 2
**Dependencies:** E1S1
**Priority:** P1 Critical

---

### E1S7 — Extract named constants for all magic numbers

**Status: ✅ Done**

**As a** developer reading the translation pipeline,
**I want** all magic numbers replaced with named module-level constants,
**So that** the purpose of each threshold is immediately clear and changes require a single edit.

**Context:**
Magic values identified in SPEC.md §3.1.5:

- `500` at `xhtml_parser.py:174` — chapter context character limit.
- `200` at `xhtml_parser.py:347, 348, 358` — report field truncation limit.
- `3.0` at `ollama_translator.py:18` — max length ratio for leak detection (already named `_MAX_LEN_RATIO` but should
  follow a consistent naming convention).
- `4.0` at `xhtml_parser.py:409` — backoff cap in seconds.
- `0.25 * (2**attempt)` at `xhtml_parser.py:406–408` — backoff base formula (parameterize the `0.25` multiplier).

**Acceptance Criteria:**

- `CHAPTER_CONTEXT_MAX_CHARS = 1500` (updated value per E2S1) defined at module level in `xhtml_parser.py`.
- `REPORT_FIELD_MAX_CHARS = 200` defined at module level in `xhtml_parser.py`.
- `MAX_TRANSLATION_LEN_RATIO = 3.0` defined at module level in `ollama_translator.py` (renamed from `_MAX_LEN_RATIO`
  with consistent naming).
- `BACKOFF_CAP_SECONDS = 4.0` and `BACKOFF_BASE = 0.25` defined at module level in `xhtml_parser.py`.
- No bare numeric literals remain for these values anywhere in `src/`.
- `mypy --strict` passes with zero errors.

**Story Points:** 1
**Dependencies:** None
**Priority:** P2 High

---

### E1S8 — Add `ChapterProcessorPort` to domain; adapt `XHTMLTranslator`

**Status: ✅ Done**

**As a** developer writing unit tests for the orchestrator,
**I want** a `ChapterProcessorPort` protocol in the domain layer that `XHTMLTranslator` implements,
**So that** the orchestrator can be tested with a fake chapter processor and the application layer has no direct import
of any infrastructure class.

**Context:**
`TranslationOrchestrator` directly imports `XHTMLTranslator` and `ChapterTranslationResult` from
`infrastructure/epub/xhtml_parser.py` at lines 22–25. This is the core layer boundary violation identified in SPEC.md
§3.1.1. `ChapterTranslationResult` (currently at `xhtml_parser.py` lines 54–60) must move to `domain/models.py`.

**Acceptance Criteria:**

- `ChapterProcessorPort` protocol is defined in `domain/ports.py` with one method:
  `translate_chapter(chapter: ChapterDocument) -> tuple[bytes, ChapterTranslationResult]`.
- `ChapterTranslationResult` is moved to `domain/models.py`.
- `XHTMLTranslator` implements `ChapterProcessorPort` (satisfies the protocol structurally).
- `TranslationOrchestrator` no longer imports `XHTMLTranslator` or `ChapterTranslationResult` from infrastructure.
- `TranslationOrchestrator` imports `ChapterProcessorPort` and `ChapterTranslationResult` from domain.
- The CLI wires `XHTMLTranslator(translator=..., settings=...)` and passes it to the orchestrator.
- A unit test demonstrates the orchestrator can run with a fake `ChapterProcessorPort` that returns empty results
  without instantiating `XHTMLTranslator`.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E1S1, E1S2, E1S3
**Priority:** P1 Critical

---

## Epic 2: Translation Quality Improvements

> Improve the accuracy, consistency, and robustness of translated output through better context extraction, glossary
> support, prompt structure improvements, and post-translation validation.

---

### E2S1 — Redesign chapter context extraction (multi-point sample, 1500-char limit)

**Status: ✅ Done**

**As a** translator user,
**I want** the chapter context passed to the LLM to be a representative sample from across the chapter,
**So that** the model receives tone and terminology guidance from beyond just the opening paragraphs.

**Context:**
`XHTMLTranslator._chapter_context()` at `xhtml_parser.py:171–174` collects all chapter text and truncates to 500
characters — barely 3–5 sentences, capturing only the opening of the chapter. A better strategy samples from beginning,
middle, and end of the chapter text, capped at 1500 characters total (SPEC.md §3.2.1).

**Acceptance Criteria:**

- `_chapter_context` extracts text at three sample points: first paragraph, middle paragraph, last paragraph.
- The combined sample is capped at `CHAPTER_CONTEXT_MAX_CHARS = 1500` (constant from E1S7).
- Sample points are separated by a `[...]` ellipsis marker in the context string to signal discontinuity to the model.
- If the chapter has only one or two paragraphs, the method degrades gracefully (no index errors).
- The existing behavior (context is a string of chapter text) is preserved as the output type; no changes to
  `TranslationRequest` fields for this story.
- Unit test: a chapter with 50 paragraphs produces a context string that contains text from paragraph 1, paragraph ~25,
  and paragraph 50.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E1S8
**Priority:** P2 High

---

### E2S2 — Change rolling context to source→target pairs

**Status: ✅ Done**

**As a** translator user,
**I want** the rolling context window to contain source→target pairs instead of only the translated text,
**So that** the LLM can see what source text it previously mapped to what translated text, improving terminology
consistency.

**Context:**
`XHTMLTranslator._prior_translations()` at `xhtml_parser.py:254–259` builds the rolling context from a `deque[str]` of
translated texts only. The LLM has no visibility into the source paragraphs those translations came from. Showing
`"Original: ... Translation: ..."` pairs is significantly more effective for maintaining consistent rendering of
character names, place names, and recurring phrases (SPEC.md §3.2.2).

**Acceptance Criteria:**

- The rolling context deque changes from `deque[str]` to `deque[tuple[str, str]]` (source, translated).
- `_prior_translations()` formats each pair as: `"Original: {source}\nTranslation: {translated}"`.
- Pairs are separated by a blank line in the context block.
- The `prior_translations` field in `TranslationRequest` still receives a single formatted string (backward-compatible).
- Unit test: a rolling window with two entries produces a formatted string containing both `Original:` and
  `Translation:` labels.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E1S8
**Priority:** P2 High

---

### E2S3 — Implement flat-file glossary (`--glossary` flag, `GlossaryPort`)

**Status: ✅ Done**

**As a** translator user,
**I want** to supply a flat-file glossary of terms that must be translated consistently,
**So that** character names, place names, and invented vocabulary are rendered identically across all chapters.

**Context:**
No glossary mechanism currently exists. Without it, the LLM may render "D" as "D.", "the Hunter", or "il Cacciatore"
inconsistently across a novel's chapters (SPEC.md §3.2.3).

**Acceptance Criteria:**

- `GlossaryEntry` and `Glossary` domain models are added to `domain/models.py`.
- `GlossaryPort` protocol is added to `domain/ports.py` with `load(path: Path) -> Glossary`.
- `TomlGlossaryLoader` infrastructure adapter in `infrastructure/llm/prompt_builder.py` implements `GlossaryPort` and
  reads a TOML file with the schema `[glossary]\n"term" = "translation"`.
- `JsonGlossaryLoader` infrastructure adapter reads a JSON file with schema `{"glossary": {"term": "translation"}}`.
- CLI adds `--glossary` option accepting an optional `Path`. When provided, the glossary is loaded and passed through
  the pipeline.
- `Glossary.as_dict()` returns `dict[str, str]` injected into each `TranslationRequest.glossary_terms`.
- When `--glossary` is not supplied, `glossary_terms` is an empty dict and behavior is identical to current.
- Integration test: a glossary file with `"D" = "D"` and `"Doris" = "Doris"` produces a translation request containing
  those terms in `glossary_terms`.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E1S3, E2S6
**Priority:** P2 High

---

### E2S4 — Generalize `_LEAKED_PROMPT_RE` to remove Italian-specific hardcoded markers

**Status: ✅ Done**

**As a** developer supporting multiple translation directions,
**I want** the leaked-prompt detector to match only the current English prompt markers,
**So that** the sanitizer does not contain legacy Italian-language strings that never appear in current prompts.

**Context:**
`_LEAKED_PROMPT_RE` at `ollama_translator.py:23–26` matches `TESTO DA TRADURRE` and `CONTESTO DEL CAPITOLO` — Italian
echoes of an older prompt version. The current prompt uses only English labels. These strings are misleadingly
documented as "known prompt markers" but originate from a different, historical prompt phrasing (SPEC.md §3.2.4).

After the `/api/chat` migration (E2S6), the user prompt template will use `<<<` / `>>>` fences and no labelled headers.
The sanitizer should match only the fence markers that actually appear in current prompts.

**Acceptance Criteria:**

- `_LEAKED_PROMPT_RE` is redefined to match only the fence markers present in the current prompt template (`<<<` /
  `>>>`).
- Italian-specific strings (`TESTO DA TRADURRE`, `CONTESTO DEL CAPITOLO`) are removed from the regex.
- The regex continues to handle the known case where the model echoes back the text-to-translate block.
- A unit test verifies that a response containing `TESTO DA TRADURRE` is no longer stripped.
- A unit test verifies that a response containing the `<<<`-fenced text block is still stripped.
- `mypy --strict` passes with zero errors.

**Story Points:** 2
**Dependencies:** E2S6
**Priority:** P2 High

---

### E2S5 — Add post-translation validators (empty guard, HTML injection, length-ratio retry)

**Status: ✅ Done**

**As a** translator user,
**I want** the pipeline to detect and handle pathological translation outputs automatically,
**So that** empty translations, HTML injection, and excessively long responses do not silently corrupt the output EPUB.

**Context:**
Three gaps identified in SPEC.md §3.2.5 and §3.2.6:

1. Empty output after `_sanitise_response` is not detected — an empty string silently replaces the source paragraph.
2. HTML/XML tag injection by the model is not detected.
3. Length ratio > 3× currently logs a warning but does not retry.

**Acceptance Criteria:**

- If `_sanitise_response` produces an empty string, a `RetryableTranslationError` is raised so the retry logic in
  `_translate_with_retries` can attempt recovery.
- If the cleaned response contains `<` followed by a word character (naive HTML tag detection), a
  `RetryableTranslationError` is raised on the first occurrence; on final retry, a `NonRetryableTranslationError` is
  raised.
- If `len(clean_text) > MAX_TRANSLATION_LEN_RATIO * len(source_text)`, a `RetryableTranslationError` is raised (instead
  of the current warning-and-continue).
- Unit tests cover each guard: empty result, HTML-injected result, oversized result.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E2S6, E4S1
**Priority:** P3 Medium

---

### E2S6 — Migrate `OllamaTranslator` to `/api/chat` with system/user role split

**Status: ✅ Done**

**As a** translator user,
**I want** the LLM called with a proper chat-format request separating persona/rules from translatable content,
**So that** instruction-tuned models (Llama 3, Mistral, Phi-3) follow the output constraints more reliably.

**Context:**
`OllamaTranslator` uses `POST /api/generate` with a single concatenated prompt string (lines 167–179 of
`ollama_translator.py`). Modern instruction-tuned models perform better when the system persona/rules are in the
`system` role and the translatable text is in the `user` role (SPEC.md §3.2.8). The `/api/chat` endpoint supports this
directly.

**Acceptance Criteria:**

- `OllamaTranslator` calls `POST /api/chat` instead of `POST /api/generate`.
- The request payload uses `messages: [{"role": "system", ...}, {"role": "user", ...}]`.
- `_generate_url` is replaced by `_chat_url` returning `{base_url}/api/chat`.
- `_payload` is replaced by `_chat_payload(request, settings, prompt_builder)`.
- Response parsing changes from `payload["response"]` to `payload["message"]["content"]`.
- `_response_text` is updated accordingly; error messages reference the `message.content` field.
- `OllamaTranslator` receives `settings: TranslationSettings` at construction time (needed to build the system prompt,
  since `TranslationRequest` will no longer carry `source_lang` etc. after E4S3).
- All existing Ollama unit tests are updated to use the new payload structure.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E1S3
**Priority:** P1 Critical

---

### E2S7 — Strengthen Italian language rules in `PromptBuilder`

**Status: ✅ Done**

**As a** Italian-language translator user,
**I want** the Italian orthographic rules in the prompt to cover more edge cases,
**So that** the output EPUB has fewer accent errors, apostrophe misuses, and formatting inconsistencies.

**Context:**
The existing Italian rules in `_LANGUAGE_RULES["it"]` (lines 57–70 of `ollama_translator.py`) cover accents,
apostrophes, punctuation spacing, month/day capitalization, guillemets, and pronoun capitalization. SPEC.md §3.2.7 notes
that the length guidance is vague ("roughly the same length"). Two additional rules are needed: realistic length
expansion guidance (Italian is 5–15% longer than English) and stronger guidance on the `è`/`é` distinction that models
frequently get wrong.

**Acceptance Criteria:**

- Italian rules are updated in `infrastructure/llm/prompt_builder.py` (after the move in E1S3).
- A rule is added specifying realistic length expectations: "Italian translations of English prose are typically 5–15%
  longer. Do not compress text to match the source length character-for-character."
- The existing accent rule is expanded to include explicit examples of common errors: `e'` → `è`, `po'` (truncation,
  correct) vs `pò` (wrong).
- The apostrophe rule is expanded to cover `un'` (feminine elision) vs `un` (masculine, no apostrophe).
- Unit test: `PromptBuilder().build_system_prompt(settings_italian)` contains the new rule strings.
- `mypy --strict` passes with zero errors.

**Story Points:** 2
**Dependencies:** E1S3, E2S6
**Priority:** P3 Medium

---

### E2S8 — Implement `GlossaryAwarePromptBuilder`

**Status: ✅ Done**

**As a** translator user using a glossary file,
**I want** the glossary terms injected into the prompt as a mandatory translation table,
**So that** the LLM is explicitly instructed to use the specified translations for known terms.

**Context:**
After E2S3 introduces `glossary_terms: dict[str, str]` in `TranslationRequest`, the existing `PromptBuilder` ignores
this field. A `GlossaryAwarePromptBuilder` must format the terms into a visible block in the user prompt (SPEC.md §4.1,
§4.3).

**Acceptance Criteria:**

- `GlossaryAwarePromptBuilder` is defined in `infrastructure/llm/prompt_builder.py` and implements `PromptBuilderPort`.
- `build_user_prompt(request)` includes a glossary block when `request.glossary_terms` is non-empty, formatted as:
  `"MANDATORY TERM TRANSLATIONS (always use these exact translations):\n  {src} -> {tgt}\n..."`.
- The glossary block appears before the chapter context block and before the text-to-translate fence.
- When `glossary_terms` is empty, the block is omitted and the output is identical to `PromptBuilder`.
- `OllamaTranslator` defaults to using `GlossaryAwarePromptBuilder` (replaces the previous `PromptBuilder` default).
- Unit test: a request with two glossary entries produces a prompt containing both `src -> tgt` lines.
- Unit test: a request with empty glossary produces no glossary block.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E1S3, E2S6, E2S3
**Priority:** P2 High

---

## Epic 3: EPUB Spec Compliance

> Implement correct EPUB OPF spine-order chapter reading and preserve original ZIP compression types, making the tool
> spec-compliant for all real-world EPUB inputs.

---

### E3S1 — Parse OPF `content.opf` to extract `<spine>` `<itemref>` reading order

**Status: ✅ Done**

**As a** translator user,
**I want** the tool to parse the EPUB OPF package document to find the spine order,
**So that** chapters are processed and translated in the correct reading order as defined by the EPUB specification.

**Context:**
`ZipEpubRepository._chapter_documents()` at `epub_repository.py:36–45` uses `sorted(..., key=lambda doc: doc.path)` —
lexicographic sort. The EPUB specification mandates OPF spine order (SPEC.md §3.3.1). The fix requires parsing
`META-INF/container.xml` and the OPF file, both already loaded into `items`.

**Acceptance Criteria:**

- `OPFSpineParser` class is added at `src/epub_translate_cli/infrastructure/epub/opf_spine_parser.py`.
- `OPFSpineParser.find_opf_path(items)` reads `META-INF/container.xml`, parses the `<rootfile full-path="...">`
  attribute, and returns the OPF path string, or `None` if absent/unparseable.
- `OPFSpineParser.ordered_chapter_paths(opf_bytes, all_paths)` parses the OPF XML, reads `<manifest>` items and
  `<spine>` itemrefs, maps `idref` → `href`, and returns the ordered list of chapter paths present in `all_paths`.
- Returns `None` (not an empty list) when the OPF is absent or structurally invalid, signaling the caller to fall back.
- `lxml` is used for XPath traversal (no new dependencies).
- Unit test with a minimal synthetic OPF XML verifies correct `idref` → `href` mapping.
- Unit test with malformed OPF XML verifies graceful `None` return.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E1S1
**Priority:** P1 Critical

---

### E3S2 — Map spine `idref` → manifest `href` → chapter path

**Status: ✅ Done**

**As a** translator user,
**I want** the OPF manifest lookup to correctly resolve spine item references to archive paths,
**So that** relative paths and subdirectory-based EPUB structures are handled correctly.

**Context:**
OPF spine `<itemref idref="ch01"/>` refers to `<item id="ch01" href="Text/chapter01.xhtml"/>`. The `href` is relative to
the OPF file's directory (e.g., if OPF is at `OEBPS/content.opf`, the resolved path is `OEBPS/Text/chapter01.xhtml`).
This resolution must handle the case where the OPF is at the archive root vs. in a subdirectory.

**Acceptance Criteria:**

- `OPFSpineParser.ordered_chapter_paths` correctly resolves OPF-relative `href` values using
  `posixpath.join(opf_dir, href)` and `posixpath.normpath`.
- Both `href="chapter01.xhtml"` (OPF at root) and `href="Text/chapter01.xhtml"` (OPF in `OEBPS/`) are resolved
  correctly.
- The `all_paths` filter ensures only paths present in the actual archive are returned.
- Unit test: OPF in `OEBPS/` with `href="Text/ch01.xhtml"` produces path `OEBPS/Text/ch01.xhtml`.
- Unit test: OPF at archive root with `href="ch01.xhtml"` produces path `ch01.xhtml`.
- `mypy --strict` passes with zero errors.

**Story Points:** 2
**Dependencies:** E3S1
**Priority:** P2 High

---

### E3S3 — Fall back to lexicographic order when OPF is absent

**Status: ✅ Done**

**As a** developer maintaining backward compatibility,
**I want** the repository to fall back to lexicographic chapter ordering when OPF parsing returns `None`,
**So that** EPUBs that currently work correctly continue to work after the OPF parser is introduced.

**Context:**
`OPFSpineParser.ordered_chapter_paths` returns `None` when the OPF is absent or invalid (story E3S1).
`ZipEpubRepository._chapter_documents` must handle this return value and fall back gracefully.

**Acceptance Criteria:**

- `ZipEpubRepository._chapter_documents` calls `OPFSpineParser` first; if the result is `None`, falls back to
  `sorted(..., key=lambda doc: doc.path)`.
- When the fallback is used, a `logger.warning(...)` is emitted indicating that OPF spine order is unavailable.
- Integration test: an EPUB archive without `META-INF/container.xml` produces chapters in lexicographic order without
  raising an exception.
- Integration test: an EPUB archive with a valid OPF produces chapters in spine order.
- `mypy --strict` passes with zero errors.

**Story Points:** 1
**Dependencies:** E3S1, E3S2
**Priority:** P2 High

---

### E3S4 — Preserve original ZIP compression modes per item on save

**Status: ✅ Done**

**As a** translator user,
**I want** the saved EPUB to use the same compression mode as the original for each archive item,
**So that** pre-compressed binary assets (JPEG, PNG) are not wastefully re-compressed and the output archive is
byte-faithful for non-text items.

**Context:**
`ZipEpubRepository._write_archive_items` at `epub_repository.py:58–61` applies `ZIP_DEFLATED` to every non-`mimetype`
item. The original archive may store JPEG/PNG items as `ZIP_STORED` (since those formats are already compressed).
Applying `ZIP_DEFLATED` is wasteful and changes the byte identity of untranslated assets (SPEC.md §3.3.4).

**Acceptance Criteria:**

- `EpubBook` gains a `compression_types: dict[str, int]` field mapping archive path to original ZIP compression
  constant (see ARCHITECTURE.md §4.1).
- `ZipEpubRepository._read_archive_items` reads each `ZipInfo.compress_type` and populates `compression_types`.
- `ZipEpubRepository._write_archive_items` uses `book.compression_types.get(name, zipfile.ZIP_DEFLATED)` as the
  compression type for each item.
- `mimetype` is always written as `ZIP_STORED` regardless of `compression_types`.
- Unit test: an EPUB with a JPEG item originally stored as `ZIP_STORED` is saved with `ZIP_STORED` for that item.
- `mypy --strict` passes with zero errors.

**Story Points:** 2
**Dependencies:** E1S1
**Priority:** P3 Medium

---

## Epic 4: Architecture Improvements

> Complete the separation of concerns within the translation pipeline, fix algorithmic fragility, and simplify domain
> models to reduce redundancy.

---

### E4S1 — Separate XHTML node orchestration from parsing (move node loop to application)

**Status: ✅ Done**

**As a** developer maintaining the translation pipeline,
**I want** `XHTMLTranslator` to handle only XHTML I/O (parse/serialize) while the node-level translation loop lives in
the application layer,
**So that** infrastructure concerns (lxml parsing) are fully separated from application concerns (retry policy, rolling
context, reporting).

**Context:**
`XHTMLTranslator._translate_nodes` at `xhtml_parser.py:176–220` contains the per-node translation loop, retry calls,
rolling context maintenance, and report construction — all application concerns (SPEC.md §3.1.1). The orchestrator
directly imports and uses this infrastructure class.

This story depends on E1S8 (which introduces `ChapterProcessorPort` and moves `ChapterTranslationResult` to domain).
After E1S8, `XHTMLTranslator` still internally does the node loop. This story extracts that loop into the application
layer.

**Acceptance Criteria:**

- `XHTMLTranslator` exposes two public methods:
  `parse_chapter(chapter: ChapterDocument) -> tuple[etree._Element, list[TranslatableNode]]` and
  `serialize_chapter(root: etree._Element) -> bytes`.
- A new application-layer class (e.g., `ChapterTranslator`) in `application/services/` holds the node translation loop,
  rolling context, and report assembly, and satisfies `ChapterProcessorPort`.
- `ChapterTranslator` depends on `XHTMLTranslator` via constructor injection (typed as the minimal structural protocol
  it needs — or via a new `XHTMLParserPort`).
- `TranslationOrchestrator` uses `ChapterTranslator`, not `XHTMLTranslator` directly.
- All existing node-level unit tests pass against the new structure.
- `mypy --strict` passes with zero errors.

**Story Points:** 5
**Dependencies:** E1S8
**Priority:** P2 High

---

### E4S2 — Add `workers` to stage store run signature

**Status: ✅ Done**

**As a** developer debugging parallel translation runs,
**I want** the stage store signature to include the `workers` count,
**So that** changing `--workers` between a partial run and its resume invalidates the cached stage instead of silently
reusing it.

**Context:**
`FilesystemChapterStageStore.for_run` builds a signature dict at lines 63–75 of `chapter_stage_store.py` that includes
`model`, `temperature`, `retries`, and `context_paragraphs` but not `workers`. Two runs with different worker counts
share the same staging workspace (SPEC.md §3.3.3).

**Acceptance Criteria:**

- `"workers": settings.workers` is added to the signature dict in `FilesystemChapterStageStore.for_run`.
- Existing staged workspaces from before this change will have a mismatched signature and be reset (acceptable: the
  signature change is intentional).
- Unit test: two `for_run` calls with identical settings but different `workers` values produce different `signature`
  dicts.
- `mypy --strict` passes with zero errors.

**Story Points:** 1
**Dependencies:** E1S2
**Priority:** P3 Medium

---

### E4S3 — Simplify `TranslationRequest` (remove redundant settings fields; add `glossary_terms`)

**Status: ✅ Done**

**As a** developer reading the translation request model,
**I want** `TranslationRequest` to carry only the content fields that vary per-node,
**So that** settings that are fixed for the entire run are not duplicated into every request object.

**Context:**
`TranslationRequest` at `models.py:62–73` contains `source_lang`, `target_lang`, `model`, and `temperature` — all also
present in `TranslationSettings`. Every call to `_translation_request()` at `xhtml_parser.py:261–276` copies these from
settings to request. This redundancy means adding a new settings field requires updating `TranslationRequest` too (
SPEC.md §3.3.5).

After E2S6, `OllamaTranslator` receives `settings` at construction time and builds the system prompt once, so it no
longer needs these fields from `TranslationRequest`. After E2S3, `glossary_terms` is added.

**Acceptance Criteria:**

- `TranslationRequest` removes fields: `source_lang`, `target_lang`, `model`, `temperature`.
- `TranslationRequest` adds field: `glossary_terms: dict[str, str]` with default `field(default_factory=dict)`.
- `XHTMLTranslator._translation_request` (or the application-layer equivalent after E4S1) is updated to build the
  simplified request.
- `PromptBuilderPort.build_system_prompt(settings)` receives `TranslationSettings` for language/model info.
- All prompt builder implementations are updated to match.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E1S3, E2S6, E2S3
**Priority:** P2 High

---

### E4S4 — Fix `_distribute_text` for dropcap case (first grapheme cluster strategy)

**Status: ✅ Done**

**As a** translator user translating novels with dropcap formatting,
**I want** translated text to be distributed correctly across dropcap inline spans,
**So that** a single-character dropcap `<span>` receives exactly one grapheme cluster from the translated text instead
of a proportional fraction that may be empty or truncated.

**Context:**
`_distribute_text` at `xhtml_parser.py:97–126` uses character-length proportions to split translated text across inline
slots. For a dropcap paragraph (a 1-character `<span>` followed by 100+ characters of body text), the proportion
`1/(1+100)` ≈ 0.99% of the translated text may round to 0 characters for the dropcap slot. Italian translations may not
produce a clean single-character first token (SPEC.md §3.3.2).

The fix: when the first slot has length 1 and the translated text is non-empty, assign the first Unicode grapheme
cluster to the first slot and the remainder to subsequent slots.

**Acceptance Criteria:**

- `_distribute_text` is updated so that when `slot_lengths[0] == 1`, the first chunk is `translated[:1]` (the first
  grapheme, assuming BMP characters; grapheme cluster handling for combining marks is a stretch goal).
- The remaining slots share `translated[1:]` using the existing proportional algorithm.
- Existing tests for `_distribute_text` continue to pass.
- New unit test: `_distribute_text("Hello world", [1, 10])` returns `["H", "ello world"]`.
- New unit test: `_distribute_text("Ciao mondo", [1, 20])` returns `["C", "iao mondo"]`.
- `mypy --strict` passes with zero errors.

**Story Points:** 3
**Dependencies:** E5S4
**Priority:** P3 Medium

---

## Epic 5: Testing and CI Infrastructure

> Establish a robust automated quality gate with integration tests, contract tests, CI configuration, and enforced code
> coverage.

---

### E5S1 — Add integration test: full EPUB round-trip with fake LLM

**Status: ✅ Done**

**As a** developer,
**I want** an integration test that loads a real EPUB, translates it with a fake LLM, and saves it, then reloads it,
**So that** the full pipeline from file-to-file is verified end-to-end including OPF spine ordering and XHTML round-trip
fidelity.

**Context:**
SPEC.md §3.4.1: the test suite has no integration tests. The orchestrator, repository, parser, stage store, and report
writer all have unit tests, but no test exercises them together end-to-end. A round-trip test that uses the real
`ZipEpubRepository`, the real `XHTMLTranslator`, and a fake `TranslatorPort` would catch integration failures that unit
tests cannot.

**Acceptance Criteria:**

- A test fixture EPUB with at least two chapters (with OPF spine defined) is added to `tests/fixtures/`.
- The integration test uses `ZipEpubRepository`, `XHTMLTranslator`/`ChapterTranslator`, and a `FakeTranslator` (returns
  `"[translated] {source_text}"` for any input).
- The test asserts: output EPUB is a valid ZIP archive; chapters appear in spine order in the output; each translated
  `<p>` text starts with `"[translated]"`.
- The test uses a temporary directory for output paths.
- `mypy --strict` passes for the test file.

**Story Points:** 5
**Dependencies:** E1S8, E3S3
**Priority:** P2 High

---

### E5S2 — Add integration test: stage store save/resume lifecycle

**Status: ✅ Done**

**As a** developer,
**I want** an integration test that saves chapter snapshots to the stage store, then "resumes" from them,
**So that** the save/resume lifecycle is verified end-to-end including signature validation and manifest integrity.

**Context:**
SPEC.md §3.4.1: the stage store has unit tests for individual methods but no test exercises the full save-then-resume
cycle, including the signature change detection that resets the workspace.

**Acceptance Criteria:**

- Integration test uses `FilesystemChapterStageStore.for_run(...)` with a real temporary directory.
- Test saves two chapter snapshots, then calls `load_completed()` and asserts both are returned.
- Test changes one settings field, creates a new store, calls `load_completed()`, and asserts empty result (signature
  mismatch resets workspace).
- Test saves a chapter with failures (`report.failures` non-empty), calls `load_completed()`, asserts the chapter is NOT
  in the completed map (completed = False).
- `mypy --strict` passes for the test file.

**Story Points:** 3
**Dependencies:** E1S2
**Priority:** P2 High

---

### E5S3 — Add contract tests for Ollama HTTP boundary

**Status: ✅ Done**

**As a** developer,
**I want** contract tests that verify `OllamaTranslator` behaves correctly against the Ollama `/api/chat` HTTP contract,
**So that** HTTP transport errors, non-200 status codes, malformed JSON, and empty responses each trigger the correct
domain error.

**Context:**
SPEC.md §3.4.1: there are no contract tests for the Ollama HTTP boundary. The translator is only tested via its public
`translate()` method with mock HTTP responses.

**Acceptance Criteria:**

- Contract tests use `responses` library (or `unittest.mock.patch`) to mock HTTP at the `requests.post` level.
- Test cases cover: HTTP 200 with valid `/api/chat` JSON → `TranslationResponse`; HTTP 500 →
  `RetryableTranslationError`; HTTP 400 → `NonRetryableTranslationError`; JSON decode error →
  `RetryableTranslationError`; `message.content` empty string → `RetryableTranslationError`;
  `requests.RequestException` → `RetryableTranslationError`.
- All tests are in `tests/unit/test_ollama_translator_contract.py` or equivalent.
- `mypy --strict` passes for the test file.

**Story Points:** 3
**Dependencies:** E2S6
**Priority:** P3 Medium

---

### E5S4 — Promote `_collect_text_slots`, `_distribute_text`, `_nearest_word_boundary` to public surface

**Status: ✅ Done**

**As a** developer writing tests for XHTML text distribution,
**I want** the text-slot helper functions to be public (no underscore prefix),
**So that** tests can import them directly without coupling to internal implementation details.

**Context:**
`tests/unit/test_preserve_inline_formatting.py` lines 14–17 imports `_collect_text_slots`, `_distribute_text`, and
`_nearest_word_boundary` with underscore names (SPEC.md §3.4.4). This creates test-implementation coupling that makes
refactoring costly because renaming these functions breaks the test import.

**Acceptance Criteria:**

- `_collect_text_slots`, `_distribute_text`, and `_nearest_word_boundary` are renamed to `collect_text_slots`,
  `distribute_text`, and `nearest_word_boundary` in `xhtml_parser.py`.
- All internal callers within `xhtml_parser.py` are updated to use the new names.
- Existing tests updated to import the public names.
- `mypy --strict` passes with zero errors.

**Story Points:** 1
**Dependencies:** None
**Priority:** P3 Medium

---

### E5S5 — Configure GitHub Actions CI (ruff, mypy, pytest)

**Status: ✅ Done**

**As a** developer submitting a pull request,
**I want** a CI workflow that automatically runs `ruff`, `mypy --strict`, and `pytest`,
**So that** linting failures, type errors, and test failures are caught before merging.

**Context:**
SPEC.md §3.4.2: no `.github/workflows/` directory exists. Quality gates are manually run. Any PR that breaks linting or
tests will not be caught automatically.

**Acceptance Criteria:**

- `.github/workflows/ci.yml` is created.
- Workflow triggers on `push` to `main` and on all `pull_request` events.
- Workflow runs on `ubuntu-latest` with Python 3.9 and Python 3.11 matrix.
- Steps: checkout, install `.[dev]`, run `ruff check src tests`, run `ruff format --check src tests`, run
  `mypy --strict src tests/unit`, run `pytest -q`.
- All steps must pass for the workflow to succeed.
- Workflow file passes YAML lint.

**Story Points:** 3
**Dependencies:** None
**Priority:** P3 Medium

---

### E5S6 — Add pytest-cov with 80% threshold

**Status: ✅ Done**

**As a** developer maintaining code quality,
**I want** pytest-cov configured to enforce a minimum 80% coverage threshold,
**So that** coverage regressions are caught automatically in CI.

**Context:**
SPEC.md §3.4.3: `pyproject.toml` has no `pytest-cov` configuration. Code coverage is unmeasured and unenforced.

**Acceptance Criteria:**

- `pytest-cov>=4.0.0` is added to `[project.optional-dependencies].dev` in `pyproject.toml`.
- `pyproject.toml` `[tool.pytest.ini_options]` is updated with
  `addopts = "-q --cov=epub_translate_cli --cov-report=term-missing --cov-fail-under=80"`.
- `pytest -q` passes with coverage at or above 80%.
- The CI workflow (E5S5) is updated to include the coverage step.

**Story Points:** 2
**Dependencies:** E5S5
**Priority:** P4 Low