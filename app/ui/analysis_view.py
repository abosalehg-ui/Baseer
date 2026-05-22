"""واجهة التحليل — استخراج المخالفات من كل المقاطع المُحلَّلة."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.constants import VIOLATION_ARABIC_NAMES, ViolationType
from app.core.analyzer import AnalyzerService

logger = logging.getLogger(__name__)


class _ExtractWorker(QThread):
    """يستخرج المخالفات لمجموعة مقاطع في background."""

    progress = pyqtSignal(int, int, int, int)  # current, total, video_id, count
    finished_all = pyqtSignal(int, int)  # total_violations, processed_videos
    failed = pyqtSignal(str)

    def __init__(self, video_ids: list[int], service: AnalyzerService) -> None:
        super().__init__()
        self._ids = video_ids
        self._service = service
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D401
        try:
            total = 0
            processed = 0
            for i, vid in enumerate(self._ids, start=1):
                if self._cancelled:
                    break
                try:
                    count = self._service.extract_violations(vid)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("فشل استخراج المخالفات للمقطع %d: %s", vid, exc)
                    self.progress.emit(i, len(self._ids), vid, -1)
                    continue
                total += count
                processed += 1
                self.progress.emit(i, len(self._ids), vid, count)
            self.finished_all.emit(total, processed)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل عامل استخراج المخالفات")
            self.failed.emit(str(exc))


class AnalysisView(QWidget):
    """تبويب التحليل."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._service = AnalyzerService()
        self._worker: _ExtractWorker | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # شريط أزرار
        bar = QHBoxLayout()
        self._run_btn = QPushButton("استخراج المخالفات لكل المقاطع", self)
        self._run_btn.clicked.connect(self._on_extract_all)
        bar.addWidget(self._run_btn)

        self._run_selected_btn = QPushButton("استخراج المختارة", self)
        self._run_selected_btn.clicked.connect(self._on_extract_selected)
        bar.addWidget(self._run_selected_btn)

        refresh_btn = QPushButton("تحديث", self)
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)

        bar.addStretch()
        root.addLayout(bar)

        # شريط تقدم
        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        self._status = QLabel("جاهز", self)
        root.addWidget(self._status)

        # جدول المقاطع
        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            ["المعرّف", "اسم الملف", "حالة المقطع", "عدد الكشوفات", "عدد المخالفات"]
        )
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self._table, stretch=2)

        # جدول ملخّص المخالفات حسب النوع
        self._summary_label = QLabel("ملخّص المخالفات حسب النوع:", self)
        root.addWidget(self._summary_label)
        self._summary = QTextEdit(self)
        self._summary.setReadOnly(True)
        self._summary.setMaximumHeight(150)
        root.addWidget(self._summary, stretch=1)

    # ============================================
    # عرض
    # ============================================
    def refresh(self) -> None:
        rows = self._service._db.fetch_all(  # noqa: SLF001
            "SELECT v.id, v.filename, v.status, "
            "COALESCE((SELECT COUNT(*) FROM detections d WHERE d.video_id = v.id), 0), "
            "COALESCE((SELECT COUNT(*) FROM violations vi WHERE vi.video_id = v.id), 0) "
            "FROM videos v ORDER BY v.id"
        )
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(str(val)))
        self._table.resizeColumnsToContents()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        rows = self._service._db.fetch_all(  # noqa: SLF001
            "SELECT violation_type, COUNT(*) FROM violations "
            "GROUP BY violation_type ORDER BY COUNT(*) DESC"
        )
        if not rows:
            self._summary.setText("لا توجد مخالفات مُستخرَجة بعد.")
            return
        lines: list[str] = ["<b>مخالفة | عدد</b>"]
        for vtype, count in rows:
            try:
                arabic = VIOLATION_ARABIC_NAMES[ViolationType(vtype)]
            except (KeyError, ValueError):
                arabic = str(vtype)
            lines.append(f"{arabic}: {count}")
        self._summary.setHtml("<br>".join(lines))

    # ============================================
    # تشغيل
    # ============================================
    def _on_extract_all(self) -> None:
        rows = self._service._db.fetch_all("SELECT id FROM videos ORDER BY id")  # noqa: SLF001
        ids = [int(r[0]) for r in rows]
        if not ids:
            QMessageBox.information(self, "لا توجد مقاطع", "لا توجد مقاطع مستوردة.")
            return
        self._start_extraction(ids)

    def _on_extract_selected(self) -> None:
        selection = (
            self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        )
        ids = [int(self._table.item(idx.row(), 0).text()) for idx in selection]
        if not ids:
            QMessageBox.information(self, "اختر مقاطع", "حدد مقطعاً واحداً على الأقل.")
            return
        self._start_extraction(ids)

    def _start_extraction(self, ids: list[int]) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "العملية تعمل", "هناك عملية استخراج جارية.")
            return
        self._progress.setVisible(True)
        self._progress.setRange(0, len(ids))
        self._progress.setValue(0)
        self._status.setText(f"بدء استخراج المخالفات لـ {len(ids)} مقطع...")

        worker = _ExtractWorker(ids, self._service)
        worker.progress.connect(self._on_progress)
        worker.finished_all.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _on_progress(self, current: int, total: int, video_id: int, count: int) -> None:
        self._progress.setValue(current)
        if count >= 0:
            self._status.setText(f"({current}/{total}) المقطع #{video_id}: {count} مخالفة")
        else:
            self._status.setText(f"({current}/{total}) المقطع #{video_id}: ✗ فشل")

    def _on_finished(self, total: int, processed: int) -> None:
        self._progress.setVisible(False)
        self._status.setText(f"اكتمل — {total} مخالفة من {processed} مقطع")
        self._worker = None
        self.refresh()

    def _on_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status.setText("فشل الاستخراج")
        QMessageBox.critical(self, "فشل", message)
        self._worker = None
