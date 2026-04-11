from __future__ import annotations

import typer

from epub_translate_cli.cli import translate


def run() -> None:
    """Run Typer CLI entrypoint for EPUB translation command."""
    typer.run(translate)
