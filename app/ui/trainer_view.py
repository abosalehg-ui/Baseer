"""واجهة التدريب — اختيار النموذج/الـ dataset، تشغيل، عرض logs والمقاييس."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.core.trainer import (
    EpochMetrics,
    EvalReport,
    TrainConfig,
    TrainerService,
    TrainResult,
)
from app.workers.training_worker import TrainingWorker

logger = logging.getLogger(__name__)


class TrainerView(QWidget):
    """تبويب التدريب."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = get_settings()
        self._service = TrainerService()
        self._thread: QThread | None = None
        self._worker: TrainingWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addLayout(self._build_paths_row())
        root.addLayout(self._build_hyperparams())
        root.addLayout(self._build_actions())

        self._progress = QProgressBar(self)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("جاهز", self)
        root.addWidget(self._status)

        # logs + جدول تقييم
        self._log = QTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        root.addWidget(self._log, stretch=2)

        self._eval_table = QTableWidget(0, 2, self)
        self._eval_table.setHorizontalHeaderLabels(["class", "mAP50"])
        self._eval_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        root.addWidget(self._eval_table, stretch=1)

    def _build_paths_row(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("النموذج الأساسي:", self))
        self._model_label = QLabel(self._default_base_model(), self)
        bar.addWidget(self._model_label, stretch=1)
        model_btn = QPushButton("اختر...", self)
        model_btn.clicked.connect(self._on_pick_model)
        bar.addWidget(model_btn)

        bar.addSpacing(20)
        bar.addWidget(QLabel("dataset.yaml:", self))
        self._ds_label = QLabel(self._default_dataset_yaml(), self)
        bar.addWidget(self._ds_label, stretch=1)
        ds_btn = QPushButton("اختر...", self)
        ds_btn.clicked.connect(self._on_pick_dataset)
        bar.addWidget(ds_btn)
        return bar

    def _build_hyperparams(self) -> QFormLayout:
        form = QFormLayout()
        self._epochs = QSpinBox(self)
        self._epochs.setRange(1, 1000)
        self._epochs.setValue(100)
        form.addRow("Epochs:", self._epochs)

        self._batch = QSpinBox(self)
        self._batch.setRange(1, 256)
        self._batch.setValue(16)
        form.addRow("Batch:", self._batch)

        self._imgsz = QSpinBox(self)
        self._imgsz.setRange(320, 1280)
        self._imgsz.setSingleStep(32)
        self._imgsz.setValue(640)
        form.addRow("Image size:", self._imgsz)

        self._patience = QSpinBox(self)
        self._patience.setRange(0, 200)
        self._patience.setValue(20)
        form.addRow("Patience:", self._patience)

        self._lr0 = QDoubleSpinBox(self)
        self._lr0.setDecimals(5)
        self._lr0.setRange(1e-5, 1.0)
        self._lr0.setSingleStep(0.0005)
        self._lr0.setValue(0.001)
        form.addRow("Initial LR:", self._lr0)

        self._run_name = QLabel("baseer-v1", self)
        form.addRow("Run name:", self._run_name)
        return form

    def _build_actions(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._start_btn = QPushButton("بدء التدريب", self)
        self._start_btn.clicked.connect(self._on_start)
        bar.addWidget(self._start_btn)

        self._eval_btn = QPushButton("تقييم best.pt", self)
        self._eval_btn.clicked.connect(self._on_evaluate)
        bar.addWidget(self._eval_btn)

        clear_btn = QPushButton("مسح السجل", self)
        clear_btn.clicked.connect(lambda: self._log.clear())
        bar.addWidget(clear_btn)
        bar.addStretch()
        return bar

    # ============================================
    # أفعال
    # ============================================
    def _on_pick_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر النموذج الأساسي", str(self._settings.models_dir), "PyTorch (*.pt)"
        )
        if path:
            self._model_label.setText(path)

    def _on_pick_dataset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر dataset.yaml", str(self._settings.data_dir), "YAML (*.yaml *.yml)"
        )
        if path:
            self._ds_label.setText(path)

    def _on_start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self, "التدريب يعمل", "هناك تدريب جارٍ.")
            return

        base = Path(self._model_label.text())
        ds = Path(self._ds_label.text())
        if not base.exists():
            QMessageBox.warning(self, "النموذج مفقود", f"غير موجود: {base}")
            return
        if not ds.exists():
            QMessageBox.warning(self, "dataset.yaml مفقود", f"غير موجود: {ds}")
            return

        config = TrainConfig(
            base_model=base,
            dataset_yaml=ds,
            epochs=int(self._epochs.value()),
            batch=int(self._batch.value()),
            imgsz=int(self._imgsz.value()),
            patience=int(self._patience.value()),
            lr0=float(self._lr0.value()),
            device=self._settings.cuda_device,
            project=self._settings.models_dir / "finetuned",
            name=self._run_name.text(),
        )
        self._start_training(config)

    def _start_training(self, config: TrainConfig) -> None:
        self._progress.setVisible(True)
        self._progress.setRange(0, config.epochs)
        self._progress.setValue(0)
        self._status.setText(f"بدء التدريب — {config.epochs} epoch")
        self._log.append(f"=== بدء تدريب {config.name} ===")
        self._log.append(f"base: {config.base_model}")
        self._log.append(f"data: {config.dataset_yaml}")

        thread = QThread(self)
        worker = TrainingWorker(config, service=self._service)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.epoch_done.connect(self._on_epoch)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_epoch(self, m: EpochMetrics) -> None:
        self._progress.setValue(m.epoch)
        map_str = f"mAP50={m.map50:.3f}" if m.map50 is not None else "—"
        self._log.append(
            f"[epoch {m.epoch}/{m.total}] "
            f"box={m.box_loss:.4f} cls={m.cls_loss:.4f} dfl={m.dfl_loss:.4f} {map_str}"
        )
        self._status.setText(f"epoch {m.epoch}/{m.total}")

    def _on_finished(self, result: TrainResult) -> None:
        self._progress.setVisible(False)
        self._status.setText(f"اكتمل — {result.run_dir}")
        self._log.append("=== انتهى التدريب ===")
        self._log.append(f"best.pt: {result.best_pt}")
        if result.final_map50 is not None:
            self._log.append(f"mAP50 النهائية: {result.final_map50:.3f}")
        self._thread = None
        self._worker = None

    def _on_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._status.setText("فشل التدريب")
        self._log.append(f"✗ خطأ: {message}")
        QMessageBox.critical(self, "فشل التدريب", message)
        self._thread = None
        self._worker = None

    def _on_evaluate(self) -> None:
        best = (
            self._settings.models_dir / "finetuned" / self._run_name.text() / "weights" / "best.pt"
        )
        ds = Path(self._ds_label.text())
        if not best.exists():
            QMessageBox.warning(self, "best.pt مفقود", f"غير موجود: {best}")
            return
        try:
            report = self._service.evaluate(best, ds)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "فشل التقييم", str(exc))
            return
        self._show_eval_report(report)

    def _show_eval_report(self, report: EvalReport) -> None:
        self._log.append(
            f"=== التقييم: mAP50={report.map50:.3f} mAP={report.map:.3f} "
            f"P={report.precision:.3f} R={report.recall:.3f} ==="
        )
        items = list(report.per_class_map50.items())
        self._eval_table.setRowCount(len(items))
        for r, (name, value) in enumerate(items):
            self._eval_table.setItem(r, 0, QTableWidgetItem(str(name)))
            self._eval_table.setItem(r, 1, QTableWidgetItem(f"{value:.3f}"))
        self._eval_table.resizeColumnsToContents()

    # ============================================
    # مساعدات
    # ============================================
    def _default_base_model(self) -> str:
        return str(self._settings.models_dir / "pretrained" / "yolov8m.pt")

    def _default_dataset_yaml(self) -> str:
        return str(self._settings.data_dir / "dataset" / "dataset.yaml")
