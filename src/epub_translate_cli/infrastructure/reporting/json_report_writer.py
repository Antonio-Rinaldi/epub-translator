from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from epub_translate_cli.domain.models import RunReport
from epub_translate_cli.domain.ports import ReportWriterPort


@dataclass(frozen=True)
class JsonReportWriter(ReportWriterPort):
    def write(self, report: RunReport, report_path: Path) -> None:
        report_path.parent.mkdir(parents=True, exist_ok=True)

        payload = asdict(report)
        payload["totals"] = report.totals()

        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
