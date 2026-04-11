from __future__ import annotations

from pathlib import Path

from epub_translate_cli.cli import _build_command


def test_build_command_sets_reset_resume_state(tmp_path: Path) -> None:
    input_path = tmp_path / "in.epub"
    input_path.write_bytes(b"epub")
    output_path = tmp_path / "out.epub"

    command = _build_command(
        input_path=input_path,
        output_path=output_path,
        source_lang="en",
        target_lang="it",
        model="x",
        temperature=0.2,
        retries=1,
        report_out=None,
        abort_on_error=False,
        log_level="INFO",
        ollama_url="http://localhost:11434",
        workers=1,
        context_paragraphs=3,
        reset_resume_state=True,
    )

    assert command.reset_resume_state is True
    assert command.report_path == output_path.with_suffix(".epub.report.json")
