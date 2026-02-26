# EPUB Translator CLI Plan

## 1. Goal
Build a Python CLI that:
- Reads EPUB from input path
- Translates paragraph text nodes via Ollama
- Writes translated EPUB to `--out`
- Emits JSON report of changes and failures

## 2. Core Constraints
- SOLID, DRY, KISS
- Required CLI flags: `--model`, `--source-lang`, `--target-lang`, `--out`
- Optional: `--temperature` default value, `--retries` default 3, `--abort-on-error` default false
- Strategy: read full chapter HTML for context, translate paragraph-level text nodes
- Preserve structure as much as possible, allow minor normalization
- Never modify link text or URL targets, footnotes, code blocks, and metadata nodes

## 3. Proposed Project Structure

```python
src/
  epub_translate_cli/
    __init__.py
    main.py
    cli.py
    application/
      services/
        translation_orchestrator.py
    domain/
      models.py
      ports.py
      errors.py
    infrastructure/
      epub/
        epub_reader.py
        xhtml_parser.py
        epub_writer.py
      llm/
        ollama_client.py
      reporting/
        json_report_writer.py
      logging/
        logger_factory.py
tests/
  unit/
  integration/
```

## 4. SOLID Design
- Single Responsibility:
  - EPUB read/write isolated from translation
  - LLM calls isolated from parsing
  - Reporting isolated from workflow
- Open/Closed:
  - New LLM providers via `TranslatorPort`
  - New output reporters via `ReportWriterPort`
- Liskov:
  - Any `TranslatorPort` implementation can replace Ollama client
- Interface Segregation:
  - Separate ports for translation, EPUB IO, reporting
- Dependency Inversion:
  - Orchestrator depends on interfaces, not concrete classes

## 5. Domain Ports and Models
- Ports:
  - `EpubRepositoryPort`: load chapters, save translated book
  - `TranslatorPort`: translate text with context and settings
  - `ReportWriterPort`: write run report JSON
- Models:
  - `ChapterDocument`
  - `ParagraphNode`
  - `TranslationRequest`
  - `TranslationResult`
  - `NodeChange`
  - `NodeFailure`
  - `RunReport`

## 6. Processing Pipeline
1. Validate CLI inputs and file paths
2. Load EPUB and discover translatable chapter XHTML
3. For each chapter:
   - Parse full HTML DOM
   - Build chapter context summary text
   - Locate paragraph-level text nodes
4. For each paragraph node:
   - Apply eligibility filter before translation
   - Skip node when inside links, footnotes, code/pre blocks, or metadata containers
   - Build translation prompt with chapter context and node text
   - Call Ollama with retry policy
   - Replace node text on success
   - Record failure on final error
5. Persist report JSON
6. Output behavior:
   - If `--abort-on-error=true` and failures > 0: do not write EPUB
   - Else write EPUB to `--out`

## 7. Ollama Translation Design
- Request includes:
  - source language
  - target language
  - chapter context excerpt
  - strict instruction to return translated plain text only
- Retry:
  - configurable count, default 3
  - exponential backoff
- Error classes:
  - transient transport/model unavailable
  - response format invalid
  - non-retryable client config error

## 8. JSON Report Schema
- Top-level:
  - input path, output path
  - model, source language, target language, temperature, retries
  - totals: chapters processed, nodes seen, nodes changed, nodes failed
  - output written boolean
- Per chapter:
  - chapter id/path
  - changed nodes list
  - failed nodes list
- Node change entry:
  - node id, original excerpt, translated excerpt
- Node failure entry:
  - node id, error type, message, attempts
- Node skip entry:
  - node id, chapter path, skip reason

## 9. CLI UX Spec
- Command shape:
  - `epub-translate --in INPUT.epub --out OUTPUT.epub --source-lang xx --target-lang yy --model MODEL`
- Flags:
  - `--temperature` default `0.2`
  - `--retries` default `3`
  - `--report-out` optional; if missing derive near `--out`
  - `--abort-on-error` boolean default `false`
- Exit codes:
  - `0` success
  - `1` validation or runtime failure
  - `2` completed with failures and aborted output due to `--abort-on-error`

## 10. Testing Strategy
- Unit tests:
  - parser node extraction and replacement
  - retry policy behavior
  - orchestrator output policy logic
  - report generation mapping
  - eligibility filter for protected nodes and skip reason classification
- Integration tests:
  - fixture EPUB round-trip
  - fake translator deterministic outputs
  - partial-failure scenario and abort policy
  - protected content scenario to assert unchanged links, footnotes, code blocks, and metadata nodes
- Contract tests:
  - Ollama client response parsing and error mapping

## 11. Coding Standards
- Tooling:
  - Ruff lint + format
  - MyPy strict for core modules
  - Pytest with coverage threshold
- Practices:
  - explicit types for public interfaces
  - pure functions where possible
  - no hidden global state
  - deterministic error messages for reports

## 12. Mermaid Flow

```mermaid
flowchart TD
  A[Parse CLI args] --> B[Validate input and options]
  B --> C[Load EPUB chapters]
  C --> D[Parse chapter HTML]
  D --> E[Extract paragraph nodes]
  E --> F[Translate node with Ollama and retries]
  F --> G[Apply translated text]
  F --> H[Record failure]
  G --> I[Update run report]
  H --> I
  I --> J{Abort on error and failures exist}
  J -->|Yes| K[Write report only]
  J -->|No| L[Write report and output EPUB]