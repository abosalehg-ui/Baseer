"""واجهة التحليل — استخراج المخالفات من كل المقاطع المُحلَّلة."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
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
from app.core.dashboard import DashboardService
from app.core.library import LibraryService
from app.core.readiness import VideoReadiness
from app.ui.dialogs import ManualViolationDialog
from app.workers.extract_worker import ExtractReport, ExtractWorker
from app.workers.runner import ThreadHandle, run_worker

logger = logging.getLogger(__name__)

# سقف صفوف جدول المخالفات — يُعرض مع الإجمالي بدل بتر صامت
VIOLATIONS_PAGE_SIZE = 500


def _stretch_text_columns(table: QTableWidget, *, text_columns: tuple[int, ...]) -> None:
    """يجعل الأعمدة النصية تتمدّد مع النافذة والرقمية بحجم محتواها.

    `resizeColumnsToContents()` وحده كان يجعل عرض الجدول تابعاً للمحتوى لا
    للنافذة، فاسم ملف طويل يُخرج الجدول عن حدود الشاشة ويظهر شريط تمرير أفقي
    بدل استغلال المساحة المتاحة.
    """
    header = table.horizontalHeader()
    if header is None:
        return
    for col in range(table.columnCount()):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if col in text_columns
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(col, mode)


def _violation_type_label(value: str) -> str:
    """الاسم العربي لنوع المخالفة، أو الرمز كما هو لو غير معروف."""
    try:
        return VIOLATION_ARABIC_NAMES[ViolationType(value)]
    except (KeyError, ValueError):
        return value


def _readiness_item(readiness: VideoReadiness | None) -> QTableWidgetItem:
    """خلية عمود «الجاهزية» مع tooltip يسمّي الكواشف المعطّلة وسببها."""
    if readiness is None:  # صف حُذف بين الاستعلامين
        return QTableWidgetItem("—")
    item = QTableWidgetItem(readiness.summary)
    blocked = readiness.blocked_detectors
    item.setToolTip(
        "كواشف معطّلة:\n• " + "\n• ".join(blocked)
        if blocked
        else "كل المتطلبات متوفّرة — لا كواشف معطّلة"
    )
    return item


class AnalysisView(QWidget):
    """تبويب التحليل."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._service = AnalyzerService()
        # الاستعلامات تمرّ عبر الخدمات لا عبر `_db` الخاص بها — طبقة العرض
        # يجب ألا تحتوي SQL خاماً (راجع docs/architecture.md).
        self._library = LibraryService()
        self._violations = DashboardService()
        self._extract: ThreadHandle | None = None
        self._build_ui()
        self.refresh()

    def background_handles(self) -> list[ThreadHandle]:
        """مقابض العمّال الجارية — يقرأها `MainWindow.closeEvent` قبل إغلاق القاعدة."""
        return [self._extract] if self._extract is not None else []

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addLayout(self._build_toolbar())

        # شريط تقدم
        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        self._status = QLabel("جاهز", self)
        root.addWidget(self._status)

        root.addWidget(self._build_videos_table(), stretch=2)

        self._violations_label = QLabel("المخالفات المُسجّلة:", self)
        root.addWidget(self._violations_label)
        root.addWidget(self._build_violations_table(), stretch=2)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._run_btn = QPushButton("استخراج المخالفات لكل المقاطع", self)
        self._run_btn.clicked.connect(self._on_extract_all)
        bar.addWidget(self._run_btn)

        self._run_selected_btn = QPushButton("استخراج المختارة", self)
        self._run_selected_btn.clicked.connect(self._on_extract_selected)
        bar.addWidget(self._run_selected_btn)

        self._stop_btn = QPushButton("⏹ إيقاف", self)
        self._stop_btn.setToolTip("إيقاف الاستخراج بعد المقطع الحالي")
        self._stop_btn.setAccessibleName("إيقاف استخراج المخالفات")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_extraction)
        bar.addWidget(self._stop_btn)

        refresh_btn = QPushButton("تحديث", self)
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)

        self._zones_btn = QPushButton("🗺️ تحرير المناطق", self)
        self._zones_btn.setToolTip("رسم مناطق (خط توقف/ممنوع الوقوف/خط مسار) للمقطع المختار")
        self._zones_btn.clicked.connect(self._on_edit_zones)
        bar.addWidget(self._zones_btn)

        self._calib_btn = QPushButton("📏 معايرة", self)
        self._calib_btn.setToolTip("معايرة المقطع المختار (لازمة لكاشفي السرعة والمسافة)")
        self._calib_btn.clicked.connect(self._on_calibrate)
        bar.addWidget(self._calib_btn)

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
        return bar

    def _build_videos_table(self) -> QTableWidget:
        """جدول المقاطع — عمود «الجاهزية» يُظهر أي متطلبات الكواشف ناقصة قبل
        الضغط على استخراج، بدل ترك المستخدم أمام «0 مخالفة» بلا تفسير."""
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            [
                "المعرّف",
                "اسم الملف",
                "حالة المقطع",
                "عدد الكشوفات",
                "عدد المخالفات",
                "الجاهزية",
            ]
        )
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setAccessibleName("جدول المقاطع وجاهزيتها للاستخراج")
        _stretch_text_columns(self._table, text_columns=(1, 5))
        return self._table

    def _build_violations_table(self) -> QTableWidget:
        """جدول المخالفات الفردية (قابل للتعديل/الحذف)."""
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
        self._violations_table.setAlternatingRowColors(True)
        self._violations_table.setAccessibleName("جدول المخالفات المسجّلة")
        _stretch_text_columns(self._violations_table, text_columns=(1, 2, 7))
        return self._violations_table

    # ============================================
    # عرض
    # ============================================
    def refresh(self) -> None:
        rows = self._library.video_summaries()
        # استعلام مجمَّع واحد بدل خمس عمليات I/O لكل صف في الـmain thread:
        # مكتبة 500 مقطع كانت تعني ~2500 استعلام + 500 stat عند كل تحديث.
        readiness = self._service.readiness_bulk([int(r[0]) for r in rows])
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(str(val)))
            self._table.setItem(r, 5, _readiness_item(readiness.get(int(row[0]))))
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """يُحدّث جدول المخالفات الفردية."""
        rows = self._violations.list_violations_for_editing(limit=VIOLATIONS_PAGE_SIZE)
        total = self._violations.count_violations()
        self._violations_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = (
                str(row.id),
                row.video_filename,
                _violation_type_label(row.violation_type),
                str(row.start_ms),
                str(row.end_ms),
                row.license_plate,
                "يدوي" if row.source == "manual" else "تلقائي",
                row.notes,
            )
            for c, text in enumerate(cells):
                self._violations_table.setItem(r, c, QTableWidgetItem(text))
        # البتر الصامت عند 500 صف كان يوهم المستخدم أن هذا كل ما لديه
        if total > len(rows):
            self._violations_label.setText(
                f"المخالفات المُسجّلة: عرض {len(rows)} من {total} (الأحدث أولاً)"
            )
        else:
            self._violations_label.setText(f"المخالفات المُسجّلة: {total}")

    # ============================================
    # تشغيل
    # ============================================
    def _on_extract_all(self) -> None:
        ids = [vid for vid, _name in self._library.video_names()]
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
        if self._extract is not None and self._extract.is_running():
            QMessageBox.information(self, "العملية تعمل", "هناك عملية استخراج جارية.")
            return
        self._progress.setVisible(True)
        self._progress.setRange(0, len(ids))
        self._progress.setValue(0)
        self._status.setText(f"بدء استخراج المخالفات لـ {len(ids)} مقطع...")
        self._run_btn.setEnabled(False)
        self._run_selected_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        self._extract = run_worker(
            ExtractWorker(ids, service=self._service),
            parent=self,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
            signal_bindings={"progress": self._on_progress},
        )

    def _on_stop_extraction(self) -> None:
        """يطلب إيقاف الاستخراج — يتوقف بعد المقطع الجاري."""
        if self._extract is not None and self._extract.cancel():
            self._stop_btn.setEnabled(False)
            self._status.setText("جارٍ الإيقاف بعد المقطع الحالي...")

    def _on_progress(self, current: int, total: int, video_id: int, count: int) -> None:
        self._progress.setValue(current)
        if count >= 0:
            self._status.setText(f"({current}/{total}) المقطع #{video_id}: {count} مخالفة")
        else:
            self._status.setText(f"({current}/{total}) المقطع #{video_id}: ✗ فشل")

    def _on_finished(self, report: object) -> None:
        self._progress.setVisible(False)
        self._reset_action_buttons()
        self._extract = None
        if not isinstance(report, ExtractReport):  # pragma: no cover - حماية توقيع الإشارة
            self.refresh()
            return
        prefix = "أُوقف" if report.cancelled else "اكتمل"
        status = f"{prefix} — {report.total_violations} مخالفة من {report.processed} مقطع"
        if report.failures:
            status += f" • {len(report.failures)} إخفاق"
        self._status.setText(status)
        self.refresh()

        # صفر مخالفة بلا تفسير هو أسوأ مخرَج ممكن — نعرض السبب المحتمل
        if report.failures:
            self._show_failures(report.failures)
        elif report.total_violations == 0 and report.processed > 0:
            self._explain_zero_violations()

    def _show_failures(self, failures: list[str]) -> None:
        shown = failures[:10]
        extra = "" if len(failures) <= 10 else f"\n\n(و{len(failures) - 10} إخفاقاً آخر في السجل)"
        QMessageBox.warning(
            self,
            "اكتمل مع إخفاقات",
            "تعذّر تشغيل بعض الكواشف:\n\n• " + "\n• ".join(shown) + extra,
        )

    def _explain_zero_violations(self) -> None:
        """يشرح لماذا لم تُستخرَج أي مخالفة بدل ترك المستخدم يخمّن."""
        ids = [vid for vid, _name in self._library.video_names()]
        blocked: list[str] = []
        for readiness in self._service.readiness_bulk(ids).values():
            blocked.extend(readiness.blocked_detectors)
        if not blocked:
            return
        unique = list(dict.fromkeys(blocked))[:8]
        QMessageBox.information(
            self,
            "لم تُكتشف أي مخالفة",
            "اكتمل الاستخراج دون مخالفات. الكواشف التالية معطّلة لنقص متطلباتها:\n\n• "
            + "\n• ".join(unique)
            + "\n\nاستخدم «🗺️ تحرير المناطق» و«📏 معايرة» لتفعيلها.",
        )

    def _reset_action_buttons(self) -> None:
        self._run_btn.setEnabled(True)
        self._run_selected_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _on_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._reset_action_buttons()
        self._status.setText("فشل الاستخراج")
        QMessageBox.critical(self, "فشل", message)
        self._extract = None

    # ============================================
    # التدخل البشري — إضافة/تعديل/حذف يدوي
    # ============================================
    def _load_videos_for_dialog(self) -> list[tuple[int, str]]:
        return self._library.video_names()

    def _selected_video_id(self) -> int | None:
        """معرّف المقطع المختار في جدول المقاطع (أعلى الشاشة)."""
        selection = (
            self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        )
        if not selection:
            QMessageBox.information(self, "اختر مقطعاً", "حدد مقطعاً من الجدول العلوي أولاً.")
            return None
        return int(self._table.item(selection[0].row(), 0).text())

    def _load_frame_for_video(self, video_id: int) -> QImage | None:
        from app.ui.dialogs.zone_editor_dialog import load_first_frame

        filepath = self._library.video_filepath(video_id)
        if not filepath:
            return None
        return load_first_frame(filepath)

    def _on_edit_zones(self) -> None:
        vid = self._selected_video_id()
        if vid is None:
            return
        from app.ui.dialogs import ZoneEditorDialog

        image = self._load_frame_for_video(vid)
        # الحوار يستخدم `ZoneService` داخلياً ويحلّ اتصال القاعدة بنفسه
        dlg = ZoneEditorDialog(video_id=vid, image=image, parent=self)
        dlg.exec()
        self._status.setText(f"حُدِّثت مناطق المقطع #{vid}")

    def _on_calibrate(self) -> None:
        vid = self._selected_video_id()
        if vid is None:
            return
        from app.ui.dialogs import CalibrationDialog

        image = self._load_frame_for_video(vid)
        dlg = CalibrationDialog(video_id=vid, image=image, parent=self)
        dlg.exec()
        self._status.setText(f"حُدِّثت معايرة المقطع #{vid}")

    def _on_add_manual(self) -> None:
        videos = self._load_videos_for_dialog()
        if not videos:
            QMessageBox.information(self, "لا توجد مقاطع", "يجب استيراد مقطع واحد على الأقل.")
            return
        dlg = ManualViolationDialog(
            videos=videos, parent=self, current_time_ms=self._seed_time_ms()
        )
        if dlg.exec() == ManualViolationDialog.DialogCode.Accepted:
            self._status.setText("تمت إضافة مخالفة يدوية")
            self.refresh()

    def _seed_time_ms(self) -> int | None:
        """وقت ابتدائي مقترح لمخالفة جديدة: بداية المخالفة المختارة إن وُجدت.

        سابقاً كان الحوار يُمرَّر 0 دائماً بينما يعرض زر «الوقت الحالي» —
        زر يعيد الصفر أبداً. الآن يظهر الزر فقط حين يوجد وقت حقيقي يقترحه.
        """
        selection = (
            self._violations_table.selectionModel().selectedRows()
            if self._violations_table.selectionModel()
            else []
        )
        if not selection:
            return None
        item = self._violations_table.item(selection[0].row(), 3)  # عمود البداية (ms)
        if item is None:
            return None
        try:
            return int(item.text())
        except (TypeError, ValueError):
            return None

    def _selected_violation_source(self) -> str:
        """مصدر المخالفة المختارة ('auto'/'manual') لعرض تنبيه التحويل في الحوار."""
        selection = (
            self._violations_table.selectionModel().selectedRows()
            if self._violations_table.selectionModel()
            else []
        )
        if not selection:
            return "auto"
        item = self._violations_table.item(selection[0].row(), 6)  # عمود المصدر
        return "manual" if item is not None and item.text() == "يدوي" else "auto"

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
        existing = self._violations.get_violation_for_edit(viol_id)
        if existing is None:
            QMessageBox.warning(self, "غير موجودة", "المخالفة المختارة غير موجودة.")
            return
        existing["source"] = self._selected_violation_source()
        videos = self._load_videos_for_dialog()
        dlg = ManualViolationDialog(videos=videos, parent=self, existing=existing)
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
        self._violations.delete_violation(viol_id)
        self._status.setText(f"تم حذف المخالفة #{viol_id}")
        self.refresh()
