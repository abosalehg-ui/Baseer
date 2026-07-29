"""حوار مراجعة التكرارات — يعرض مجموعات التكرار (ثنائي/حسّي) ويسمح بحذف المكرر.

يبني فوق `LibraryService.detect_duplicates()` الموجودة أصلاً. التكرار الحسّي
(phash) لم يعد يُسقط تلقائياً (H2) فصار يُراجَع هنا يدوياً.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.library import LibraryService

logger = logging.getLogger(__name__)

_MATCH_LABELS = {"exact": "تطابق ثنائي", "perceptual": "تشابه بصري"}


class DuplicatesDialog(QDialog):
    """يعرض مجموعات التكرار ويحذف المكرر مع الإبقاء على الممثِّل."""

    def __init__(self, *, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("مراجعة التكرارات")
        self.setMinimumSize(640, 480)
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "كل مجموعة تحتوي مقطعاً ممثِّلاً (يُبقى) ومقاطع مكررة. "
                "اختر المكررات واحذفها بأمان.",
                self,
            )
        )

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["المقطع", "النوع"])
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self._tree, stretch=1)

        self._summary = QLabel("", self)
        root.addWidget(self._summary)

        bottom = QHBoxLayout()
        del_btn = QPushButton("حذف المكررات المختارة", self)
        del_btn.clicked.connect(self._on_delete_selected)
        bottom.addWidget(del_btn)
        bottom.addStretch()
        reload_btn = QPushButton("إعادة الفحص", self)
        reload_btn.clicked.connect(self.reload)
        bottom.addWidget(reload_btn)
        close_btn = QPushButton("إغلاق", self)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    def reload(self) -> None:
        self._tree.clear()
        groups = self._service.detect_duplicates()
        filenames = self._filename_map()
        total_dupes = 0
        for i, group in enumerate(groups, start=1):
            match_label = _MATCH_LABELS.get(group.match_type, group.match_type)
            parent = QTreeWidgetItem(
                [f"مجموعة {i} — الممثِّل #{group.representative_id}", match_label]
            )
            parent.setData(0, Qt.ItemDataRole.UserRole, None)  # الممثِّل غير قابل للحذف هنا
            for dup_id in group.duplicate_ids:
                child = QTreeWidgetItem([f"#{dup_id}  {filenames.get(dup_id, '')}", match_label])
                child.setData(0, Qt.ItemDataRole.UserRole, dup_id)
                parent.addChild(child)
                total_dupes += 1
            self._tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        self._summary.setText(
            f"{len(groups)} مجموعة تكرار — {total_dupes} مقطع مكرر قابل للحذف"
            if groups
            else "لا توجد تكرارات."
        )

    def _selected_duplicate_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self._tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data is not None:
                ids.append(int(data))
        return ids

    def _on_delete_selected(self) -> None:
        ids = self._selected_duplicate_ids()
        if not ids:
            QMessageBox.information(self, "لا يوجد اختيار", "اختر مقاطع مكررة للحذف.")
            return
        confirm = QMessageBox.question(
            self,
            "تأكيد الحذف",
            f"<b>حذف {len(ids)} مقطع مكرر من القاعدة؟</b> لا يمكن التراجع.<br><br>"
            "سيُحذف سجل المقطع وكشوفاته ومخالفاته والصورة المصغّرة.<br>"
            "⚠️ <b>ملف الفيديو نفسه يبقى على القرص</b> — احذفه يدوياً إن أردت "
            "إزالة محتواه (وجوه/لوحات) فعلياً.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for vid in ids:
            try:
                self._service.delete_video(vid)
            except Exception as exc:  # noqa: BLE001
                logger.exception("فشل حذف المقطع %d", vid)
                QMessageBox.critical(self, "فشل الحذف", f"المقطع #{vid}: {exc}")
        self.reload()

    def _filename_map(self) -> dict[int, str]:
        return dict(self._service.video_names())


__all__ = ["DuplicatesDialog"]
