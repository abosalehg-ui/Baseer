"""شبكة عرض thumbnails مع تحميل الصور خارج الـmain thread.

قراءة ملف JPEG وبناء `QPixmap` لكل بطاقة كانت تجري في الـmain thread، فمكتبة
بـ500 مقطع = 500 قراءة قرص متزامنة تُجمّد الواجهة (رغم أن الصنف كان موصوفاً
بأنه «تحميل كسول»). الآن تُعرض أيقونة مؤقتة فوراً وتُحمَّل الصور في
`QThreadPool` ثم تُركَّب على البطاقات عند وصولها.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QWidget,
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


class _ThumbnailSignals(QObject):
    """إشارات مهمة التحميل (QRunnable لا يرث QObject)."""

    loaded = pyqtSignal(int, QImage)


class _ThumbnailTask(QRunnable):
    """يقرأ صورة thumbnail من القرص في thread من الـpool.

    نُرجع `QImage` لا `QPixmap`: بناء الـQPixmap مسموح في الـmain thread فقط.
    """

    def __init__(self, video_id: int, path: str, signals: _ThumbnailSignals) -> None:
        super().__init__()
        self._video_id = video_id
        self._path = path
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        image = QImage(self._path)
        if image.isNull():
            return
        # نُحجّم هنا (خارج الـmain thread) بدل ترك Qt يُحجّم عند كل رسم
        scaled = image.scaled(
            QSize(240, 135),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        try:
            self._signals.loaded.emit(self._video_id, scaled)
        except RuntimeError:
            # الشبكة أُغلقت أثناء التحميل — لا شيء نفعله
            pass


class ThumbnailGrid(QListWidget):
    """شبكة thumbnails — تعرض VideoCard وتُصدر `card_activated` عند النقر."""

    card_activated = pyqtSignal(int)  # video_id

    def __init__(self, parent: QWidget | None = None) -> None:
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

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance().maxThreadCount())))
        self._signals = _ThumbnailSignals()
        self._signals.loaded.connect(self._on_thumbnail_loaded)
        self._items_by_video: dict[int, QListWidgetItem] = {}

    def set_cards(self, cards: list[VideoCard]) -> None:
        """يعيد ملء الشبكة فوراً بأيقونات مؤقتة، ثم يحمّل الصور في الخلفية."""
        self.clear()
        self._items_by_video.clear()
        pending: list[tuple[int, str]] = []
        for card in cards:
            item = self._build_item(card)
            self.addItem(item)
            self._items_by_video[card.video_id] = item
            if card.thumbnail_path and Path(card.thumbnail_path).exists():
                pending.append((card.video_id, card.thumbnail_path))

        for video_id, path in pending:
            self._pool.start(_ThumbnailTask(video_id, path, self._signals))

    def _on_thumbnail_loaded(self, video_id: int, image: QImage) -> None:
        """يُركّب الصورة المُحمَّلة على بطاقتها (يعمل في الـmain thread)."""
        item = self._items_by_video.get(video_id)
        if item is None:
            return  # أُعيد ملء الشبكة أثناء التحميل
        pix = QPixmap.fromImage(image)
        if not pix.isNull():
            item.setIcon(QIcon(pix))

    def _build_item(self, card: VideoCard) -> QListWidgetItem:
        item = QListWidgetItem()
        label = f"{card.filename}\n{_format_duration(card.duration_sec)}"
        if card.source_type:
            label += f" • {card.source_type}"
        item.setText(label)
        item.setData(Qt.ItemDataRole.UserRole, card.video_id)
        item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        # وصف للوصول: قارئ الشاشة يحتاج بديلاً نصياً للصورة
        item.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            f"مقطع {card.filename}، المدة {_format_duration(card.duration_sec)}",
        )
        item.setToolTip(label)
        return item

    def wait_for_thumbnails(self, msecs: int = 5000) -> bool:
        """ينتظر انتهاء تحميل الصور — للاختبارات أساساً."""
        return bool(self._pool.waitForDone(msecs))

    def _on_activated(self, item: QListWidgetItem) -> None:
        video_id = item.data(Qt.ItemDataRole.UserRole)
        if video_id is not None:
            self.card_activated.emit(int(video_id))
