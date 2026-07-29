"""النافذة الرئيسية للتطبيق — تحتوي خمسة تبويبات أساسية."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.ui.analysis_view import AnalysisView
from app.ui.annotator_view import AnnotatorView
from app.ui.dashboard_view import DashboardView
from app.ui.library_view import LibraryView
from app.ui.theme import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH
from app.ui.trainer_view import TrainerView

logger = logging.getLogger(__name__)


# ============================================
# تبويب placeholder بسيط للأسبوع 1
# ============================================
class PlaceholderTab(QWidget):
    """تبويب مؤقت يعرض اسم الوحدة وحالتها."""

    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel(title, self)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = title_lbl.font()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title_lbl.setFont(title_font)

        desc_lbl = QLabel(description, self)
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)

        status_lbl = QLabel("قيد التطوير — هذه الوحدة ستُفعَّل في مرحلة لاحقة", self)
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setProperty("role", "hint")

        layout.addStretch()
        layout.addWidget(title_lbl)
        layout.addSpacing(12)
        layout.addWidget(desc_lbl)
        layout.addSpacing(24)
        layout.addWidget(status_lbl)
        layout.addStretch()


# ============================================
# النافذة الرئيسية
# ============================================
class MainWindow(QMainWindow):
    """النافذة الرئيسية مع التبويبات الخمسة."""

    # (عنوان التبويب، الصنف) — تُبنى كسولاً عند أول ظهور
    _TAB_SPECS: tuple[tuple[str, type[QWidget]], ...] = (
        ("المكتبة", LibraryView),
        ("التصنيف", AnnotatorView),
        ("التدريب", TrainerView),
        ("التحليل", AnalysisView),
        ("الداشبورد", DashboardView),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} | Baseer  v{__version__}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        # حد أدنى يسع لابتوب 1366×768 — كان `resize(1280,800)` بلا حد أدنى،
        # فالنافذة أطول من الشاشة والمحتوى ينضغط بلا تمرير عند التصغير.
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resize(1280, 800)

        self._built_tabs: dict[int, QWidget] = {}
        self._build_tabs()
        self._build_menubar()
        self._build_statusbar()

    def _build_tabs(self) -> None:
        """يُنشئ التبويبات كأغلفة فارغة ويبني محتواها عند أول فتح.

        بناء التبويبات الخمسة فوراً كان يعني موجة استعلامات DuckDB متزامنة في
        الـmain thread (كل تبويب يستدعي `refresh()` في مُنشئه) **قبل** ظهور
        النافذة — إقلاع بطيء يتناسب مع حجم القاعدة.
        """
        tabs = QTabWidget(self)
        tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        for title, _cls in self._TAB_SPECS:
            placeholder = QWidget(tabs)
            QVBoxLayout(placeholder)
            tabs.addTab(placeholder, title)

        tabs.currentChanged.connect(self._ensure_tab_built)
        self.setCentralWidget(tabs)
        self._tabs = tabs
        self._ensure_tab_built(0)  # التبويب الأول يُبنى فوراً

    def _ensure_tab_built(self, index: int) -> None:
        """يبني محتوى التبويب عند أول فتح له."""
        if index < 0 or index in self._built_tabs:
            return
        title, widget_cls = self._TAB_SPECS[index]
        container = self._tabs.widget(index)
        layout = container.layout()
        if layout is None:
            return
        try:
            view = widget_cls(parent=container)
        except Exception:  # noqa: BLE001
            logger.exception("تعذّر بناء تبويب %s", title)
            error_label = QLabel(f"تعذّر تحميل تبويب «{title}» — راجع السجل.", container)
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(error_label)
            self._built_tabs[index] = error_label
            return
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)
        self._built_tabs[index] = view

    def current_view(self) -> QWidget | None:
        """الـview المبني في التبويب الحالي (أو None لو لم يُبنَ بعد)."""
        return self._built_tabs.get(self._tabs.currentIndex())

    def _build_menubar(self) -> None:
        menubar = self.menuBar()
        menubar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        file_menu = menubar.addMenu("ملف")
        refresh_action = QAction("تحديث التبويب الحالي", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)  # F5
        refresh_action.triggered.connect(self._refresh_current_tab)
        file_menu.addAction(refresh_action)
        file_menu.addSeparator()

        quit_action = QAction("خروج", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # تنقّل بلوحة المفاتيح بين التبويبات (Ctrl+1..Ctrl+5)
        view_menu = menubar.addMenu("عرض")
        for index, (title, _cls) in enumerate(self._TAB_SPECS):
            action = QAction(title, self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda _checked=False, i=index: self._tabs.setCurrentIndex(i))
            view_menu.addAction(action)

        help_menu = menubar.addMenu("مساعدة")
        about_action = QAction("عن التطبيق", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _refresh_current_tab(self) -> None:
        """يستدعي `refresh()` على التبويب الحالي إن كان يدعمه."""
        view = self.current_view()
        refresh = getattr(view, "refresh", None)
        if callable(refresh):
            refresh()

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("جاهز")
        self.setStatusBar(status)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """يُغلق اتصال قاعدة البيانات المفرد عند الخروج لتفريغ الـ WAL بأمان.

        ترك الاتصال مفتوحاً عند إغلاق مفاجئ كان يخلّف WAL بحالة وسطى — وهو
        السيناريو الذي استلزم آلية التعافي في db.py.
        """
        try:
            from app.core.db import reset_database_singleton

            reset_database_singleton()
        except Exception:  # noqa: BLE001
            logger.exception("تعذّر إغلاق قاعدة البيانات عند الخروج")
        super().closeEvent(event)

    def _show_about(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "عن بَصير",
            f"<h2>{__app_name__} | Baseer</h2>"
            f"<p>الإصدار {__version__}</p>"
            "<p>نظام تحليل المخالفات المرورية من الفيديوهات</p>"
            "<p>تطبيق سطح مكتب محلي بالكامل</p>",
        )
