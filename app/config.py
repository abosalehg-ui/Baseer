"""إعدادات التطبيق — تُقرأ من متغيرات البيئة (.env)."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_frozen() -> bool:
    """هل التطبيق يعمل من داخل PyInstaller bundle؟"""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _user_data_dir() -> Path:
    """جذر بيانات المستخدم — قابل للكتابة في كل المنصات.

    - Windows: %LOCALAPPDATA%\\Baseer
    - macOS:   ~/Library/Application Support/Baseer
    - Linux:   $XDG_DATA_HOME/Baseer أو ~/.local/share/Baseer
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "Baseer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Baseer"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) / "Baseer" if xdg else Path.home() / ".local" / "share" / "Baseer"


def _default_root() -> Path:
    """جذر افتراضي للبيانات/الـlogs.

    - عند تشغيل PyInstaller bundle: مسار قابل للكتابة في user data dir
    - عند التطوير المحلي: جذر المستودع كما كان
    """
    if _is_frozen():
        return _user_data_dir()
    return PROJECT_ROOT


def _env_file_path() -> Path:
    """مسار ملف .env — في user data dir للـbundle، وفي جذر المشروع للتطوير."""
    if _is_frozen():
        return _user_data_dir() / ".env"
    return PROJECT_ROOT / ".env"


_DEFAULT_ROOT = _default_root()


class AppSettings(BaseSettings):
    """إعدادات التطبيق الشاملة."""

    model_config = SettingsConfigDict(
        env_file=_env_file_path(),
        env_file_encoding="utf-8",
        env_prefix="BASEER_",
        extra="ignore",
        case_sensitive=False,
    )

    data_dir: Path = Field(default=_DEFAULT_ROOT / "data")
    models_dir: Path = Field(default=_DEFAULT_ROOT / "models")
    db_path: Path = Field(default=_DEFAULT_ROOT / "data" / "results.duckdb")

    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=_DEFAULT_ROOT / "logs" / "baseer.log")

    ui_theme: str = Field(default="dark")
    ui_language: str = Field(default="ar")

    cuda_device: int = Field(default=0)

    # الخصوصية والتصدير
    # ملح تجهيل أرقام اللوحات — تغييره يفصل رموز دراسة عن أخرى
    anon_salt: str = Field(default="baseer-default-salt")
    # مسار خط عربي بديل لتقارير PDF (فارغ = الخط المُرفَق في assets/fonts/)
    pdf_font: str = Field(default="")


class CvatSettings(BaseSettings):
    """إعدادات تكامل CVAT (تُقرأ بدون البادئة)."""

    model_config = SettingsConfigDict(
        env_file=_env_file_path(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    cvat_url: str = Field(default="http://localhost:8080")
    cvat_username: str = Field(default="admin")
    # ملاحظة: لا حقل لكلمة المرور عمداً. التطبيق يفتح CVAT في المتصفح فقط،
    # فحقل سرّ موثَّق ولا يستهلكه أي كود يدعو المستخدم لكتابة كلمة مرور
    # بنص عادي بلا فائدة. عند إضافة تكامل REST تُقرأ من keyring نظام التشغيل.


@lru_cache(maxsize=1)
def _cached_settings() -> AppSettings:
    return AppSettings()


@lru_cache(maxsize=1)
def _cached_cvat_settings() -> CvatSettings:
    return CvatSettings()


def get_settings() -> AppSettings:
    """يعيد إعدادات التطبيق الأساسية (مُخزَّنة مؤقتاً).

    كانت تُنشئ `AppSettings()` جديدة في كل استدعاء — أي إعادة قراءة وتحليل
    لملف `.env` من القرص في مُنشئ كل خدمة وكل عنصر واجهة. الإعدادات ثابتة
    طوال عمر العملية، فنقرأها مرة واحدة. للاختبارات: `reset_settings_cache()`.
    """
    return _cached_settings()


def get_cvat_settings() -> CvatSettings:
    """يعيد إعدادات تكامل CVAT (مُخزَّنة مؤقتاً)."""
    return _cached_cvat_settings()


def reset_settings_cache() -> None:
    """يُفرّغ ذاكرة الإعدادات — للاختبارات التي تُعدّل متغيرات البيئة."""
    _cached_settings.cache_clear()
    _cached_cvat_settings.cache_clear()


def ensure_directories(settings: AppSettings | None = None) -> None:
    """يتأكد من وجود كل المجلدات الضرورية."""
    s = settings or get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.models_dir.mkdir(parents=True, exist_ok=True)
    s.log_file.parent.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "videos").mkdir(exist_ok=True)
    (s.data_dir / "thumbnails").mkdir(exist_ok=True)
    (s.data_dir / "frames").mkdir(exist_ok=True)
    (s.data_dir / "exports").mkdir(exist_ok=True)
    (s.data_dir / "annotations" / "raw").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "annotations" / "reviewed").mkdir(parents=True, exist_ok=True)
