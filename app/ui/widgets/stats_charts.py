"""widgets رسوم بيانية بـ PyQtGraph للداشبورد.

خلفية الرسوم تتبع لوحة الثيم بدل فرض الأبيض دائماً: على ويندوز بثيم داكن كان
الداشبورد يعرض رسوماً بيضاء ساطعة وسط واجهة داكنة.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui import theme


def _bar_widget_or_label(title: str, data: list[tuple[str, int]], parent: QWidget) -> QWidget:
    """يبني bar chart عبر pyqtgraph، أو label بديل لو غير متاح."""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    title_label = QLabel(title, container)
    title_label.setStyleSheet("font-weight: bold;")
    layout.addWidget(title_label)

    if not data:
        empty = QLabel("لا توجد بيانات", container)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setProperty("role", "muted")
        layout.addWidget(empty)
        return container

    try:
        import pyqtgraph as pg
    except ImportError:
        # Fallback: نص بسيط
        for label, value in data:
            layout.addWidget(QLabel(f"  • {label}: {value}", container))
        return container

    palette = theme.active_palette()
    plot = pg.PlotWidget(parent=container)
    plot.setBackground(palette.plot_bg)
    _style_axes(plot, palette)
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    x = list(range(len(labels)))

    bar = pg.BarGraphItem(x=x, height=values, width=0.6, brush=palette.primary)
    plot.addItem(bar)
    plot.getAxis("bottom").setTicks([list(zip(x, labels, strict=False))])
    plot.setMinimumHeight(220)
    layout.addWidget(plot)
    return container


def make_bar_chart(
    title: str, data: list[tuple[str, int]], parent: QWidget | None = None
) -> QWidget:
    """يبني bar chart للعرض في الداشبورد."""
    return _bar_widget_or_label(title, data, parent or QWidget())


def make_line_chart(
    title: str, points: list[tuple[float, float]], parent: QWidget | None = None
) -> QWidget:
    """يبني line chart (e.g. مخالفات عبر الزمن)."""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(title, container))

    if not points:
        empty = QLabel("لا توجد بيانات", container)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setProperty("role", "muted")
        layout.addWidget(empty)
        return container

    try:
        import pyqtgraph as pg
    except ImportError:
        for x, y in points:
            layout.addWidget(QLabel(f"  • {x}: {y}", container))
        return container

    palette = theme.active_palette()
    plot = pg.PlotWidget(parent=container)
    plot.setBackground(palette.plot_bg)
    _style_axes(plot, palette)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    plot.plot(xs, ys, pen=pg.mkPen(palette.info, width=2), symbol="o")
    plot.setMinimumHeight(220)
    layout.addWidget(plot)
    return container


def make_heatmap(
    title: str,
    matrix: list[list[int]],
    *,
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    parent: QWidget | None = None,
) -> QWidget:
    """يبني خريطة حرارية (rows × cols)."""
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel(title, container))

    if not matrix or not matrix[0]:
        empty = QLabel("لا توجد بيانات", container)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setProperty("role", "muted")
        layout.addWidget(empty)
        return container

    try:
        import numpy as np
        import pyqtgraph as pg
    except ImportError:
        layout.addWidget(QLabel("pyqtgraph غير متاح", container))
        return container

    arr = np.array(matrix)
    img_view = pg.ImageView(parent=container)
    img_view.setImage(arr.T)  # transpose ليتطابق مع orientation العين
    img_view.ui.histogram.hide()
    img_view.ui.menuBtn.hide()
    img_view.ui.roiBtn.hide()
    img_view.setMinimumHeight(220)
    layout.addWidget(img_view)

    if row_labels and col_labels:
        layout.addWidget(QLabel(f"الصفوف: {', '.join(row_labels)}", container))
        layout.addWidget(QLabel(f"الأعمدة: {', '.join(map(str, col_labels))}", container))

    return container


def _style_axes(plot: object, palette: theme.Palette) -> None:
    """يلوّن محاور الرسم بلون نص الثيم حتى تبقى مقروءة في الوضعين."""
    for axis_name in ("bottom", "left"):
        try:
            axis = plot.getAxis(axis_name)
            axis.setPen(palette.plot_fg)
            axis.setTextPen(palette.plot_fg)
        except Exception:  # noqa: BLE001
            continue


__all__ = ["make_bar_chart", "make_heatmap", "make_line_chart"]
