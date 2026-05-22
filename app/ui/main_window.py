"""النافذة الرئيسية للتطبيق — تحتوي خمسة تبويبات أساسية."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.ui.library_view import LibraryView


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
        status_lbl.setStyleSheet("color: #888; font-style: italic;")

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

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} | Baseer  v{__version__}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1280, 800)

        self._build_tabs()
        self._build_menubar()
        self._build_statusbar()

    def _build_tabs(self) -> None:
        tabs = QTabWidget(self)
        tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        tabs.addTab(LibraryView(parent=self), "المكتبة")
        tabs.addTab(
            PlaceholderTab("التصنيف", "التصنيف اليدوي المدعوم بـ pseudo-labeling عبر CVAT."),
            "التصنيف",
        )
        tabs.addTab(
            PlaceholderTab("التدريب", "fine-tuning موديل YOLO على البيانات المُصنَّفة."),
            "التدريب",
        )
        tabs.addTab(
            PlaceholderTab("التحليل", "تشغيل الموديل واستخراج المخالفات من المقاطع."),
            "التحليل",
        )
        tabs.addTab(
            PlaceholderTab("الداشبورد", "الإحصاءات والرسوم البيانية وتصدير الدراسات."),
            "الداشبورد",
        )

        self.setCentralWidget(tabs)
        self._tabs = tabs

    def _build_menubar(self) -> None:
        menubar = self.menuBar()
        menubar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        file_menu = menubar.addMenu("ملف")
        quit_action = QAction("خروج", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = menubar.addMenu("مساعدة")
        about_action = QAction("عن التطبيق", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("جاهز")
        self.setStatusBar(status)

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
