"""مربع حوار إضافة/تعديل مخالفة يدوية."""

from __future__ import annotations

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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.constants import VIOLATION_ARABIC_NAMES, ViolationType
from app.core.dashboard import DashboardService
from app.core.db import Database, get_database

logger = logging.getLogger(__name__)

# حدود المدخلات: لوحة سعودية لا تتجاوز 12 محرفاً بالمسافات، والملاحظة سطر شرح
# لا مستند. بلا حدود يمكن حفظ ميغابايتات من النص في حقل VARCHAR.
MAX_PLATE_LENGTH = 12
MAX_NOTES_LENGTH = 2000


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
        # الكتابة تمرّ عبر الخدمة (تسجّل التدقيق) بدل SQL خام في الحوار
        self._service = DashboardService(db=self._db)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("تعديل مخالفة يدوية" if existing else "إضافة مخالفة يدوية")
        self.setMinimumWidth(420)
        self._build_ui(current_time_ms)
        if existing:
            self._populate_from_existing(existing)

    # ============================================
    # واجهة
    # ============================================
    def _build_ui(self, current_time_ms: int | None) -> None:
        root = QVBoxLayout(self)

        # تحويل مخالفة تلقائية إلى يدوية قرار له أثر (لا تُحذف عند إعادة
        # التحليل) — كان يحدث بصمت. نُعلم المستخدم قبل الحفظ.
        if self._existing and str(self._existing.get("source") or "auto") != "manual":
            notice = QLabel(
                "ℹ️ هذه مخالفة <b>تلقائية</b>. حفظ التعديل سيحوّلها إلى <b>يدوية</b>، "
                "فلن تُحذف عند إعادة تحليل المقطع.",
                self,
            )
            notice.setWordWrap(True)
            notice.setProperty("role", "hint")
            root.addWidget(notice)

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

        # بداية الوقت — زر «الوقت المقترح» يظهر فقط عند وجود وقت حقيقي يقترحه
        # (كان يظهر دائماً ويعيد 0 لأن المستدعي لم يمرّر أي وقت).
        seed_ms = current_time_ms or 0
        start_row = QHBoxLayout()
        self._start_ms = QSpinBox(self)
        self._start_ms.setRange(0, 24 * 3600 * 1000)
        self._start_ms.setSingleStep(100)
        self._start_ms.setSuffix(" ms")
        self._start_ms.setValue(seed_ms)
        self._start_ms.setAccessibleName("بداية المخالفة بالميلي ثانية")
        start_row.addWidget(self._start_ms, stretch=1)
        if current_time_ms is not None:
            use_now_btn = QPushButton("الوقت المقترح", self)
            use_now_btn.setToolTip(f"يعيد الوقت المقترح ({seed_ms} ms)")
            use_now_btn.clicked.connect(lambda: self._start_ms.setValue(seed_ms))
            start_row.addWidget(use_now_btn)
        form.addRow("بداية الوقت:", start_row)

        # نهاية الوقت
        self._end_ms = QSpinBox(self)
        self._end_ms.setRange(0, 24 * 3600 * 1000)
        self._end_ms.setSingleStep(100)
        self._end_ms.setSuffix(" ms")
        self._end_ms.setValue(seed_ms + 2000)
        self._end_ms.setAccessibleName("نهاية المخالفة بالميلي ثانية")
        form.addRow("نهاية الوقت:", self._end_ms)

        # لوحة السيارة — حد الطول يمنع حشو القاعدة بنص لا معنى له
        self._plate = QLineEdit(self)
        self._plate.setPlaceholderText("اختياري — مثل: أ ب ج 1234")
        self._plate.setMaxLength(MAX_PLATE_LENGTH)
        self._plate.setAccessibleName("رقم لوحة المركبة")
        form.addRow("لوحة السيارة:", self._plate)

        # رقم إطار الإثبات (اختياري)
        self._evidence_frame = QSpinBox(self)
        self._evidence_frame.setRange(-1, 10_000_000)
        self._evidence_frame.setValue(-1)
        self._evidence_frame.setSpecialValueText("غير محدد")
        form.addRow("رقم فريم الإثبات:", self._evidence_frame)

        # ملاحظات — بلا حد كان يمكن حفظ ميغابايتات من النص في القاعدة
        self._notes = QPlainTextEdit(self)
        self._notes.setPlaceholderText("سبب المخالفة أو ملاحظات إضافية...")
        self._notes.setMaximumHeight(80)
        self._notes.setAccessibleName("ملاحظات المخالفة")
        self._notes_counter = QLabel("", self)
        self._notes_counter.setProperty("role", "muted")
        self._notes.textChanged.connect(self._on_notes_changed)
        self._on_notes_changed()
        form.addRow("ملاحظات:", self._notes)
        form.addRow("", self._notes_counter)

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
        self._set_tab_order(buttons)

    def _set_tab_order(self, buttons: QDialogButtonBox) -> None:
        """ترتيب تنقّل لوحة المفاتيح صريح لا تابعاً لترتيب الإنشاء.

        الترتيب الضمني يتبع ترتيب بناء الودجات، وهو يتفرّق هنا لأن صف «بداية
        الوقت» يحوي تخطيطاً متداخلاً وصف الملاحظات يحوي عدّاداً — فنُثبّته صراحةً
        بالترتيب المنطقي: المقطع ← النوع ← الأوقات ← اللوحة ← الفريم ← الملاحظات
        ← الأزرار.
        """
        chain: list[QWidget] = [
            self._video_combo,
            self._type_combo,
            self._start_ms,
            self._end_ms,
            self._plate,
            self._evidence_frame,
            self._notes,
            buttons,
        ]
        # الإزاحة مقصودة (كل عنصر مع تاليه) فالطولان مختلفان عمداً
        for first, second in zip(chain, chain[1:], strict=False):
            self.setTabOrder(first, second)
        self._video_combo.setFocus()

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

    def _on_notes_changed(self) -> None:
        """يقصّ الملاحظات عند الحد ويُظهر العدّاد."""
        text = self._notes.toPlainText()
        if len(text) > MAX_NOTES_LENGTH:
            cursor_position = self._notes.textCursor().position()
            self._notes.blockSignals(True)
            self._notes.setPlainText(text[:MAX_NOTES_LENGTH])
            cursor = self._notes.textCursor()
            cursor.setPosition(min(cursor_position, MAX_NOTES_LENGTH))
            self._notes.setTextCursor(cursor)
            self._notes.blockSignals(False)
            text = self._notes.toPlainText()
        self._notes_counter.setText(f"{len(text)} / {MAX_NOTES_LENGTH} محرف")

    def _validate(self) -> bool:
        if self._video_combo.currentData() is None:
            QMessageBox.warning(self, "بيانات ناقصة", "يجب اختيار مقطع.")
            return False
        if self._end_ms.value() <= self._start_ms.value():
            QMessageBox.warning(self, "بيانات غير صحيحة", "نهاية الوقت يجب أن تكون بعد البداية.")
            return False
        return self._validate_within_duration()

    def _validate_within_duration(self) -> bool:
        """يمنع وقتاً خارج مدة المقطع.

        المدى كان ثابتاً (0 → 24 ساعة) بلا علم بالمقطع، فمخالفة عند الساعة
        الثالثة على مقطع 30 ثانية تُقبَل وتُخزَّن — بيانات لا معنى لها ولا شيء
        يمنعها.
        """
        duration_ms = self._duration_ms_for_selected_video()
        if duration_ms is None:
            return True
        if self._end_ms.value() > duration_ms:
            QMessageBox.warning(
                self,
                "وقت خارج المقطع",
                f"مدة المقطع {duration_ms} ms — "
                f"لا يمكن أن تنتهي المخالفة عند {self._end_ms.value()} ms.",
            )
            return False
        return True

    def _duration_ms_for_selected_video(self) -> int | None:
        """مدة المقطع المختار بالمللي ثانية، أو None لو غير معروفة."""
        video_id = self._video_combo.currentData()
        if video_id is None:
            return None
        row = self._db.fetch_one("SELECT duration_sec FROM videos WHERE id = ?", (int(video_id),))
        if row is None or row[0] is None:
            return None
        duration = float(row[0])
        return int(duration * 1000) if duration > 0 else None

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

    def _payload(self) -> tuple[ManualViolationData, str, str]:
        """يجمع البيانات ويبني (data, evidence_json, notes) المشتركة بين الإدراج والتعديل."""
        data = self.collect()
        evidence_json = (
            json.dumps([data.evidence_frame]) if data.evidence_frame is not None else "[]"
        )
        notes = f"[manual] {data.notes}" if data.notes else "[manual]"
        return data, evidence_json, notes

    def _insert_violation(self) -> None:
        data, evidence_json, notes = self._payload()
        self._service.insert_manual_violation(
            video_id=data.video_id,
            violation_type=data.violation_type.value,
            start_ms=data.start_ms,
            end_ms=data.end_ms,
            evidence_frames_json=evidence_json,
            license_plate=data.license_plate or None,
            notes=notes,
        )

    def _update_violation(self) -> None:
        if self._existing is None:  # pragma: no cover - لا يُستدعى إلا في وضع التعديل
            raise RuntimeError("لا توجد مخالفة قائمة للتعديل")
        data, evidence_json, notes = self._payload()
        self._service.update_violation_as_manual(
            int(self._existing["id"]),
            video_id=data.video_id,
            violation_type=data.violation_type.value,
            start_ms=data.start_ms,
            end_ms=data.end_ms,
            evidence_frames_json=evidence_json,
            license_plate=data.license_plate or None,
            notes=notes,
        )


__all__ = ["ManualViolationData", "ManualViolationDialog"]
