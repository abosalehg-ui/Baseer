"""نقطة دخول التطبيق."""

from __future__ import annotations

import html
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from app import __app_name_en__
from app.config import ensure_directories, get_settings
from app.core.db import get_database
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


def _configure_logging() -> None:
    """يُهيّئ سجلات التشغيل (stdout + ملف دوّار)."""
    settings = get_settings()
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    file_handler = RotatingFileHandler(
        settings.log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def main() -> int:
    """يُشغّل التطبيق."""
    _configure_logging()
    logger = logging.getLogger(__name__)

    # ⚠️ ترتيب مقصود: `QApplication` **قبل** أي تهيئة قد تفشل.
    # سابقاً كانت تهيئة القاعدة تسبق إنشاء التطبيق، فأي فشل (نسخة ثانية تحتفظ
    # بالقفل، صلاحيات، قرص ممتلئ) يقتل العملية بـtraceback في stdout — وفي بناء
    # PyInstaller بـ`console=False` لا يوجد stdout أصلاً، فالمستخدم ينقر
    # الأيقونة ولا يحدث شيء إطلاقاً.
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name_en__)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    try:
        settings = get_settings()
        ensure_directories(settings)
        logger.info("بدء تشغيل بَصير — مسار البيانات: %s", settings.data_dir)

        db = get_database(settings)
        logger.info("قاعدة البيانات جاهزة في %s — الجداول: %s", db.path, db.list_tables())
    except Exception as exc:  # noqa: BLE001
        logger.exception("فشل تهيئة التطبيق")
        _show_startup_error(exc)
        return 1

    # الثيم يُطبَّق مرة واحدة على مستوى التطبيق من `BASEER_UI_THEME`
    palette = apply_theme(app, settings.ui_theme)
    logger.info("الثيم المُطبَّق: %s", palette.name)

    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    _warn_if_ffmpeg_missing(logger)

    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


def _show_startup_error(exc: Exception) -> None:
    """يعرض سبب فشل الإقلاع في نافذة — لا في stdout الذي قد لا يوجد."""
    settings_hint = ""
    if isinstance(exc, PermissionError | OSError):
        settings_hint = (
            "<br><br><b>أسباب شائعة:</b><br>"
            "• نسخة أخرى من بَصير تعمل وتحتفظ بقفل القاعدة<br>"
            "• لا توجد صلاحية كتابة في مجلد البيانات<br>"
            "• القرص ممتلئ"
        )
    QMessageBox.critical(
        None,
        "تعذّر تشغيل بَصير",
        "<b>فشلت تهيئة التطبيق.</b><br><br>"
        f"<code>{html.escape(str(exc))}</code>"
        f"{settings_hint}<br><br>"
        "التفاصيل الكاملة في ملف السجل.",
    )


def _load_app_icon() -> QIcon:
    """يحمّل أيقونة التطبيق — يدعم التشغيل المباشر وتشغيل PyInstaller الـbundle."""
    candidates: list[Path] = []
    # bundle PyInstaller يضع الملفات في sys._MEIPASS
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "icon.ico")
        candidates.append(Path(meipass) / "assets" / "icon.png")
    # التشغيل المباشر من المستودع
    repo_assets = Path(__file__).resolve().parent.parent / "assets"
    candidates.append(repo_assets / "icon.ico")
    candidates.append(repo_assets / "icon.png")
    for path in candidates:
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def _warn_if_ffmpeg_missing(logger: logging.Logger) -> None:
    """يحذّر المستخدم عند بدء التطبيق لو ffmpeg/ffprobe غير موجود."""
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if not missing:
        return
    logger.warning("FFmpeg غير موجود في PATH: %s", missing)
    QMessageBox.warning(
        None,
        "FFmpeg غير مثبَّت",
        "<b>تحذير:</b> لم يُعثر على "
        f"<code>{' و '.join(missing)}</code> في PATH.<br><br>"
        "استيراد الفيديوهات وتوليد الـ thumbnails سيفشل بدونه.<br><br>"
        "<b>طريقة التثبيت السريعة (PowerShell):</b><br>"
        "<code>winget install --id Gyan.FFmpeg</code><br><br>"
        "بعد التثبيت، أعد فتح PowerShell وشغّل التطبيق من جديد.",
    )


if __name__ == "__main__":
    sys.exit(main())
