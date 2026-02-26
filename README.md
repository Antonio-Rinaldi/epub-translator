# epub-translator-cli

Translate an EPUB by translating paragraph text nodes through a local Ollama model and producing:
- a new EPUB (`--out`)
- a JSON report (`--report-out` or derived next to `--out`)

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

## Requirements
- Python 3.9+
- Ollama running locally (default: `http://localhost:11434`)

## Usage

```bash
epub-translate \
--in ./sample1.epub \
--out ./sample1.italiano.epub \
--source-lang en \
--target-lang it \
--model translategemma:4b \
--temperature 0.2 \
--retries 3 \
--log-level DEBUG \
--ollama-url http://localhost:11434
```

| Flag               | Default                  | Description                                                                 |
|--------------------|--------------------------|-----------------------------------------------------------------------------|
| `--in`             | *(required)*             | Input EPUB path                                                             |
| `--out`            | *(required)*             | Output EPUB path                                                            |
| `--source-lang`    | *(required)*             | Source language (e.g. `en`)                                                 |
| `--target-lang`    | *(required)*             | Target language (e.g. `it`)                                                 |
| `--model`          | *(required)*             | Ollama model name (translategemma:4b is light, fast and gives fine results) |
| `--temperature`    | `0.2`                    | LLM sampling temperature (0.0–2.0)                                          |
| `--retries`        | `3`                      | Retries per node on transient errors                                        |
| `--report-out`     | derived                  | JSON report path (default: `<out>.report.json`)                             |
| `--abort-on-error` | `false`                  | Abort and skip saving output if any node fails                              |
| `--log-level`      | `INFO`                   | Logging verbosity (`INFO` or `DEBUG`)                                       |
| `--ollama-url`     | `http://localhost:11434` | Ollama API base URL                                                         |

### Logging
- Default level is `INFO`
- Set `--log-level DEBUG` for detailed runtime diagnostics (chapter internals, retries, Ollama call metadata)

### Safety rules
This tool avoids translating protected content:
- code blocks (`<code>`, `<pre>`)
- metadata-ish containers (`<head>`, `<title>`, `<style>`, `<script>`)

All other content is translated, including links, footnotes, and endnotes.

## Exit codes
- `0`: success
- `1`: fatal error
- `2`: finished processing but did not write output due to `--abort-on-error` and failures
