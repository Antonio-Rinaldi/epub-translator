# EPUB Translator CLI Plan

## 1. Objective
Deliver a production-grade CLI that translates EPUB narrative content with Ollama, preserves document structure, and emits a reliable JSON report for auditing and troubleshooting.

## 2. Current Baseline (Implemented)
- Translation scope includes `p` and heading tags `h1`-`h6`.
- Layered architecture is in place (`domain`, `application`, `infrastructure`) with port-based adapters.
- `TranslationOrchestrator` acts as facade and coordinates repository, parser, translator, and report writer.
- CLI uses a command-style input model and explicit validation/build steps.
- Inline formatting preservation uses text-slot collection and proportional redistribution.
- Retry/backoff and abort policy (`--abort-on-error`) are implemented.
- Unit suite covers parser behavior, skip rules, sanitization, and orchestrator abort semantics.

## 3. Architecture Snapshot

```text
src/epub_translate_cli/
  cli.py
  main.py
  application/services/translation_orchestrator.py
  domain/{models.py,ports.py,errors.py}
  infrastructure/
    epub/{epub_repository.py,xhtml_parser.py}
    llm/ollama_translator.py
    reporting/json_report_writer.py
    logging/logger_factory.py
tests/unit/
  test_orchestrator_abort_on_error.py
  test_preserve_inline_formatting.py
  test_sanitise_response.py
  test_skip_reason.py
```

## 4. Runtime Pipeline (As-Built)
1. CLI validates flags and builds immutable translation command/settings.
2. Repository loads EPUB item map and chapter documents.
3. Each chapter is parsed; translatable nodes are selected (`p`, `h1`-`h6`).
4. Protected/empty nodes are skipped with explicit skip reasons.
5. Translator request includes source text plus chapter/rolling context.
6. Ollama adapter builds prompt, performs HTTP call, retries retryable errors, sanitizes response.
7. Parser applies translated text while preserving inline element ownership.
8. Report aggregates changes, skips, failures, totals.
9. If failures exist and `--abort-on-error=true`, EPUB write is skipped and exit code is `2`; otherwise output EPUB is saved.

## 5. Safety And Content Rules
- Skip protected code/metadata regions (`code`, `pre`, `head`, `title`, `style`, `script`).
- Preserve XHTML validity and avoid malformed/self-closing inline artifacts.
- Keep href/attribute structure intact; only textual node payload is translated.
- Keep deterministic error taxonomy (`RetryableTranslationError`, validation/runtime categories) for report stability.

## 6. Quality Gates
- Lint: `ruff check src tests`
- Format: `ruff format --check src tests`
- Typing: `mypy --strict src tests/unit`
- Tests: `pytest -q tests/unit`

Status now: passing after strict typing cleanup in report writer and lxml-heavy test helpers.

## 7. Next Hardening Milestones
1. Add integration fixtures for full EPUB round-trip with heading-heavy chapters.
2. Add contract tests for Ollama adapter HTTP/status/error mapping boundaries.
3. Add CI workflow with required gates (ruff, mypy strict, pytest unit).
4. Add coverage threshold and regression snapshot for report schema.
5. Add benchmark harness for worker scaling and context-window cost.

## 8. Risks To Monitor
- LLM output drift (prompt leakage or malformed content) under different models.
- Context-window growth with long chapters causing latency or token pressure.
- EPUB edge cases (non-standard XHTML/entities) that may bypass skip logic.
- Parallel processing contention when future shared-state features are introduced.

## 9. Hardening Outcome (2026-04-09)
- `ruff check src tests`: pass
- `ruff format --check src tests`: pass
- `mypy --strict src tests/unit`: pass
- `pytest -q tests/unit`: pass
- Remaining `type: ignore` suppressions for this package scope: `0`
