# epub-translator-cli

Translate EPUB content with a local Ollama model while preserving EPUB structure and producing both translated output and a detailed processing report.

## Core Features

- Parses EPUB items and chapter XHTML documents.
- Translates narratable text nodes with retry handling.
- Preserves inline formatting and surrounding markup.
- Applies rolling context from previous translated paragraphs for style consistency.
- Skips protected non-translatable content (`code`, `pre`, metadata containers).
- Writes translated EPUB plus JSON report (timings, failures, skipped nodes).
- Supports parallel chapter workers.

## Why These Choices Were Made

- **Node-level translation**: minimizes markup breakage and makes failures local/recoverable.
- **Rolling context**: improves consistency for names, terminology, and tone between adjacent paragraphs.
- **Explicit skip rules**: prevents corruption of technical/code/meta content.
- **Report artifact**: production-friendly observability and post-run auditability.

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

## Requirements

- Python 3.9+
- Ollama reachable (default: `http://localhost:11434`)
- A translation-capable model available in Ollama

## Quick Start

```bash
epub-translate \
  --in ./sample1.epub \
  --out ./sample1.italiano.epub \
  --source-lang en \
  --target-lang it \
  --model translategemma:4b \
  --temperature 0.2 \
  --retries 3 \
  --workers 1 \
  --context-paragraphs 3 \
  --log-level DEBUG
```

## CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--in` | *(required)* | Input EPUB path. |
| `--out` | *(required)* | Output translated EPUB path. |
| `--source-lang` | *(required)* | Source language code or label. |
| `--target-lang` | *(required)* | Target language code or label. |
| `--model` | *(required)* | Ollama model id used for translation. |
| `--temperature` | `0.2` | Sampling temperature. |
| `--retries` | `3` | Retries per node on transient failures. |
| `--report-out` | derived | Report path (`<out>.report.json` if omitted). |
| `--abort-on-error` | `false` | If true, do not save translated EPUB when any error remains. |
| `--log-level` | `INFO` | `INFO` or `DEBUG`. |
| `--ollama-url` | `http://localhost:11434` | Ollama base URL. |
| `--workers` | `1` | Parallel chapter workers (thread pool). |
| `--context-paragraphs` | `3` | Number of previous translated paragraphs used as rolling context. |

## Translation Rules and Safety

### Protected from translation

- `<code>`, `<pre>`
- `<head>`, `<title>`, `<style>`, `<script>`

### Translated

- Paragraph-like text nodes in chapter content
- Links, notes, endnotes, and common narrative structures

### Formatting behavior

- Keeps original XHTML skeleton and inline structure.
- Updates text content while preserving tags/attributes.

## Outputs

- `--out`: translated EPUB file.
- `--report-out` (or `<out>.report.json`): structured report with status and diagnostics.

## Failure Semantics

- With `--abort-on-error=false`: writes EPUB even if some nodes fail, and reports failures.
- With `--abort-on-error=true`: exits with failure status and does not write final EPUB when unresolved errors remain.

## Detailed Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as epub-translate CLI
    participant Orch as Translation Orchestrator
    participant Repo as EPUB Repository
    participant Parse as XHTML Parser/Walker
    participant Ctx as Rolling Context Buffer
    participant LLM as Ollama Translation Client
    participant Save as EPUB Writer
    participant Report as JSON Report Writer

    User->>CLI: run command (--in, --out, langs, model, retries, workers)
    CLI->>CLI: validate inputs and derive report path
    CLI->>Orch: translate(...settings...)

    Orch->>Repo: load EPUB
    Repo-->>Orch: items + chapters

    loop each chapter (possibly parallel)
        Orch->>Parse: walk translatable nodes
        loop each eligible text node
            Orch->>Ctx: build prompt context from previous translated paragraphs
            Ctx-->>Orch: context snippet

            loop attempts up to retries
                Orch->>LLM: translate node text with context
                alt success
                    LLM-->>Orch: translated text
                    Orch->>Parse: inject translated text back into node
                    Orch->>Ctx: append translated paragraph
                    break
                else transient error
                    LLM-->>Orch: retryable error
                    Orch->>Orch: retry
                else non-retryable error
                    LLM-->>Orch: failure
                    Orch->>Report: record node failure
                    break
                end
            end
        end
    end

    alt no fatal policy violation
        Orch->>Save: serialize translated EPUB to --out
        Save-->>Orch: written
    else abort-on-error with unresolved failures
        Orch->>Orch: skip EPUB save
    end

    Orch->>Report: write report JSON
    Orch-->>CLI: final status + stats
    CLI-->>User: exit code and summary
```

## Logging and Exit Codes

- Default level: `INFO`
- Verbose diagnostics: `--log-level DEBUG`
- Exit codes:
  - `0`: success
  - `1`: fatal error
  - `2`: processing completed but output not written due to `--abort-on-error` and failures
