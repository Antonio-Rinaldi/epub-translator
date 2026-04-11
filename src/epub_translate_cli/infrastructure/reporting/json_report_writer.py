from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from epub_translate_cli.domain.models import RunReport
from epub_translate_cli.domain.ports import ReportWriterPort
from epub_translate_cli.infrastructure.logging.logger_factory import create_logger

logger = create_logger(__name__)


@dataclass(frozen=True)
class JsonReportWriter(ReportWriterPort):
    """Report writer that serializes run reports to UTF-8 JSON files."""

    @staticmethod
    def _payload(report: RunReport) -> dict[str, object]:
        """Build serializable payload including computed totals section."""
        payload = asdict(report)
        payload["totals"] = report.totals()
        return payload

    def write(self, report: RunReport, report_path: Path) -> None:
        """Write report payload to disk, creating parent directories when needed."""
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(self._payload(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Report written | path=%s", report_path)
