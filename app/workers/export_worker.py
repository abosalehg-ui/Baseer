"""عامل خلفي لتصدير الدراسة (JSON / CSV / Excel / PDF).

التصدير كان يجري كاملاً في الـmain thread داخل معالج الزر: بناء الدراسة، قراءة
**كل** المخالفات بلا حد، ثم توليد PDF أو Excel. على قاعدة بعشرات الآلاف من
الصفوف تعني هذه نافذة «لا تستجيب» بلا شريط تقدّم ولا إلغاء — وهي العملية الثقيلة
الوحيدة في التطبيق التي بقيت خارج QThread، مع أن README يعلن «لا I/O ثقيل في
main thread» معياراً للجودة.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.dashboard import DashboardService
from app.core.exporter import (
    anonymize_violation_rows,
    build_study,
    export_csv,
    export_excel,
    export_json,
    export_pdf,
)

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS: tuple[str, ...] = ("json", "csv", "xlsx", "pdf")


@dataclass(frozen=True)
class ExportResult:
    """ناتج تصدير واحد."""

    output_path: Path
    fmt: str
    violations: int


class ExportWorker(QObject):
    """يبني الدراسة ويكتب الملف في thread منفصل."""

    progress = pyqtSignal(str)  # وصف المرحلة الحالية
    finished = pyqtSignal(object)  # ExportResult
    failed = pyqtSignal(str)

    def __init__(
        self,
        fmt: str,
        output_path: Path,
        *,
        anonymize: bool = True,
        service: DashboardService | None = None,
    ) -> None:
        super().__init__()
        self._fmt = fmt
        self._output_path = Path(output_path)
        self._anonymize = anonymize
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        """يطلب الإلغاء — يُفحص بين المراحل (كتابة الملف نفسها غير قابلة للتقسيم)."""
        self._cancelled = True

    def run(self) -> None:
        try:
            if self._fmt not in SUPPORTED_FORMATS:
                raise ValueError(f"صيغة تصدير غير مدعومة: {self._fmt}")
            service = self._service or DashboardService()

            self.progress.emit("جمع بيانات الدراسة...")
            study = build_study(service, anonymize=self._anonymize)
            if self._cancelled:
                self.failed.emit("أُلغي التصدير قبل الكتابة")
                return

            self.progress.emit("قراءة المخالفات...")
            violations = service.list_violations()
            if self._anonymize:
                violations = anonymize_violation_rows(violations)
            if self._cancelled:
                self.failed.emit("أُلغي التصدير قبل الكتابة")
                return

            self.progress.emit(f"كتابة الملف ({self._fmt})...")
            self._write(study, violations)
            service.record_export_entry(
                study_name=self._output_path.stem, fmt=self._fmt, output_path=self._output_path
            )
            self.finished.emit(
                ExportResult(
                    output_path=self._output_path, fmt=self._fmt, violations=len(violations)
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل التصدير")
            self.failed.emit(str(exc))

    def _write(self, study: dict, violations: list) -> None:  # type: ignore[type-arg]
        if self._fmt == "json":
            export_json(study, self._output_path)
        elif self._fmt == "csv":
            export_csv(violations, self._output_path)
        elif self._fmt == "xlsx":
            export_excel(study, violations, self._output_path)
        else:
            export_pdf(study, violations, self._output_path)


__all__ = ["SUPPORTED_FORMATS", "ExportResult", "ExportWorker"]
