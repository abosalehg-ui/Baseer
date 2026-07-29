"""واجهة التصنيف — pseudo-labeling وتصدير CVAT."""

from __future__ import annotations

import html
import logging
import webbrowser
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.constants import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_IOU_THRESHOLD
from app.core.analyzer import AnalysisConfig, AnalyzerService
from app.core.annotator import AnnotatorService
from app.core.library import LibraryService
from app.workers.inference_worker import InferenceWorker
from app.workers.runner import ThreadHandle, run_worker

logger = logging.getLogger(__name__)


class AnnotatorView(QWidget):
    """تبويب التصنيف — يدير pseudo-labeling والتصدير لـ CVAT."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._analyzer = AnalyzerService()
        self._annotator = AnnotatorService()
        # قراءات الجدول عبر الخدمة لا عبر `_db` الخاص بها
        self._library = LibraryService()
        self._inference: ThreadHandle | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # شريط الإعدادات
        cfg_bar = QHBoxLayout()
        cfg_bar.addWidget(QLabel("نموذج الاستدلال:", self))
        self._model_label = QLabel(self._default_model_path(), self)
        self._model_label.setProperty("role", "muted")
        cfg_bar.addWidget(self._model_label, stretch=1)

        choose_btn = QPushButton("اختر نموذجاً...", self)
        choose_btn.clicked.connect(self._on_choose_model)
        cfg_bar.addWidget(choose_btn)

        root.addLayout(cfg_bar)

        # عتبات
        thresh_bar = QHBoxLayout()
        thresh_bar.addWidget(QLabel("ثقة:", self))
        self._conf_spin = QDoubleSpinBox(self)
        self._conf_spin.setRange(0.05, 0.95)
        self._conf_spin.setSingleStep(0.05)
        self._conf_spin.setValue(DEFAULT_CONFIDENCE_THRESHOLD)
        thresh_bar.addWidget(self._conf_spin)

        thresh_bar.addWidget(QLabel("IoU:", self))
        self._iou_spin = QDoubleSpinBox(self)
        self._iou_spin.setRange(0.1, 0.9)
        self._iou_spin.setSingleStep(0.05)
        self._iou_spin.setValue(DEFAULT_IOU_THRESHOLD)
        thresh_bar.addWidget(self._iou_spin)

        thresh_bar.addWidget(QLabel("frame stride:", self))
        self._stride_spin = QSpinBox(self)
        self._stride_spin.setRange(1, 30)
        self._stride_spin.setValue(1)
        thresh_bar.addWidget(self._stride_spin)

        self._tracking_check = QCheckBox("تتبّع (ByteTrack)", self)
        self._tracking_check.setChecked(True)
        self._tracking_check.setToolTip(
            "لازم لاستخراج المخالفات: بدونه لا تُنشأ tracks ولا تُكشف أي مخالفة."
        )
        thresh_bar.addWidget(self._tracking_check)

        thresh_bar.addStretch()
        root.addLayout(thresh_bar)

        # أزرار الأفعال
        actions = QHBoxLayout()
        self._run_btn = QPushButton("تشغيل pre-labeling", self)
        self._run_btn.clicked.connect(self._on_run_inference)
        actions.addWidget(self._run_btn)

        self._stop_btn = QPushButton("⏹ إيقاف", self)
        self._stop_btn.setToolTip("إيقاف الاستدلال بعد المقطع الحالي")
        self._stop_btn.setAccessibleName("إيقاف الاستدلال")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop_inference)
        actions.addWidget(self._stop_btn)

        self._export_btn = QPushButton("تصدير لـ CVAT XML", self)
        self._export_btn.clicked.connect(self._on_export_cvat)
        actions.addWidget(self._export_btn)

        open_cvat = QPushButton("افتح CVAT في المتصفح", self)
        open_cvat.clicked.connect(self._on_open_cvat)
        actions.addWidget(open_cvat)

        refresh_btn = QPushButton("تحديث", self)
        refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(refresh_btn)

        prepare_btn = QPushButton("تجهيز Dataset (YOLOv8)", self)
        prepare_btn.clicked.connect(self._on_prepare_dataset)
        actions.addWidget(prepare_btn)

        actions.addStretch()
        root.addLayout(actions)

        # جدول المقاطع
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["المعرّف", "اسم الملف", "الحالة", "عدد الكشوفات"])
        self._table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setAccessibleName("جدول المقاطع وحالة التصنيف")
        header = self._table.horizontalHeader()
        if header is not None:
            for col in range(self._table.columnCount()):
                header.setSectionResizeMode(
                    col,
                    (
                        QHeaderView.ResizeMode.Stretch
                        if col == 1
                        else QHeaderView.ResizeMode.ResizeToContents
                    ),
                )
        root.addWidget(self._table, stretch=1)

        # شريط الحالة
        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        self._status_label = QLabel("جاهز", self)
        root.addWidget(self._status_label)

    # ============================================
    # عرض الجدول
    # ============================================
    def refresh(self) -> None:
        """يُحدّث الجدول بكل المقاطع المرتبطة بهذه الوحدة."""
        rows = self._library.video_summaries()
        self._table.setRowCount(len(rows))
        for r, (vid, filename, status, detections, _violations) in enumerate(rows):
            self._table.setItem(r, 0, QTableWidgetItem(str(vid)))
            self._table.setItem(r, 1, QTableWidgetItem(filename))
            self._table.setItem(r, 2, QTableWidgetItem(status))
            self._table.setItem(r, 3, QTableWidgetItem(str(detections)))

    # ============================================
    # تشغيل الاستدلال
    # ============================================
    def _on_run_inference(self) -> None:
        if self._inference is not None and self._inference.is_running():
            QMessageBox.information(self, "العملية تعمل", "هناك دفعة استدلال جارية.")
            return

        model_path = Path(self._model_label.text())
        if not model_path.exists():
            QMessageBox.warning(
                self,
                "النموذج غير موجود",
                f"تأكد من وجود الموديل: {model_path}\n"
                "نزّله أولاً عبر scripts/download_models.py",
            )
            return

        video_ids = self._selected_video_ids() or self._analyzer.list_unanalyzed_video_ids()
        if not video_ids:
            QMessageBox.information(
                self, "لا توجد مقاطع", "كل المقاطع تم تحليلها أو لا توجد مقاطع."
            )
            return

        config = AnalysisConfig(
            model_path=model_path,
            confidence=float(self._conf_spin.value()),
            iou=float(self._iou_spin.value()),
            frame_stride=int(self._stride_spin.value()),
            device=self._settings.cuda_device,
            enable_tracking=self._tracking_check.isChecked(),
        )
        self._start_inference(video_ids, config)

    def _start_inference(self, video_ids: list[int], config: AnalysisConfig) -> None:
        self._progress.setVisible(True)
        self._progress.setRange(0, len(video_ids))
        self._progress.setValue(0)
        self._status_label.setText(f"بدء استدلال على {len(video_ids)} مقطع...")
        self._stop_btn.setEnabled(True)
        self._run_btn.setEnabled(False)

        self._inference = run_worker(
            InferenceWorker(video_ids, config, service=self._analyzer),
            parent=self,
            on_finished=self._on_inference_finished,
            on_failed=self._on_inference_failed,
            signal_bindings={"progress": self._on_inference_progress},
        )

    def _on_stop_inference(self) -> None:
        """يطلب إيقاف الاستدلال — يتوقف بعد المقطع الجاري."""
        if self._inference is not None and self._inference.cancel():
            self._stop_btn.setEnabled(False)
            self._status_label.setText("جارٍ الإيقاف بعد المقطع الحالي...")

    def _on_inference_progress(self, current: int, total: int, video_id: int) -> None:
        self._progress.setValue(current)
        self._status_label.setText(f"({current}/{total}) تحليل المقطع #{video_id}...")

    def _on_inference_finished(self, results: list[Any]) -> None:
        self._progress.setVisible(False)
        self._status_label.setText(f"اكتمل استدلال {len(results)} مقطع")
        self._inference = None
        self._stop_btn.setEnabled(False)
        self._run_btn.setEnabled(True)
        self.refresh()

    def _on_inference_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status_label.setText("فشل الاستدلال")
        QMessageBox.critical(self, "فشل الاستدلال", message)
        self._inference = None
        self._stop_btn.setEnabled(False)
        self._run_btn.setEnabled(True)

    # ============================================
    # تصدير CVAT
    # ============================================
    def _on_export_cvat(self) -> None:
        ids = self._selected_video_ids() or self._annotator.list_prelabeled_video_ids()
        if not ids:
            QMessageBox.information(self, "لا توجد مقاطع", "لا توجد مقاطع لها pseudo-labels.")
            return
        try:
            paths = self._annotator.export_batch_pseudo_labels(ids)
            self._status_label.setText(f"صُدِّرت {len(paths)} ملفات XML")
            QMessageBox.information(
                self,
                "تم التصدير",
                f"صُدِّرت {len(paths)} ملف XML في:\n"
                f"{self._settings.data_dir / 'annotations' / 'raw'}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل التصدير")
            QMessageBox.critical(self, "فشل التصدير", str(exc))

    def _on_open_cvat(self) -> None:
        """يفتح CVAT في المتصفح — بعد التحقق من أن الرابط http(s) فقط.

        الرابط يأتي من `.env` بلا قيود، و`webbrowser.open` يفتح أي مخطط مسجَّل
        في النظام (`file://`، مخططات تطبيقات…) — فنقصره على المتصفح.
        """
        url = (self._annotator.cvat_url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self,
                "رابط CVAT غير صالح",
                f"الرابط المضبوط في .env ليس http/https:\n{url}\n\n"
                "صحّح CVAT_URL قبل المحاولة مجدداً.",
            )
            return
        webbrowser.open(url)

    def _on_prepare_dataset(self) -> None:
        """يُجهّز dataset YOLOv8 من مجلد reviewed."""
        from app.core.dataset import DatasetService

        source = QFileDialog.getExistingDirectory(
            self,
            "اختر مجلد التصنيفات المُراجَعة (CVAT YOLO export)",
            str(self._settings.data_dir / "annotations" / "reviewed"),
        )
        if not source:
            return
        output = self._settings.data_dir / "dataset"

        # `prepare(..., overwrite=True)` ينفّذ `shutil.rmtree` على مجلد الإخراج.
        # كان يحدث بلا سؤال: نقرة واحدة تمحو dataset قد يمثّل ساعات مراجعة يدوية.
        if not self._confirm_dataset_overwrite(output):
            return
        if Path(source).resolve() == output.resolve():
            QMessageBox.warning(
                self,
                "مسار غير صالح",
                "مجلد المصدر هو نفسه مجلد الإخراج — سيُحذف المصدر قبل قراءته.\n"
                "اختر مجلد التصنيفات المُراجَعة بدلاً منه.",
            )
            return

        try:
            report = DatasetService().prepare(source, output, overwrite=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل تجهيز الـ dataset")
            QMessageBox.critical(self, "فشل التجهيز", str(exc))
            return

        msg_lines = [
            f"إجمالي العينات: {report.total_samples}",
            f"train: {report.train_count}  •  val: {report.val_count}  •  test: {report.test_count}",
            f"\ndataset.yaml: {output / 'dataset.yaml'}",
        ]
        if report.issues:
            msg_lines.append("\nتحذيرات:")
            msg_lines.extend(f"• {issue}" for issue in report.issues)

        QMessageBox.information(self, "تم تجهيز الـ Dataset", "\n".join(msg_lines))
        self._status_label.setText(f"جُهّز dataset في {output}")

    def _confirm_dataset_overwrite(self, output: Path) -> bool:
        """يطلب تأكيداً صريحاً قبل حذف مجلد dataset قائم."""
        if not output.exists():
            return True
        try:
            existing_files = sum(1 for p in output.rglob("*") if p.is_file())
        except OSError:
            existing_files = 0
        answer = QMessageBox.question(
            self,
            "استبدال الـ Dataset الحالي؟",
            f"<b>سيُحذف المجلد التالي بالكامل قبل التجهيز:</b><br>"
            f"<code>{html.escape(str(output))}</code><br><br>"
            f"يحتوي حالياً على <b>{existing_files}</b> ملفاً. لا يمكن التراجع.<br><br>"
            "هل تريد المتابعة؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_choose_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر نموذج YOLO", str(self._settings.models_dir), "PyTorch (*.pt)"
        )
        if path:
            self._model_label.setText(path)

    # ============================================
    # مساعدات
    # ============================================
    def _default_model_path(self) -> str:
        return str(self._settings.models_dir / "pretrained" / "yolov8x.pt")

    def _selected_video_ids(self) -> list[int]:
        selected = (
            self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        )
        return [int(self._table.item(idx.row(), 0).text()) for idx in selected]
