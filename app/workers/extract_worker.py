"""عامل خلفي لاستخراج المخالفات من دفعة مقاطع.

كان معرَّفاً داخل `app/ui/analysis_view.py` كصنف يرث `QThread` مباشرة، بينما
بقية عمّال التطبيق `QObject` تُشغَّل عبر `app.workers.runner.run_worker`. نمطان
للـthreading في تطبيق واحد يعني أن إصلاح دورة الحياة في أحدهما لا يسري على
الآخر — والنمط القديم يفوته `deleteLater` والإلغاء الموحّد الذي يوفّره
`ThreadHandle`. الوحدة هنا توحّدهما وتُخرج منطق العمل من طبقة العرض.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal

from app.core.analyzer import AnalyzerService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractReport:
    """ملخّص دفعة استخراج — النجاح **والإخفاقات** معاً.

    إرجاع الإخفاقات صراحةً بدل ابتلاعها في السجل يسمح للواجهة بإخبار المستخدم
    لماذا خرج بـ«0 مخالفة» بدل تركه يظن أن التطبيق معطّل.
    """

    total_violations: int = 0
    processed: int = 0
    failures: list[str] = field(default_factory=list)
    cancelled: bool = False


class ExtractWorker(QObject):
    """يستخرج المخالفات لمجموعة مقاطع في thread منفصل."""

    progress = pyqtSignal(int, int, int, int)  # current, total, video_id, count (-1 = فشل)
    finished = pyqtSignal(object)  # ExtractReport
    failed = pyqtSignal(str)

    def __init__(self, video_ids: list[int], *, service: AnalyzerService | None = None) -> None:
        super().__init__()
        self._ids = list(video_ids)
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        """يطلب الإيقاف — يتوقف بعد المقطع الجاري."""
        self._cancelled = True

    def run(self) -> None:
        try:
            service = self._service or AnalyzerService()
            total = 0
            processed = 0
            failures: list[str] = []
            for index, video_id in enumerate(self._ids, start=1):
                if self._cancelled:
                    break
                count = self._extract_one(service, video_id, failures)
                self.progress.emit(index, len(self._ids), video_id, count)
                if count < 0:
                    continue
                total += count
                processed += 1
            self.finished.emit(
                ExtractReport(
                    total_violations=total,
                    processed=processed,
                    failures=failures,
                    cancelled=self._cancelled,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل استخراج المخالفات")
            self.failed.emit(str(exc))

    @staticmethod
    def _extract_one(service: AnalyzerService, video_id: int, failures: list[str]) -> int:
        """عدد المخالفات المستخرجة، أو -1 عند فشل المقطع (يُضاف سببه إلى `failures`)."""
        try:
            count = service.extract_violations(video_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل استخراج المخالفات للمقطع %d", video_id)
            failures.append(f"المقطع #{video_id}: {exc}")
            return -1
        failures.extend(f"المقطع #{video_id} — {f}" for f in service.last_detector_failures)
        return count


__all__ = ["ExtractReport", "ExtractWorker"]
