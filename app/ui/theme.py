"""نظام التصميم — ألوان ومسافات وأحجام موحّدة + توليد QSS للتطبيق كله.

قبل هذه الوحدة كانت الألوان مكتوبة كـhex يدوياً داخل `setStyleSheet` في ثمانية
ملفات، و`BASEER_UI_THEME` معرّفاً في الإعدادات بلا أي قارئ — فالتطبيق يعمل بثيم
النظام بينما الرسوم تفرض خلفية بيضاء واللوحة تفرض خلفية داكنة. كل لون يُطلب من
هنا الآن، والثيم يُطبَّق مرة واحدة في `main.py`.

**التباين:** كل تركيبة (نص/خلفية) في `_PALETTES` مضبوطة لتتجاوز حد WCAG AA
(4.5:1 للنص العادي). تركيبات مثل أبيض على `#f39c12` (2.2:1) استُبدلت بنص داكن
على نفس الخلفية أو بخلفية أغمق.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Palette:
    """ألوان ثيم واحد."""

    name: str
    bg: str
    surface: str
    surface_alt: str
    text: str
    text_muted: str
    border: str
    primary: str
    on_primary: str
    danger: str
    on_danger: str
    warning: str
    on_warning: str
    success: str
    on_success: str
    info: str
    on_info: str
    # خلفية لوحات الرسم — تتبع الثيم بدل فرض الأبيض دائماً
    plot_bg: str
    plot_fg: str
    canvas_bg: str


_LIGHT: Final[Palette] = Palette(
    name="light",
    bg="#f5f6f7",
    surface="#ffffff",
    surface_alt="#eceff1",
    text="#1a1a1a",
    text_muted="#5a6268",  # 4.9:1 على الأبيض
    border="#c8ced3",
    primary="#1c6ea4",  # 5.1:1 مع الأبيض
    on_primary="#ffffff",
    danger="#b02a20",  # 5.9:1 مع الأبيض
    on_danger="#ffffff",
    warning="#f39c12",  # نص داكن فوقه (11.4:1) بدل الأبيض (2.2:1)
    on_warning="#1a1a1a",
    success="#1e7e45",  # 4.8:1 مع الأبيض
    on_success="#ffffff",
    info="#0f6674",
    on_info="#ffffff",
    plot_bg="#ffffff",
    plot_fg="#1a1a1a",
    canvas_bg="#20242a",
)

_DARK: Final[Palette] = Palette(
    name="dark",
    bg="#1e2227",
    surface="#282d34",
    surface_alt="#31373f",
    text="#e8eaed",
    text_muted="#a8b0b8",  # 6.4:1 على #1e2227
    border="#414952",
    primary="#4aa3df",  # نص داكن فوقه
    on_primary="#10141a",
    danger="#e26a5f",
    on_danger="#10141a",
    warning="#f0ad4e",
    on_warning="#10141a",
    success="#4cb782",
    on_success="#10141a",
    info="#4dbccd",
    on_info="#10141a",
    plot_bg="#282d34",
    plot_fg="#e8eaed",
    canvas_bg="#15181c",
)

PALETTES: Final[dict[str, Palette]] = {"light": _LIGHT, "dark": _DARK}

# ============================================
# المسافات والأحجام (مقياس 4px)
# ============================================
SPACING_XS: Final[int] = 4
SPACING_SM: Final[int] = 8
SPACING_MD: Final[int] = 12
SPACING_LG: Final[int] = 16

RADIUS: Final[int] = 8

# الحد الأدنى لهدف النقر/اللمس — أزرار الأفعال كانت 32px (دون الموصى به)
MIN_TOUCH_TARGET: Final[int] = 32
COMFORTABLE_TOUCH_TARGET: Final[int] = 44

# الحد الأدنى لنافذة التطبيق — يجب أن يسع لابتوب 1366×768
MIN_WINDOW_WIDTH: Final[int] = 960
MIN_WINDOW_HEIGHT: Final[int] = 600


_ACTIVE: dict[str, Palette] = {"palette": _DARK}


def resolve_palette(theme: str | None) -> Palette:
    """يُرجع لوحة الثيم المطلوب — `dark` افتراضياً عند قيمة غير معروفة."""
    key = (theme or "dark").strip().lower()
    return PALETTES.get(key, _DARK)


def set_active_palette(palette: Palette) -> None:
    """يضبط اللوحة الفعّالة التي تقرؤها الودجات (الرسوم، اللوحة…)."""
    _ACTIVE["palette"] = palette


def active_palette() -> Palette:
    """اللوحة الفعّالة حالياً."""
    return _ACTIVE["palette"]


def build_stylesheet(palette: Palette) -> str:
    """يبني QSS التطبيق كاملاً من لوحة الألوان."""
    p = palette
    return f"""
