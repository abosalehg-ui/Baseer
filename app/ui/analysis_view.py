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
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.constants import VIOLATION_ARABIC_NAMES, ViolationType
from app.core.analyzer import AnalyzerService
from app.ui.dialogs import ManualViolationDialog

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

        # أزرار التدخل البشري (يدوي)
        self._add_manual_btn = QPushButton("➕ إضافة مخالفة يدوية", self)
        self._add_manual_btn.clicked.connect(self._on_add_manual)
        bar.addWidget(self._add_manual_btn)

        self._edit_btn = QPushButton("✏️ تعديل", self)
        self._edit_btn.clicked.connect(self._on_edit_violation)
        bar.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("🗑️ حذف", self)
        self._delete_btn.clicked.connect(self._on_delete_violation)
        bar.addWidget(self._delete_btn)

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

        # جدول المخالفات الفردية (قابل للتعديل/الحذف)
        self._violations_label = QLabel("المخالفات المُسجّلة:", self)
        root.addWidget(self._violations_label)
        self._violations_table = QTableWidget(self)
        self._violations_table.setColumnCount(8)
        self._violations_table.setHorizontalHeaderLabels(
            [
                "المعرّف",
                "المقطع",
                "النوع",
                "البداية (ms)",
                "النهاية (ms)",
                "اللوحة",
                "المصدر",
                "الملاحظات",
            ]
        )
        self._violations_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._violations_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._violations_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self._violations_table, stretch=2)

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
        """يُحدّث جدول المخالفات الفردية."""
        rows = self._service._db.fetch_all(  # noqa: SLF001
            "SELECT vi.id, v.filename, vi.violation_type, vi.start_ms, vi.end_ms, "
            "COALESCE(vi.license_plate, ''), COALESCE(vi.source, 'auto'), COALESCE(vi.notes, '') "
            "FROM violations vi LEFT JOIN videos v ON v.id = vi.video_id "
            "ORDER BY vi.id DESC LIMIT 500"
        )
        self._violations_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                # نترجم نوع المخالفة إلى عربي
                display = val
                if c == 2:
                    try:
                        display = VIOLATION_ARABIC_NAMES[ViolationType(str(val))]
                    except (KeyError, ValueError):
                        display = str(val)
                elif c == 6:
                    display = "يدوي" if str(val) == "manual" else "تلقائي"
                self._violations_table.setItem(r, c, QTableWidgetItem(str(display)))
        self._violations_table.resizeColumnsToContents()

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

    # ============================================
    # التدخل البشري — إضافة/تعديل/حذف يدوي
    # ============================================
    def _load_videos_for_dialog(self) -> list[tuple[int, str]]:
        rows = self._service._db.fetch_all(  # noqa: SLF001
            "SELECT id, filename FROM videos ORDER BY id"
        )
        return [(int(r[0]), str(r[1])) for r in rows]

    def _on_add_manual(self) -> None:
        videos = self._load_videos_for_dialog()
        if not videos:
            QMessageBox.information(self, "لا توجد مقاطع", "يجب استيراد مقطع واحد على الأقل.")
            return
        dlg = ManualViolationDialog(
            videos=videos, parent=self, db=self._service._db  # noqa: SLF001
        )
        if dlg.exec() == ManualViolationDialog.DialogCode.Accepted:
            self._status.setText("تمت إضافة مخالفة يدوية")
            self.refresh()

    def _selected_violation_id(self) -> int | None:
        selection = (
            self._violations_table.selectionModel().selectedRows()
            if self._violations_table.selectionModel()
            else []
        )
        if not selection:
            QMessageBox.information(self, "اختر مخالفة", "حدد مخالفة واحدة من الجدول.")
            return None
        row = selection[0].row()
        return int(self._violations_table.item(row, 0).text())

    def _on_edit_violation(self) -> None:
        viol_id = self._selected_violation_id()
        if viol_id is None:
            return
        row = self._service._db.fetch_one(  # noqa: SLF001
            "SELECT id, video_id, violation_type, start_ms, end_ms, "
            "license_plate, notes FROM violations WHERE id = ?",
            (viol_id,),
        )
        if row is None:
            QMessageBox.warning(self, "غير موجودة", "المخالفة المختارة غير موجودة.")
            return
        existing = {
            "id": int(row[0]),
            "video_id": int(row[1]),
            "violation_type": str(row[2]),
            "start_ms": int(row[3] or 0),
            "end_ms": int(row[4] or 0),
            "license_plate": row[5],
            "notes": row[6],
        }
        videos = self._load_videos_for_dialog()
        dlg = ManualViolationDialog(
            videos=videos, parent=self, existing=existing, db=self._service._db  # noqa: SLF001
        )
        if dlg.exec() == ManualViolationDialog.DialogCode.Accepted:
            self._status.setText(f"تم تعديل المخالفة #{viol_id}")
            self.refresh()

    def _on_delete_violation(self) -> None:
        viol_id = self._selected_violation_id()
        if viol_id is None:
            return
        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"هل تريد حذف المخالفة #{viol_id}؟ لا يمكن التراجع.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._service._db.execute("DELETE FROM violations WHERE id = ?", (viol_id,))  # noqa: SLF001
        self._status.setText(f"تم حذف المخالفة #{viol_id}")
        self.refresh()
