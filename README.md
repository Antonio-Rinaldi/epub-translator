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
- Ollama running locally (default: `http://localhost:11434`) for translation
- For audiobook generation (optional):
  - `openai-speech` backend (default): [Orpheus-FastAPI](https://github.com/legraphista/LocalOrpheusTTS) or any OpenAI-compatible `/v1/audio/speech` server (default: `http://localhost:5005`)
  - `ollama` backend: an Ollama model that returns audio via `/api/generate`

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

### Translation + audiobook (Orpheus-FastAPI / OpenAI-speech backend)

Start [Orpheus-FastAPI](https://github.com/legraphista/LocalOrpheusTTS) separately (default port `5005`), then:

```bash
epub-translate \
  --in ./sample1.epub \
  --out ./sample1.italiano.epub \
  --source-lang en \
  --target-lang it \
  --model translategemma:12b \
  --generate-audiobook \
  --voice-backend openai-speech \
  --voice-model orpheus \
  --voice tara \
  --voice-base-url http://localhost:5005 \
  --audiobook-out ./sample1_audiobook/
```

### Translation + audiobook (Ollama backend)

```bash
epub-translate \
  --in ./sample1.epub \
  --out ./sample1.italiano.epub \
  --source-lang en \
  --target-lang it \
  --model translategemma:12b \
  --generate-audiobook \
  --voice-backend ollama \
  --voice-model outetts \
  --voice-base-url http://localhost:11434 \
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

Audiobook generation runs **after** translation using a completely independent model and server.
It is skipped when `--generate-audiobook` is not set.

| Flag                   | Default                                          | Description                                                                                                                                  |
|------------------------|--------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| `--generate-audiobook` | `false`                                          | Enable per-chapter audiobook generation                                                                                                      |
| `--voice-model`        | *(required when `--generate-audiobook`)*       | TTS model name (e.g. `orpheus` for Orpheus-FastAPI, `outetts` for Ollama)                                                                    |
| `--voice-backend`      | `openai-speech`                                  | TTS backend: `openai-speech` (calls `POST /v1/audio/speech`, e.g. Orpheus-FastAPI / Kokoro-FastAPI) or `ollama` (calls `/api/generate`)     |
| `--voice-base-url`     | `http://localhost:5005` (openai-speech) / `http://localhost:11434` (ollama) | Base URL of the TTS server. Overrides the per-backend default. |
| `--voice`              | *(backend default)*                              | Voice name passed to the TTS backend (e.g. `tara`, `leo`, `leah` for Orpheus)                                                               |
| `--audiobook-out`      | `<out_stem>_audiobook/`                          | Directory for audio files; one file per non-empty chapter. Created automatically if absent.                                                  |

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
