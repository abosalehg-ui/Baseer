"""لوحة رسم فوق إطار فيديو — تلتقط النقرات لتعريف مناطق/نقاط معايرة.

قابلة للاختبار بلا فيديو حقيقي: تُحقن الصورة كـ QImage، والنقر يُحاكى بـ
`add_point_image_coords()`. الإحداثيات تُعاد دائماً بمقياس الصورة الأصلية
(لا بمقياس العرض) حتى تطابق bbox الكشوفات.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from app.utils.geometry import Point


class FrameCanvas(QWidget):
    """يعرض إطاراً ويجمع نقاطاً بالنقر (بإحداثيات الصورة الأصلية)."""

    points_changed = pyqtSignal()

    def __init__(self, image: QImage | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image or QImage()
        self._points: list[Point] = []
        self.setMinimumSize(320, 240)
        self.setMouseTracking(False)

    # ============================================
    # واجهة عامة
    # ============================================
    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    @property
    def has_image(self) -> bool:
        return not self._image.isNull()

    def points(self) -> list[Point]:
        """يعيد النقاط بإحداثيات الصورة الأصلية."""
        return list(self._points)

    def clear_points(self) -> None:
        self._points.clear()
        self.points_changed.emit()
        self.update()

    def undo_point(self) -> None:
        if self._points:
            self._points.pop()
            self.points_changed.emit()
            self.update()

    def add_point_image_coords(self, x: float, y: float) -> None:
        """يُضيف نقطة بإحداثيات الصورة مباشرة (يُستخدم في الاختبارات)."""
        self._points.append((float(x), float(y)))
        self.points_changed.emit()
        self.update()

    # ============================================
    # التحويل بين إحداثيات العرض والصورة
    # ============================================
    def _display_rect(self) -> tuple[float, float, float, float]:
        """يعيد (offset_x, offset_y, scale, _) لصورة مُحجَّمة مع الحفاظ على النسبة."""
        if self._image.isNull():
            return (0.0, 0.0, 1.0, 1.0)
        iw, ih = self._image.width(), self._image.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / iw, wh / ih) if iw and ih else 1.0
        disp_w, disp_h = iw * scale, ih * scale
        off_x = (ww - disp_w) / 2
        off_y = (wh - disp_h) / 2
        return (off_x, off_y, scale, scale)

    def _widget_to_image(self, pos: QPoint) -> Point | None:
        off_x, off_y, scale, _ = self._display_rect()
        if scale <= 0:
            return None
        ix = (pos.x() - off_x) / scale
        iy = (pos.y() - off_y) / scale
        if ix < 0 or iy < 0 or ix > self._image.width() or iy > self._image.height():
            return None
        return (ix, iy)

    # ============================================
    # أحداث
    # ============================================
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._image.isNull() or event.button() != Qt.MouseButton.LeftButton:
            return
        img_pt = self._widget_to_image(event.position().toPoint())
        if img_pt is not None:
            self._points.append(img_pt)
            self.points_changed.emit()
            self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202020"))
        if not self._image.isNull():
            off_x, off_y, scale, _ = self._display_rect()
            scaled = QPixmap.fromImage(self._image).scaled(
                int(self._image.width() * scale),
                int(self._image.height() * scale),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(int(off_x), int(off_y), scaled)
            self._draw_points(painter, off_x, off_y, scale)
        painter.end()

    def _draw_points(self, painter: QPainter, off_x: float, off_y: float, scale: float) -> None:
        pen = QPen(QColor("#e74c3c"))
        pen.setWidth(2)
        painter.setPen(pen)
        widget_pts = [
            QPoint(int(off_x + px * scale), int(off_y + py * scale)) for px, py in self._points
        ]
        for i, wp in enumerate(widget_pts):
            painter.drawEllipse(wp, 4, 4)
            if i > 0:
                painter.drawLine(widget_pts[i - 1], wp)


__all__ = ["FrameCanvas"]
