"""واجهة وحدة المكتبة — استيراد، عرض، فلترة، معاينة."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread
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
from app.core.library import ImportReport, LibraryService
from app.ui.widgets.thumbnail_grid import ThumbnailGrid, VideoCard
from app.ui.widgets.video_player import VideoPlayer
from app.workers.import_worker import ImportWorker

logger = logging.getLogger(__name__)


class LibraryView(QWidget):
    """تبويب المكتبة — يحتوي شريط أدوات، شبكة thumbnails، panel معاينة."""

    def __init__(
        self, service: LibraryService | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._service = service or LibraryService()
        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
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
        bar = QHBoxLayout()
        bar.addWidget(self._status_label, stretch=1)
        bar.addWidget(self._progress, stretch=2)
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
        self._search_box.textChanged.connect(self.refresh)
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
        if self._import_thread is not None and self._import_thread.isRunning():
            QMessageBox.information(
                self, "استيراد قيد التنفيذ", "جارٍ استيراد عملية أخرى — انتظر انتهاءها."
            )
            return
        if not paths:
            return

        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        label = paths[0].name if len(paths) == 1 else f"{len(paths)} عناصر"
        self._status_label.setText(f"جارٍ استيراد {label}...")

        thread = QThread(self)
        worker = ImportWorker(paths, source, service=self._service)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_import_progress)
        worker.finished.connect(self._on_import_finished)
        worker.failed.connect(self._on_import_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._import_thread = thread
        self._import_worker = worker
        thread.start()

    def _on_import_progress(self, current: int, total: int, filename: str) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._status_label.setText(f"({current}/{total}) {filename}")

    def _on_import_finished(self, report: ImportReport) -> None:
        self._progress.setVisible(False)
        self._status_label.setText(
            f"اكتمل: {len(report.imported)} مُستورد، "
            f"{len(report.duplicates)} مكرر، {len(report.failed)} فاشل"
        )
        self._import_thread = None
        self._import_worker = None

        # تشخيص واضح لو كل الملفات فشلت
        if report.failed and not report.imported and not report.duplicates:
            self._show_failure_diagnosis(report)

        self.refresh()

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
                "تفاصيل أول خطأ:<br><i>" + first_error[:200] + "</i>",
            )
        else:
            QMessageBox.warning(
                self,
                "فشلت كل عمليات الاستيراد",
                f"فشل {len(report.failed)} ملف. أول خطأ:\n\n{first_error[:400]}",
            )

    def _on_import_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status_label.setText("فشل الاستيراد")
        QMessageBox.critical(self, "خطأ في الاستيراد", message)
        self._import_thread = None
        self._import_worker = None

    # ============================================
    # العرض والمعاينة
    # ============================================
    def refresh(self) -> None:
        """يعيد تحميل الشبكة وفق الفلاتر الحالية."""
        source_filter = self._filter_source.currentData()
        search = self._search_box.text().strip().lower()

        rows = self._service.list_videos(source_type=source_filter)
        cards = [
            VideoCard(
                video_id=int(r[0]),
                filename=str(r[1]),
                duration_sec=float(r[3]) if r[3] is not None else None,
                source_type=str(r[2]) if r[2] is not None else None,
                thumbnail_path=str(r[5]) if r[5] is not None else None,
            )
            for r in rows
            if not search or search in str(r[1]).lower()
        ]
        self._grid.set_cards(cards)
        total = self._service.count_videos()
        total_duration = self._service.total_duration_seconds()
        self._status_label.setText(
            f"إجمالي المقاطع: {total} — مجموع المدة: {total_duration / 60:.1f} دقيقة"
        )

    def _on_card_activated(self, video_id: int) -> None:
        row = self._service.get_video(video_id)
        if not row:
            return
        filepath = row[1]
        self._player.load(filepath)
        self._details_label.setText(self._format_details(row))

    @staticmethod
    def _format_details(row: tuple) -> str:
        cols = [
            ("المعرّف", row[0]),
            ("الاسم", row[2]),
            ("المصدر", row[3]),
            ("المدة (ثانية)", row[4]),
            ("الأبعاد", f"{row[5]}×{row[6]}" if row[5] and row[6] else "—"),
            ("FPS", row[7]),
            ("الترميز", row[8]),
            ("الحجم (م.ب)", row[9]),
            ("تاريخ التسجيل", row[12]),
            ("تاريخ الاستيراد", row[13]),
            ("الحالة", row[18]),
        ]
        lines = [f"<b>{label}:</b> {value if value is not None else '—'}" for label, value in cols]
        return "<br>".join(lines)
