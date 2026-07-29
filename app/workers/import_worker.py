"""عامل خلفي لاستيراد المقاطع — يعمل في QThread."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from app.constants import SourceType
from app.core.library import ImportReport, LibraryService

logger = logging.getLogger(__name__)


class ImportWorker(QObject):
    """عامل يستورد مقاطع من مسار في thread منفصل."""

    progress = pyqtSignal(int, int, str)  # current, total, filename
    finished = pyqtSignal(object)  # ImportReport
    failed = pyqtSignal(str)

    def __init__(
        self,
        path: Path | list[Path],
        source_type: SourceType,
        *,
        generate_thumbnails: bool = True,
        service: LibraryService | None = None,
    ) -> None:
        super().__init__()
        # نقبل مساراً واحداً أو قائمة مسارات (للإسقاط/الاختيار المتعدد)
        self._paths: list[Path] = [path] if isinstance(path, Path) else list(path)
        self._source_type = source_type
        self._generate_thumbnails = generate_thumbnails
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        """يطلب إلغاء العملية (تُفحص الحالة بين الملفات)."""
        self._cancelled = True

    def run(self) -> None:
        """نقطة الدخول — تُستدعى عبر QThread.started → slot."""
        try:
            service = self._service or LibraryService()
            report = service.import_paths(
                list(self._paths),
                self._source_type,
                generate_thumbnails=self._generate_thumbnails,
                progress_cb=self._on_progress,
                should_stop=lambda: self._cancelled,
            )
            # الإلغاء ينتهي بـ`finished` مع تقرير جزئي (report.cancelled=True)
            # لا بـ`failed` — إيقاف المستخدم لعملية ليس خطأً.
            self.finished.emit(report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل الاستيراد")
            self.failed.emit(str(exc))

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        self.progress.emit(current, total, filename)


__all__ = ["ImportReport", "ImportWorker"]
