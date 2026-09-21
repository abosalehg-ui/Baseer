"""حوار تعيين تاريخ تسجيل المقطع يدوياً.

`recorded_at` يُستخرج من tags الفيديو، وهي غائبة في أكثر المصادر الواقعية
(واتساب، إعادة ترميز، تنزيل من سوشل ميديا). وكل التجميعات الزمنية في الداشبورد
تشترط وجوده، فمقطع بلا تاريخ تُستثنى كل مخالفاته من خريطة «أيام × ساعات» ومن
توزيع الساعات. هذا الحوار يجعل المعلومة قابلة للإدخال بدل أن تكون خسارة نهائية.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class RecordedAtDialog(QDialog):
    """يطلب تاريخ ووقت تسجيل المقطع."""

    def __init__(
        self,
        *,
        filename: str,
        current: datetime | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("تاريخ تسجيل المقطع")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        hint = QLabel(
            f"<b>{filename}</b><br>"
            "التاريخ يُستخدم في الرسوم الزمنية (توزيع الساعات والخريطة الحرارية). "
            "لحظة كل مخالفة تُحسب من هذا التاريخ + موضعها داخل المقطع.",
            self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self._edit = QDateTimeEdit(self)
        self._edit.setCalendarPopup(True)
        self._edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._edit.setAccessibleName("تاريخ ووقت تسجيل المقطع")
        self._edit.setDateTime(
            QDateTime(current) if current is not None else QDateTime.currentDateTime()
        )
        form.addRow("تاريخ التسجيل:", self._edit)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("حفظ")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self) -> datetime:
        """التاريخ المختار."""
        return self._edit.dateTime().toPyDateTime()


__all__ = ["RecordedAtDialog"]
