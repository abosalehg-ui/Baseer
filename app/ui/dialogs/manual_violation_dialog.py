"""مربع حوار إضافة/تعديل مخالفة يدوية."""

from __future__ import annotations

import getpass
import json
import logging
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import VIOLATION_ARABIC_NAMES, ViolationType
from app.core.db import Database, get_database

logger = logging.getLogger(__name__)


@dataclass
class ManualViolationData:
    """البيانات المُجمَّعة من الحوار."""

    video_id: int
    violation_type: ViolationType
    start_ms: int
    end_ms: int
    license_plate: str
    notes: str
    evidence_frame: int | None


class ManualViolationDialog(QDialog):
    """حوار لإضافة مخالفة يدوية أو تعديل قائمة."""

    def __init__(
        self,
        *,
        videos: list[tuple[int, str]],
        parent: QWidget | None = None,
        existing: dict[str, Any] | None = None,
        current_time_ms: int | None = None,
        db: Database | None = None,
    ) -> None:
        """`videos`: قائمة (id, filename). `existing`: قاموس قيم للتعديل (يحتوي id)."""
        super().__init__(parent)
        self._videos = videos
        self._existing = existing
        self._db = db or get_database()
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("تعديل مخالفة يدوية" if existing else "إضافة مخالفة يدوية")
        self.setMinimumWidth(420)
        self._build_ui(current_time_ms or 0)
        if existing:
            self._populate_from_existing(existing)

    # ============================================
    # واجهة
    # ============================================
    def _build_ui(self, current_time_ms: int) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        # المقطع
        self._video_combo = QComboBox(self)
        for vid, name in self._videos:
            self._video_combo.addItem(f"{name} (#{vid})", userData=vid)
        form.addRow("المقطع:", self._video_combo)

        # نوع المخالفة
        self._type_combo = QComboBox(self)
        for vtype in ViolationType:
            label = VIOLATION_ARABIC_NAMES.get(vtype, vtype.value)
            self._type_combo.addItem(label, userData=vtype.value)
        # افتراضياً: مخالفة يدوية أخرى
        idx = self._type_combo.findData(ViolationType.MANUAL_OTHER.value)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        form.addRow("نوع المخالفة:", self._type_combo)

        # بداية الوقت + زر "الوقت الحالي"
        start_row = QHBoxLayout()
        self._start_ms = QSpinBox(self)
        self._start_ms.setRange(0, 24 * 3600 * 1000)
        self._start_ms.setSingleStep(100)
        self._start_ms.setSuffix(" ms")
        self._start_ms.setValue(current_time_ms)
        start_row.addWidget(self._start_ms, stretch=1)
        use_now_btn = QPushButton("الوقت الحالي", self)
        use_now_btn.setToolTip(f"يضع الوقت الحالي للمشغل ({current_time_ms} ms)")
        use_now_btn.clicked.connect(lambda: self._start_ms.setValue(current_time_ms))
        start_row.addWidget(use_now_btn)
        form.addRow("بداية الوقت:", start_row)

        # نهاية الوقت
        self._end_ms = QSpinBox(self)
        self._end_ms.setRange(0, 24 * 3600 * 1000)
        self._end_ms.setSingleStep(100)
        self._end_ms.setSuffix(" ms")
        self._end_ms.setValue(current_time_ms + 2000)
        form.addRow("نهاية الوقت:", self._end_ms)

        # لوحة السيارة
        self._plate = QLineEdit(self)
        self._plate.setPlaceholderText("اختياري — مثل: أ ب ج 1234")
        form.addRow("لوحة السيارة:", self._plate)

        # رقم إطار الإثبات (اختياري)
        self._evidence_frame = QSpinBox(self)
        self._evidence_frame.setRange(-1, 10_000_000)
        self._evidence_frame.setValue(-1)
        self._evidence_frame.setSpecialValueText("غير محدد")
        form.addRow("رقم فريم الإثبات:", self._evidence_frame)

        # ملاحظات
        self._notes = QPlainTextEdit(self)
        self._notes.setPlaceholderText("سبب المخالفة أو ملاحظات إضافية...")
        self._notes.setMaximumHeight(80)
        form.addRow("ملاحظات:", self._notes)

        root.addLayout(form)

        # أزرار
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("حفظ")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("إلغاء")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate_from_existing(self, data: dict[str, Any]) -> None:
        # المقطع
        vid = int(data.get("video_id", 0))
        idx = self._video_combo.findData(vid)
        if idx >= 0:
            self._video_combo.setCurrentIndex(idx)
        # النوع
        vtype = str(data.get("violation_type", ""))
        idx = self._type_combo.findData(vtype)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._start_ms.setValue(int(data.get("start_ms", 0)))
        self._end_ms.setValue(int(data.get("end_ms", 0)))
        self._plate.setText(str(data.get("license_plate") or ""))
        notes = str(data.get("notes") or "")
        if notes.startswith("[manual] "):
            notes = notes[len("[manual] ") :]
        self._notes.setPlainText(notes)

    # ============================================
    # حفظ
    # ============================================
    def _on_accept(self) -> None:
        if not self._validate():
            return
        try:
            if self._existing:
                self._update_violation()
            else:
                self._insert_violation()
            self.accept()
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل حفظ المخالفة اليدوية")
            QMessageBox.critical(self, "فشل الحفظ", f"تعذّر الحفظ: {exc}")

    def _validate(self) -> bool:
        if self._video_combo.currentData() is None:
            QMessageBox.warning(self, "بيانات ناقصة", "يجب اختيار مقطع.")
            return False
        if self._end_ms.value() <= self._start_ms.value():
            QMessageBox.warning(self, "بيانات غير صحيحة", "نهاية الوقت يجب أن تكون بعد البداية.")
            return False
        return True

    def collect(self) -> ManualViolationData:
        """يجمع البيانات الحالية للحوار."""
        return ManualViolationData(
            video_id=int(self._video_combo.currentData()),
            violation_type=ViolationType(self._type_combo.currentData()),
            start_ms=int(self._start_ms.value()),
            end_ms=int(self._end_ms.value()),
            license_plate=self._plate.text().strip(),
            notes=self._notes.toPlainText().strip(),
            evidence_frame=(
                int(self._evidence_frame.value()) if self._evidence_frame.value() >= 0 else None
            ),
        )

    def _insert_violation(self) -> None:
        data = self.collect()
        evidence_json = (
            json.dumps([data.evidence_frame]) if data.evidence_frame is not None else "[]"
        )
        notes = f"[manual] {data.notes}" if data.notes else "[manual]"
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001
            user = "unknown"
        self._db.execute(
            """
            INSERT INTO violations (
                video_id, violation_type, start_ms, end_ms,
                confidence, evidence_frames, license_plate,
                review_status, notes, source, manual_user
            ) VALUES (?, ?, ?, ?, 1.0, ?, ?, 'confirmed', ?, 'manual', ?)
            """,
            (
                data.video_id,
                data.violation_type.value,
                data.start_ms,
                data.end_ms,
                evidence_json,
                data.license_plate or None,
                notes,
                user,
            ),
        )

    def _update_violation(self) -> None:
        assert self._existing is not None
        data = self.collect()
        evidence_json = (
            json.dumps([data.evidence_frame]) if data.evidence_frame is not None else "[]"
        )
        notes = f"[manual] {data.notes}" if data.notes else "[manual]"
        viol_id = int(self._existing["id"])
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001
            user = "unknown"
        # التعديل البشري يحوّل المخالفة إلى source='manual' حتى لا تُحذف عند
        # إعادة التحليل (DELETE ... AND source='auto')، ويُحدّث video_id أيضاً.
        self._db.execute(
            """
            UPDATE violations SET
                video_id = ?,
                violation_type = ?,
                start_ms = ?,
                end_ms = ?,
                evidence_frames = ?,
                license_plate = ?,
                notes = ?,
                source = 'manual',
                manual_user = ?
            WHERE id = ?
            """,
            (
                data.video_id,
                data.violation_type.value,
                data.start_ms,
                data.end_ms,
                evidence_json,
                data.license_plate or None,
                notes,
                user,
                viol_id,
            ),
        )


__all__ = ["ManualViolationData", "ManualViolationDialog"]
