from __future__ import annotations

import typer

from epub_translate_cli.cli import translate


def run() -> None:
    typer.run(translate)
