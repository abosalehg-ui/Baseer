"""واجهة وحدة المكتبة — استيراد، عرض، فلترة، معاينة."""

from __future__ import annotations

import html
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.constants import SOURCE_ARABIC_NAMES, SourceType
from app.core.library import ImportReport, LibraryService, VideoDetails
from app.ui.widgets.thumbnail_grid import ThumbnailGrid, VideoCard
from app.ui.widgets.video_player import VideoPlayer
from app.workers.import_worker import ImportWorker
from app.workers.runner import ThreadHandle, run_worker

logger = logging.getLogger(__name__)

# مهلة تجميع ضغطات المفاتيح قبل إعادة البحث (ms)
SEARCH_DEBOUNCE_MS = 250


class LibraryView(QWidget):
    """تبويب المكتبة — يحتوي شريط أدوات، شبكة thumbnails، panel معاينة."""

    def __init__(
        self, service: LibraryService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._service = service or LibraryService()
        self._import: ThreadHandle | None = None
        # مؤقّت تجميع: البحث كان يعيد بناء الشبكة كاملة عند كل حرف
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refresh)
        self._build_ui()
        self.setAcceptDrops(True)
        self.refresh()

    # ============================================
    # بناء الواجهة
    # ============================================
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_filters())

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self._grid = ThumbnailGrid(self)
        self._grid.card_activated.connect(self._on_card_activated)
        splitter.addWidget(self._grid)

        self._side_panel = self._build_side_panel()
        splitter.addWidget(self._side_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        self._status_label = QLabel("جاهز", self)
        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        self._cancel_btn = QPushButton("إيقاف", self)
        self._cancel_btn.setToolTip("إيقاف الاستيراد بعد الملف الحالي")
        self._cancel_btn.setAccessibleName("إيقاف الاستيراد")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel_import)
        bar = QHBoxLayout()
        bar.addWidget(self._status_label, stretch=1)
        bar.addWidget(self._progress, stretch=2)
        bar.addWidget(self._cancel_btn)
        root.addLayout(bar)

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar(self)
        toolbar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        import_files_btn = QPushButton("استيراد ملفات...", self)
        import_files_btn.clicked.connect(self._on_import_files)
        toolbar.addWidget(import_files_btn)

        import_folder_btn = QPushButton("استيراد مجلد...", self)
        import_folder_btn.clicked.connect(self._on_import_folder)
        toolbar.addWidget(import_folder_btn)

        toolbar.addSeparator()

        self._source_combo = QComboBox(self)
        self._source_combo.addItem("نوع المصدر للاستيراد:", None)
        for s in SourceType:
            self._source_combo.addItem(SOURCE_ARABIC_NAMES[s], s.value)
        self._source_combo.setCurrentIndex(1)
        toolbar.addWidget(self._source_combo)

        toolbar.addSeparator()
        dupes_btn = QPushButton("مراجعة التكرارات", self)
        dupes_btn.setToolTip("عرض المقاطع المكررة (ثنائياً أو بصرياً) وحذف الزائد")
        dupes_btn.clicked.connect(self._on_review_duplicates)
        toolbar.addWidget(dupes_btn)

        toolbar.addSeparator()
        refresh_btn = QPushButton("تحديث", self)
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        return toolbar

    def _on_review_duplicates(self) -> None:
        from app.ui.dialogs.duplicates_dialog import DuplicatesDialog

        dlg = DuplicatesDialog(service=self._service, parent=self)
        dlg.exec()
        self.refresh()

    def _build_filters(self) -> QWidget:
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("بحث:", self))
        self._search_box = QLineEdit(self)
        self._search_box.setPlaceholderText("اسم الملف...")
        self._search_box.setAccessibleName("البحث في المكتبة باسم الملف")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_box, stretch=1)

        layout.addWidget(QLabel("المصدر:", self))
        self._filter_source = QComboBox(self)
        self._filter_source.addItem("الكل", None)
        for s in SourceType:
            self._filter_source.addItem(SOURCE_ARABIC_NAMES[s], s.value)
        self._filter_source.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self._filter_source)

        return bar

    def _build_side_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)

        self._player = VideoPlayer(panel)
        layout.addWidget(self._player, stretch=1)

        self._details_label = QLabel("اختر مقطعاً لعرض تفاصيله", panel)
        self._details_label.setWordWrap(True)
        self._details_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._details_label, stretch=1)

        return panel

    # ============================================
    # السحب والإفلات
    # ============================================
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        valid = [p for p in paths if p.exists()]
        if not valid:
            return
        self._start_import(valid, self._selected_source_for_import())

    # ============================================
    # إجراءات الشريط
    # ============================================
    def _on_import_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "اختر مقاطع للاستيراد",
            "",
            "ملفات الفيديو (*.mp4 *.mkv *.mov *.avi *.webm)",
        )
        if not paths:
            return
        self._start_import([Path(p) for p in paths], self._selected_source_for_import())

    def _on_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "اختر مجلداً يحتوي المقاطع")
        if folder:
            self._start_import([Path(folder)], self._selected_source_for_import())

    def _selected_source_for_import(self) -> SourceType:
        data = self._source_combo.currentData()
        return SourceType(data) if data else SourceType.OTHER

    # ============================================
    # تنفيذ الاستيراد في thread
    # ============================================
    def _start_import(self, paths: list[Path], source: SourceType) -> None:
        if self._import is not None and self._import.is_running():
            QMessageBox.information(
                self, "استيراد قيد التنفيذ", "جارٍ استيراد عملية أخرى — انتظر انتهاءها."
            )
            return
        if not paths:
            return

        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        label = paths[0].name if len(paths) == 1 else f"{len(paths)} عناصر"
        self._status_label.setText(f"جارٍ استيراد {label}...")

        self._import = run_worker(
            ImportWorker(paths, source, service=self._service),
            parent=self,
            on_finished=self._on_import_finished,
            on_failed=self._on_import_failed,
            signal_bindings={"progress": self._on_import_progress},
        )

    def _on_cancel_import(self) -> None:
        """يطلب إيقاف الاستيراد — يتوقف بعد الملف الجاري بتقرير جزئي."""
        if self._import is not None and self._import.cancel():
            self._cancel_btn.setEnabled(False)
            self._status_label.setText("جارٍ الإيقاف بعد الملف الحالي...")

    def _on_import_progress(self, current: int, total: int, filename: str) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._status_label.setText(f"({current}/{total}) {filename}")

    def _on_import_finished(self, report: ImportReport) -> None:
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._import = None

        # تشخيص واضح لو كل الملفات فشلت
        if report.failed and not report.imported and not report.duplicates:
            self._show_failure_diagnosis(report)

        # نُحدّث الشبكة أولاً ثم نكتب ملخّص الاستيراد: `refresh()` يكتب في نفس
        # الـlabel، فترتيبه بعد الملخّص كان يدهسه قبل أن يقرأه المستخدم.
        self.refresh()
        prefix = "أُلغي الاستيراد" if report.cancelled else "اكتمل"
        summary = (
            f"{prefix}: {len(report.imported)} مُستورد، "
            f"{len(report.duplicates)} مكرر، {len(report.failed)} فاشل"
        )
        if report.cancelled and report.skipped:
            summary += f"، {len(report.skipped)} لم يُعالَج"
        self._status_label.setText(summary)

    def _show_failure_diagnosis(self, report: ImportReport) -> None:
        """يعرض رسالة تشخيص مفصّلة لو الاستيراد فشل بالكامل."""
        first_error = report.failed[0][1] if report.failed else ""
        is_ffmpeg = "ffprobe" in first_error.lower() or "ffmpeg" in first_error.lower()

        if is_ffmpeg:
            QMessageBox.critical(
                self,
                "FFmpeg غير مثبَّت",
                "<b>FFmpeg غير موجود في PATH.</b><br><br>"
                "بَصير يحتاج <code>ffmpeg</code> و <code>ffprobe</code> لقراءة بيانات "
                "المقاطع وتوليد الـ thumbnails.<br><br>"
                "<b>طريقة التثبيت السريعة (PowerShell):</b><br>"
                "<code>winget install --id Gyan.FFmpeg</code><br><br>"
                "بعد التثبيت، أغلق التطبيق وأعد فتح PowerShell ثم شغّله من جديد.<br><br>"
                "تفاصيل أول خطأ:<br><i>" + html.escape(first_error[:200]) + "</i>",
            )
        else:
            QMessageBox.warning(
                self,
                "فشلت كل عمليات الاستيراد",
                f"فشل {len(report.failed)} ملف. أول خطأ:\n\n{first_error[:400]}",
            )

    def _on_import_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._cancel_btn.setVisible(False)
        self._status_label.setText("فشل الاستيراد")
        QMessageBox.critical(self, "خطأ في الاستيراد", message)
        self._import = None

    # ============================================
    # العرض والمعاينة
    # ============================================
    def _on_search_changed(self) -> None:
        """يؤجّل البحث بدل تنفيذه على كل ضغطة مفتاح."""
        self._search_timer.start()

    def refresh(self) -> None:
        """يعيد تحميل الشبكة وفق الفلاتر الحالية."""
        self._search_timer.stop()
        source_filter = self._filter_source.currentData()
        search = self._search_box.text().strip()

        # الفلترة تجري في SQL: جلب كل الصفوف ثم تصفيتها في Python كان يسحب
        # المكتبة كاملة من القاعدة عند كل حرف.
        rows = self._service.list_videos(source_type=source_filter, search=search or None)
        cards = [
            VideoCard(
                video_id=int(r[0]),
                filename=str(r[1]),
                duration_sec=float(r[3]) if r[3] is not None else None,
                source_type=str(r[2]) if r[2] is not None else None,
                thumbnail_path=str(r[5]) if r[5] is not None else None,
            )
            for r in rows
        ]
        self._grid.set_cards(cards)
        total = self._service.count_videos()
        total_duration = self._service.total_duration_seconds()
        shown = f"{len(cards)} من {total}" if len(cards) != total else str(total)
        self._status_label.setText(
            f"المقاطع المعروضة: {shown} — مجموع المدة: {total_duration / 60:.1f} دقيقة"
        )

    def _on_card_activated(self, video_id: int) -> None:
        details = self._service.get_video_details(video_id)
        if details is None:
            return
        self._player.load(details.filepath)
        self._details_label.setText(self._format_details(details))

    @staticmethod
    def _format_details(details: VideoDetails) -> str:
        """يبني جدول التفاصيل — كل قيمة **مهروبة** قبل حقنها في HTML.

        اسم ملف مثل `<img src=x>` أو `</b><a href="...">` كان يُرندر كوسم فعلي
        في الـQLabel. المصدر (نظام الملفات) غير موثوق فيُهرَّب دائماً.
        """
        dimensions = (
            f"{details.width}×{details.height}" if details.width and details.height else None
        )
        rows: list[tuple[str, object | None]] = [
            ("المعرّف", details.id),
            ("الاسم", details.filename),
            ("المصدر", details.source_type),
            ("المدة (ثانية)", details.duration_sec),
            ("الأبعاد", dimensions),
            ("FPS", details.fps),
            ("الترميز", details.codec),
            ("الحجم (م.ب)", details.file_size_mb),
            ("تاريخ التسجيل", details.recorded_at),
            ("تاريخ الاستيراد", details.imported_at),
            ("الحالة", details.status),
        ]
        lines = [
            f"<b>{html.escape(label)}:</b> "
            f"{html.escape(str(value)) if value is not None else '—'}"
            for label, value in rows
        ]
        return "<br>".join(lines)
