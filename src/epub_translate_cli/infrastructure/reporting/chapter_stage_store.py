from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from epub_translate_cli.domain.models import (
    ChapterReport,
    NodeChange,
    NodeFailure,
    NodeSkip,
    SkipReason,
    TranslationSettings,
)
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)

_SKIP_REASON_MAP: dict[str, SkipReason] = {
    "protected_code": "protected_code",
    "protected_metadata": "protected_metadata",
    "empty": "empty",
}


@dataclass(frozen=True)
class StagedChapter:
    """Chapter bytes/report snapshot loaded from persistent staging workspace."""

    chapter_index: int
    chapter_path: str
    xhtml_bytes: bytes
    report: ChapterReport
    completed: bool


@dataclass(frozen=True)
class FilesystemChapterStageStore:
    """Filesystem-backed staging store used to resume chapter translation runs."""

    workspace_dir: Path
    signature: dict[str, object]

    @staticmethod
    def workspace_path(report_path: Path) -> Path:
        """Return deterministic workspace path for one report artifact path."""
        return report_path.parent / f".{report_path.name}.chapter-stage"

    @classmethod
    def for_run(
        cls,
        *,
        input_path: Path,
        output_path: Path,
        report_path: Path,
        settings: TranslationSettings,
    ) -> FilesystemChapterStageStore:
        """Build stage store with signature used to validate resume compatibility."""
        input_exists = input_path.exists()
        input_stats = input_path.stat() if input_exists else None
        signature: dict[str, object] = {
            "input_path": str(input_path.resolve()),
            "output_path": str(output_path.resolve()),
            "source_lang": settings.source_lang,
            "target_lang": settings.target_lang,
            "model": settings.model,
            "temperature": settings.temperature,
            "retries": settings.retries,
            "context_paragraphs": settings.context_paragraphs,
            "input_exists": input_exists,
            "input_size": input_stats.st_size if input_stats is not None else 0,
            "input_mtime_ns": input_stats.st_mtime_ns if input_stats is not None else 0,
        }
        return cls(workspace_dir=cls.workspace_path(report_path), signature=signature)

    @property
    def _manifest_path(self) -> Path:
        return self.workspace_dir / "manifest.json"

    def load_completed(self) -> dict[int, StagedChapter]:
        """Load completed chapter snapshots from workspace when signature matches."""
        manifest = self._load_or_reset_manifest()
        chapters_payload = manifest.get("chapters")
        if not isinstance(chapters_payload, dict):
            return {}

        staged_items = [
            self._load_staged_chapter(index_key, payload)
            for index_key, payload in chapters_payload.items()
            if isinstance(index_key, str) and isinstance(payload, dict)
        ]
        return {
            item.chapter_index: item for item in staged_items if item is not None and item.completed
        }

    def save_chapter(
        self,
        *,
        chapter_index: int,
        chapter_path: str,
        xhtml_bytes: bytes,
        report: ChapterReport,
    ) -> None:
        """Persist one translated chapter snapshot and update the manifest atomically."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        chapter_rel = f"chapters/{chapter_index:05d}.xhtml"
        report_rel = f"reports/{chapter_index:05d}.json"

        self._write_bytes_atomic(self.workspace_dir / chapter_rel, xhtml_bytes)
        self._write_text_atomic(
            self.workspace_dir / report_rel,
            json.dumps(
                self._serialize_report(report),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )

        manifest = self._load_or_reset_manifest()
        chapters_payload = manifest.setdefault("chapters", {})
        if not isinstance(chapters_payload, dict):
            chapters_payload = {}
            manifest["chapters"] = chapters_payload
        chapters_payload[str(chapter_index)] = {
            "chapter_path": chapter_path,
            "completed": not report.failures,
            "xhtml": chapter_rel,
            "report": report_rel,
        }
        self._write_manifest(manifest)

    def clear(self) -> None:
        """Remove workspace after successful run output write."""
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def _default_manifest(self) -> dict[str, object]:
        return {
            "version": 1,
            "signature": self.signature,
            "chapters": {},
        }

    def _load_or_reset_manifest(self) -> dict[str, object]:
        if not self._manifest_path.exists():
            manifest = self._default_manifest()
            self._write_manifest(manifest)
            return manifest

        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Resetting invalid stage manifest | path=%s", self._manifest_path)
            return self._reset_manifest()

        if not isinstance(payload, dict):
            return self._reset_manifest()

        signature = payload.get("signature")
        if signature != self.signature:
            logger.info("Resetting stage workspace because run signature changed")
            return self._reset_manifest()

        return payload

    def _reset_manifest(self) -> dict[str, object]:
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._default_manifest()
        self._write_manifest(manifest)
        return manifest

    def _write_manifest(self, payload: dict[str, object]) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._write_text_atomic(
            self._manifest_path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )

    @staticmethod
    def _write_text_atomic(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)

    @staticmethod
    def _write_bytes_atomic(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_bytes(content)
        temp_path.replace(path)

    def _load_staged_chapter(self, index_key: str, payload: dict[str, Any]) -> StagedChapter | None:
        try:
            chapter_index = int(index_key)
        except ValueError:
            return None

        chapter_path = payload.get("chapter_path")
        xhtml_rel = payload.get("xhtml")
        report_rel = payload.get("report")
        completed = payload.get("completed")
        if not (
            isinstance(chapter_path, str)
            and isinstance(xhtml_rel, str)
            and isinstance(report_rel, str)
            and isinstance(completed, bool)
        ):
            return None

        xhtml_path = self.workspace_dir / xhtml_rel
        report_path = self.workspace_dir / report_rel
        if not (xhtml_path.exists() and report_path.exists()):
            return None

        try:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

        if not isinstance(report_payload, dict):
            return None

        report = self._deserialize_report(report_payload, chapter_path)
        return StagedChapter(
            chapter_index=chapter_index,
            chapter_path=chapter_path,
            xhtml_bytes=xhtml_path.read_bytes(),
            report=report,
            completed=completed,
        )

    @staticmethod
    def _serialize_report(report: ChapterReport) -> dict[str, object]:
        return {
            "chapter_path": report.chapter_path,
            "changes": [
                {
                    "chapter_path": item.chapter_path,
                    "node_path": item.node_path,
                    "before": item.before,
                    "after": item.after,
                }
                for item in report.changes
            ],
            "failures": [
                {
                    "chapter_path": item.chapter_path,
                    "node_path": item.node_path,
                    "text": item.text,
                    "error_type": item.error_type,
                    "message": item.message,
                    "attempts": item.attempts,
                }
                for item in report.failures
            ],
            "skips": [
                {
                    "chapter_path": item.chapter_path,
                    "node_path": item.node_path,
                    "reason": item.reason,
                }
                for item in report.skips
            ],
        }

    @staticmethod
    def _deserialize_report(payload: dict[str, object], chapter_path: str) -> ChapterReport:
        def _skip_reason(raw_reason: object) -> SkipReason:
            return _SKIP_REASON_MAP.get(str(raw_reason), "empty")

        changes_raw = payload.get("changes")
        failures_raw = payload.get("failures")
        skips_raw = payload.get("skips")
        changes = (
            [
                NodeChange(
                    chapter_path=str(item.get("chapter_path", chapter_path)),
                    node_path=str(item.get("node_path", "")),
                    before=str(item.get("before", "")),
                    after=str(item.get("after", "")),
                )
                for item in changes_raw
                if isinstance(item, dict)
            ]
            if isinstance(changes_raw, list)
            else []
        )
        failures = (
            [
                NodeFailure(
                    chapter_path=str(item.get("chapter_path", chapter_path)),
                    node_path=str(item.get("node_path", "")),
                    text=str(item.get("text", "")),
                    error_type=str(item.get("error_type", "UnknownError")),
                    message=str(item.get("message", "unknown")),
                    attempts=int(item.get("attempts", 0)),
                )
                for item in failures_raw
                if isinstance(item, dict)
            ]
            if isinstance(failures_raw, list)
            else []
        )
        skips = (
            [
                NodeSkip(
                    chapter_path=str(item.get("chapter_path", chapter_path)),
                    node_path=str(item.get("node_path", "")),
                    reason=_skip_reason(item.get("reason", "empty")),
                )
                for item in skips_raw
                if isinstance(item, dict)
            ]
            if isinstance(skips_raw, list)
            else []
        )
        return ChapterReport(
            chapter_path=str(payload.get("chapter_path", chapter_path)),
            changes=changes,
            failures=failures,
            skips=skips,
        )