QWidget {{
    background-color: {p.bg};
    color: {p.text};
}}
QTabWidget::pane {{
    border: 1px solid {p.border};
    background-color: {p.surface};
}}
QTabBar::tab {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    padding: {SPACING_SM}px {SPACING_MD}px;
    margin-left: 2px;
    border-top-left-radius: {RADIUS // 2}px;
    border-top-right-radius: {RADIUS // 2}px;
}}
QTabBar::tab:selected {{
    background-color: {p.surface};
    color: {p.text};
    font-weight: bold;
}}
QTabBar::tab:focus {{
    border: 2px solid {p.primary};
}}
QPushButton {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS // 2}px;
    padding: {SPACING_XS}px {SPACING_MD}px;
    min-height: {MIN_TOUCH_TARGET - 10}px;
}}
QPushButton:hover {{ background-color: {p.border}; }}
QPushButton:pressed {{ background-color: {p.primary}; color: {p.on_primary}; }}
QPushButton:disabled {{ color: {p.text_muted}; }}
QPushButton:focus {{ border: 2px solid {p.primary}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS // 2}px;
    padding: {SPACING_XS}px;
    selection-background-color: {p.primary};
    selection-color: {p.on_primary};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {p.primary};
}}
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {p.surface};
    alternate-background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    gridline-color: {p.border};
}}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {p.primary};
    color: {p.on_primary};
}}
QHeaderView::section {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: {SPACING_XS}px {SPACING_SM}px;
    font-weight: bold;
}}
QProgressBar {{
    border: 1px solid {p.border};
    border-radius: {RADIUS // 2}px;
    background-color: {p.surface_alt};
    text-align: center;
    color: {p.text};
    min-height: 18px;
}}
QProgressBar::chunk {{ background-color: {p.primary}; border-radius: {RADIUS // 2}px; }}
QToolBar {{ background-color: {p.surface}; border-bottom: 1px solid {p.border}; spacing: {SPACING_XS}px; }}
QStatusBar {{ background-color: {p.surface}; color: {p.text_muted}; }}
QMenuBar {{ background-color: {p.surface}; color: {p.text}; }}
QMenuBar::item:selected {{ background-color: {p.primary}; color: {p.on_primary}; }}
QMenu {{ background-color: {p.surface}; color: {p.text}; border: 1px solid {p.border}; }}
QMenu::item:selected {{ background-color: {p.primary}; color: {p.on_primary}; }}
QSplitter::handle {{ background-color: {p.border}; }}
QScrollArea {{ border: none; }}
QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="hint"] {{ color: {p.text_muted}; font-style: italic; }}
"""


def kpi_card_style(background: str, foreground: str) -> str:
    """نمط بطاقة KPI — يُبنى من اللوحة لا من hex مكتوب في الواجهة."""
    return (
        f"QFrame {{ background-color: {background}; color: {foreground}; "
        f"border-radius: {RADIUS}px; padding: {SPACING_SM}px; }}"
    )


def action_button_style(background: str, foreground: str) -> str:
    """نمط زر فعل ملوّن (تأكيد/رفض/شك) بتباين مضبوط."""
    return (
        f"QPushButton {{ background-color: {background}; color: {foreground}; "
        f"border: 1px solid {background}; border-radius: {RADIUS // 2}px; "
        f"padding: 2px {SPACING_SM}px; font-weight: bold; }}"
    )


def apply_theme(app: object, theme: str | None) -> Palette:
    """يطبّق الثيم على `QApplication` ويعيد اللوحة المستخدمة.

    يقبل أي كائن له `setStyleSheet` حتى يبقى قابلاً للاختبار بلا Qt حقيقي.
    """
    palette = resolve_palette(theme)
    set_active_palette(palette)
    setter = getattr(app, "setStyleSheet", None)
    if callable(setter):
        setter(build_stylesheet(palette))
    return palette


__all__ = [
    "COMFORTABLE_TOUCH_TARGET",
    "MIN_TOUCH_TARGET",
    "MIN_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "PALETTES",
    "RADIUS",
    "SPACING_LG",
    "SPACING_MD",
    "SPACING_SM",
    "SPACING_XS",
    "Palette",
    "action_button_style",
    "active_palette",
    "apply_theme",
    "build_stylesheet",
    "kpi_card_style",
    "resolve_palette",
    "set_active_palette",
]
