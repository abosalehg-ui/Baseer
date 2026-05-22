"""عامل خلفي لاستيراد المقاطع — يعمل في QThread."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

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
        path: Path,
        source_type: SourceType,
        *,
        generate_thumbnails: bool = True,
        service: LibraryService | None = None,
    ) -> None:
        super().__init__()
        self._path = path
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
            report = service.import_path(
                self._path,
                self._source_type,
                generate_thumbnails=self._generate_thumbnails,
                progress_cb=self._on_progress,
            )
            self.finished.emit(report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل الاستيراد")
            self.failed.emit(str(exc))

    def _on_progress(self, current: int, total: int, filename: str) -> None:
        if self._cancelled:
            raise InterruptedError("أُلغيت العملية من قبل المستخدم")
        self.progress.emit(current, total, filename)


def start_import_in_thread(
    path: Path,
    source_type: SourceType,
    *,
    generate_thumbnails: bool = True,
    on_progress: object = None,
    on_finished: object = None,
    on_failed: object = None,
) -> tuple[QThread, ImportWorker]:
    """يبدأ عملية استيراد في QThread جديد ويعيد (thread, worker).

    على المستدعي الاحتفاظ بمراجع `thread` و `worker` حتى لا يُجمع garbage collector.
    """
    thread = QThread()
    worker = ImportWorker(path, source_type, generate_thumbnails=generate_thumbnails)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    if on_progress is not None:
        worker.progress.connect(on_progress)
    if on_finished is not None:
        worker.finished.connect(on_finished)
    if on_failed is not None:
        worker.failed.connect(on_failed)

    thread.start()
    return thread, worker


__all__ = ["ImportReport", "ImportWorker", "start_import_in_thread"]
