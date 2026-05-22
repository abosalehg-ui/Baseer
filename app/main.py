"""نقطة دخول التطبيق."""

from __future__ import annotations

import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from app import __app_name_en__
from app.config import ensure_directories, get_settings
from app.core.db import get_database
from app.ui.main_window import MainWindow


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

    settings = get_settings()
    ensure_directories(settings)
    logger.info("بدء تشغيل بَصير — مسار البيانات: %s", settings.data_dir)

    db = get_database(settings)
    logger.info("قاعدة البيانات جاهزة في %s — الجداول: %s", db.path, db.list_tables())

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name_en__)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    _warn_if_ffmpeg_missing(logger)

    window = MainWindow()
    window.show()
    return app.exec()


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
