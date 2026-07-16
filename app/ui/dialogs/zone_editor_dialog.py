"""حوارات تحرير المناطق (Zones) والمعايرة فوق إطار من المقطع.

الواجهة الرسومية المكافئة لـ `scripts/define_zones.py` و`scripts/calibrate.py`.
منطق تحويل الصورة وجمع النقاط قابل للاختبار بحقن QImage بدل فيديو حقيقي.
"""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.calibration import CalibrationService
from app.core.db import Database, get_database
from app.core.zones import ZONE_TYPES, ZoneService
from app.ui.widgets.frame_canvas import FrameCanvas

logger = logging.getLogger(__name__)


def numpy_bgr_to_qimage(frame: np.ndarray) -> QImage:
    """يحوّل إطار BGR (OpenCV) إلى QImage RGB — نسخة مملوكة (آمنة بعد انتهاء الـ buffer)."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("الإطار يجب أن يكون BGR بثلاث قنوات")
    h, w = frame.shape[:2]
    rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR→RGB
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return image.copy()


def load_first_frame(video_path: str) -> QImage | None:
    """يحمّل الإطار الأول من مقطع كـ QImage، أو None عند الفشل."""
    try:
        from app.core.frame_sampler import FrameSampler

        with FrameSampler(video_path) as sampler:
            frame = sampler.get_frame(0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("تعذّر تحميل إطار المعاينة من %s: %s", video_path, exc)
        return None
    if frame is None:
        return None
    return numpy_bgr_to_qimage(frame)


class ZoneEditorDialog(QDialog):
    """حوار لرسم مناطق مقطع وحفظها في DB."""

    def __init__(
        self,
        *,
        video_id: int,
        image: QImage | None = None,
        db: Database | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_id = video_id
        self._db = db or get_database()
        self._service = ZoneService(db=self._db)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"تحرير مناطق المقطع #{video_id}")
        self.setMinimumSize(720, 560)
        self._build_ui(image)
        self._refresh_zone_list()

    def _build_ui(self, image: QImage | None) -> None:
        root = QVBoxLayout(self)

        hint = QLabel(
            "انقر لإضافة نقاط المنطقة. خط التوقف/المسار: نقطتان. منطقة مغلقة: 3 نقاط أو أكثر.",
            self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._canvas = FrameCanvas(image, self)
        root.addWidget(self._canvas, stretch=1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("نوع المنطقة:", self))
        self._type_combo = QComboBox(self)
        for zt in ZONE_TYPES:
            self._type_combo.addItem(zt, zt)
        controls.addWidget(self._type_combo)

        undo_btn = QPushButton("تراجع عن نقطة", self)
        undo_btn.clicked.connect(self._canvas.undo_point)
        controls.addWidget(undo_btn)

        clear_btn = QPushButton("مسح النقاط", self)
        clear_btn.clicked.connect(self._canvas.clear_points)
        controls.addWidget(clear_btn)

        self._save_btn = QPushButton("حفظ المنطقة", self)
        self._save_btn.clicked.connect(self._on_save_zone)
        controls.addWidget(self._save_btn)
        controls.addStretch()
        root.addLayout(controls)

        root.addWidget(QLabel("المناطق المحفوظة:", self))
        self._zone_list = QListWidget(self)
        root.addWidget(self._zone_list, stretch=1)

        bottom = QHBoxLayout()
        del_btn = QPushButton("حذف المختارة", self)
        del_btn.clicked.connect(self._on_delete_selected)
        bottom.addWidget(del_btn)
        bottom.addStretch()
        close_btn = QPushButton("إغلاق", self)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    def _on_save_zone(self) -> None:
        zone_type = str(self._type_combo.currentData())
        points = self._canvas.points()
        try:
            self._service.add_zone(self._video_id, zone_type, points)
        except ValueError as exc:
            QMessageBox.warning(self, "نقاط غير كافية", str(exc))
            return
        self._canvas.clear_points()
        self._refresh_zone_list()

    def _on_delete_selected(self) -> None:
        item = self._zone_list.currentItem()
        if item is None:
            return
        zone_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._service.delete_zone(zone_id)
        self._refresh_zone_list()

    def _refresh_zone_list(self) -> None:
        from PyQt6.QtWidgets import QListWidgetItem

        self._zone_list.clear()
        for z in self._service.list_zones(self._video_id):
            item = QListWidgetItem(f"#{z.id}  {z.zone_type}  ({len(z.polygon)} نقاط)")
            item.setData(Qt.ItemDataRole.UserRole, z.id)
            self._zone_list.addItem(item)


class CalibrationDialog(QDialog):
    """حوار لمعايرة مقطع من نقطتين مرجعيتين ومسافة حقيقية."""

    def __init__(
        self,
        *,
        video_id: int,
        image: QImage | None = None,
        db: Database | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_id = video_id
        self._db = db or get_database()
        self._service = CalibrationService(db=self._db)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"معايرة المقطع #{video_id}")
        self.setMinimumSize(720, 520)
        self._build_ui(image)

    def _build_ui(self, image: QImage | None) -> None:
        root = QVBoxLayout(self)
        hint = QLabel("انقر نقطتين تعرف المسافة الحقيقية بينهما، ثم أدخل المسافة بالأمتار.", self)
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._canvas = FrameCanvas(image, self)
        root.addWidget(self._canvas, stretch=1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("المسافة الحقيقية (م):", self))
        self._distance = QDoubleSpinBox(self)
        self._distance.setRange(0.1, 1000.0)
        self._distance.setValue(10.0)
        self._distance.setSingleStep(0.5)
        controls.addWidget(self._distance)

        undo_btn = QPushButton("تراجع", self)
        undo_btn.clicked.connect(self._canvas.undo_point)
        controls.addWidget(undo_btn)

        clear_btn = QPushButton("مسح", self)
        clear_btn.clicked.connect(self._canvas.clear_points)
        controls.addWidget(clear_btn)
        controls.addStretch()
        root.addLayout(controls)

        self._result = QLabel(self._current_calibration_text(), self)
        root.addWidget(self._result)

        bottom = QHBoxLayout()
        save_btn = QPushButton("حفظ المعايرة", self)
        save_btn.clicked.connect(self._on_save)
        bottom.addWidget(save_btn)
        bottom.addStretch()
        close_btn = QPushButton("إغلاق", self)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    def _on_save(self) -> None:
        points = self._canvas.points()
        if len(points) < 2:
            QMessageBox.warning(self, "نقاط ناقصة", "انقر نقطتين على الأقل.")
            return
        # نستخدم أول نقطتين ومسافة واحدة
        try:
            cal = self._service.save_calibration(
                self._video_id, points[:2], [float(self._distance.value())]
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "فشل المعايرة", str(exc))
            return
        self._result.setText(f"✔ meters_per_px = {cal.meters_per_px:.5f}")

    def _current_calibration_text(self) -> str:
        cal = self._service.get_calibration(self._video_id)
        if cal is None:
            return "لا توجد معايرة بعد."
        return f"المعايرة الحالية: meters_per_px = {cal.meters_per_px:.5f}"


__all__ = [
    "CalibrationDialog",
    "ZoneEditorDialog",
    "load_first_frame",
    "numpy_bgr_to_qimage",
]
