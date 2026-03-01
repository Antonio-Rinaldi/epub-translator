# epub-translator-cli

Translate an EPUB by translating paragraph text nodes through a local Ollama model and producing:
- a new translated EPUB (`--out`)
- a JSON report (`--report-out` or derived next to `--out`)
- optionally, a folder of per-chapter audio files (`--generate-audiobook`)

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

### Translation only

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
  --ollama-url http://localhost:11434 \
  --workers 1 \
  --context-paragraphs 3
```

### Translation + audiobook

```bash
epub-translate \
  --in ./sample1.epub \
  --out ./sample1.italiano.epub \
  --source-lang en \
  --target-lang it \
  --model translategemma:4b \
  --generate-audiobook \
  --voice-model outetts \
  --voice-ollama-url http://localhost:11434 \
  --audiobook-out ./sample1_audiobook/
```

### Translation flags

| Flag                   | Default                  | Description                                                                                                                |
|------------------------|--------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `--in`                 | *(required)*             | Input EPUB path (must exist). Parent dirs of `--out` are created automatically.                                            |
| `--out`                | *(required)*             | Output translated EPUB path. Parent directories are created automatically.                                                 |
| `--source-lang`        | *(required)*             | Source language (e.g. `en`)                                                                                                |
| `--target-lang`        | *(required)*             | Target language (e.g. `it`)                                                                                                |
| `--model`              | *(required)*             | Ollama model name for translation (`translategemma:4b` is light/fast; `translategemma:12b` is better but slower)           |
| `--temperature`        | `0.2`                    | LLM sampling temperature (0.0–2.0)                                                                                         |
| `--retries`            | `3`                      | Retries per node on transient errors                                                                                       |
| `--report-out`         | derived                  | JSON report path (default: `<out>.report.json`)                                                                            |
| `--abort-on-error`     | `false`                  | Abort and skip saving output if any node fails                                                                             |
| `--log-level`          | `INFO`                   | Logging verbosity (`INFO` or `DEBUG`)                                                                                      |
| `--ollama-url`         | `http://localhost:11434` | Ollama API base URL for the **translation** model                                                                          |
| `--workers`            | `1`                      | Parallel chapter workers (threads)                                                                                         |
| `--context-paragraphs` | `3`                      | Rolling context: number of preceding translated paragraphs sent with each request for tone/terminology continuity          |

### Audiobook flags

Audiobook generation runs **after** translation, using a completely independent model and Ollama instance.
It is skipped silently when `--generate-audiobook` is not set.

| Flag                    | Default                                    | Description                                                                                    |
|-------------------------|--------------------------------------------|------------------------------------------------------------------------------------------------|
| `--generate-audiobook`  | `false`                                    | Enable per-chapter audiobook generation                                                        |
| `--voice-model`         | *(required when `--generate-audiobook`)* | Ollama TTS model name (e.g. `outetts`, `kokoro`)                                               |
| `--voice-ollama-url`    | `http://localhost:11434`                   | Ollama API base URL for the **TTS** model (can differ from `--ollama-url`)                     |
| `--audiobook-out`       | `<out_stem>_audiobook/`                    | Directory for audio files; one `<chapter_stem>.wav` per chapter. Created automatically if absent. |

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
