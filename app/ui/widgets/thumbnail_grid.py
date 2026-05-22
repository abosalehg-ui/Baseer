"""شبكة عرض thumbnails مع تحميل كسول."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStyle,
)


@dataclass(frozen=True)
class VideoCard:
    """بيانات بطاقة فيديو في الشبكة."""

    video_id: int
    filename: str
    duration_sec: float | None
    source_type: str | None
    thumbnail_path: str | None


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:d}:{sec:02d}"


class ThumbnailGrid(QListWidget):
    """شبكة thumbnails — تعرض VideoCard وتُصدر `card_activated` عند النقر."""

    card_activated = pyqtSignal(int)  # video_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(QSize(240, 135))
        self.setGridSize(QSize(260, 200))
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self.itemActivated.connect(self._on_activated)
        self.itemClicked.connect(self._on_activated)

    def set_cards(self, cards: list[VideoCard]) -> None:
        """يعيد ملء الشبكة بقائمة بطاقات جديدة."""
        self.clear()
        for card in cards:
            self.addItem(self._build_item(card))

    def _build_item(self, card: VideoCard) -> QListWidgetItem:
        item = QListWidgetItem()
        label = f"{card.filename}\n{_format_duration(card.duration_sec)}"
        if card.source_type:
            label += f" • {card.source_type}"
        item.setText(label)
        item.setData(Qt.ItemDataRole.UserRole, card.video_id)
        item.setIcon(self._load_icon(card.thumbnail_path))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _load_icon(self, thumbnail_path: str | None) -> QIcon:
        if thumbnail_path and Path(thumbnail_path).exists():
            pix = QPixmap(thumbnail_path)
            if not pix.isNull():
                return QIcon(pix)
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _on_activated(self, item: QListWidgetItem) -> None:
        video_id = item.data(Qt.ItemDataRole.UserRole)
        if video_id is not None:
            self.card_activated.emit(int(video_id))
