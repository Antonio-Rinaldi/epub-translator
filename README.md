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
- Ollama running locally

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
--log-level DEBUG
```

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
