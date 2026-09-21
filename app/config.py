"""إعدادات التطبيق — تُقرأ من متغيرات البيئة (.env)."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# الملح المنشور في `.env.example` — وجوده يعني أن التجهيل قابل للعكس عملياً
DEFAULT_ANON_SALT = "baseer-default-salt"
_ANON_SALT_ENV = "BASEER_ANON_SALT"


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
    # ملح تجهيل أرقام اللوحات — تغييره يفصل رموز دراسة عن أخرى.
    # القيمة الافتراضية **معروفة للجميع** (منشورة في هذا المستودع وفي
    # .env.example)، وفضاء اللوحة السعودية صغير (≈10⁷)، فمن يحصل على ملف مجهّل
    # يبني جدول أقواس يعكس كل الرموز في ثوانٍ. لذلك `ensure_anon_salt()` يولّد
    # ملحاً عشوائياً ويحفظه في `.env` عند أول تشغيل.
    anon_salt: str = Field(default=DEFAULT_ANON_SALT)
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


def is_default_anon_salt(settings: AppSettings | None = None) -> bool:
    """هل ملح التجهيل هو القيمة الافتراضية المنشورة (أو فارغ)؟"""
    s = settings or get_settings()
    return not s.anon_salt.strip() or s.anon_salt == DEFAULT_ANON_SALT


def ensure_anon_salt(settings: AppSettings | None = None) -> str:
    """يضمن ملح تجهيل **خاصاً بهذا التثبيت**، ويحفظه في `.env` عند توليده.

    التجهيل `HMAC(salt, plate)` لا يحمي شيئاً إذا كان الملح معروفاً: أرقام
    اللوحات السعودية فضاء صغير يُعدّ بالكامل في ثوانٍ، فرموز `PLATE-XXXXXXXXXX`
    المُصدَّرة بالملح الافتراضي قابلة للعكس بجدول أقواس. نولّد 128 بت عشوائية
    مرة واحدة ونكتبها في ملف `.env` الخاص بالمستخدم حتى تبقى الرموز ثابتة عبر
    الجلسات (وإلا لتغيّر رمز نفس اللوحة في كل تشغيل وفقدت الدراسة قابلية
    التجميع التي وُجد التجهيل لأجلها).

    يُرجع الملح الفعّال. لا يرفع استثناءً: تعذّر الكتابة يُسجَّل تحذيراً ويُعاد
    الملح المولَّد لهذه الجلسة — تصدير مجهّل بملح جلسة أفضل من تصدير بملح معروف.
    """
    s = settings or get_settings()
    if not is_default_anon_salt(s):
        return s.anon_salt

    generated = secrets.token_hex(16)
    # يُفعَّل في هذه العملية فوراً: متغيّر البيئة له أولوية على ملف `.env` في
    # pydantic-settings، وهو أيضاً ما يقرؤه `exporter.anonymization_salt()`.
    # الاعتماد على إعادة قراءة الملف وحدها كان يترك الجلسة الأولى بالملح القديم.
    os.environ[_ANON_SALT_ENV] = generated

    env_path = _env_file_path()
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        with env_path.open("a", encoding="utf-8") as fp:
            fp.write(
                "\n# ملح تجهيل اللوحات — وُلّد تلقائياً عند أول تشغيل.\n"
                "# لا تشاركه: معرفته تكفي لعكس رموز PLATE-XXXXXXXXXX المُصدَّرة.\n"
                f"BASEER_ANON_SALT={generated}\n"
            )
        # الملف صار يحوي سرّاً: معرفة الملح تكفي لعكس رموز اللوحات المُصدَّرة
        restrict_permissions(env_path)
        logger.info("وُلّد ملح تجهيل خاص بهذا التثبيت وحُفظ في %s", env_path)
    except OSError as exc:
        logger.warning(
            "تعذّر حفظ ملح التجهيل في %s (%s) — يعمل في هذه الجلسة فقط، "
            "وستتغيّر رموز اللوحات في التشغيل القادم",
            env_path,
            exc,
        )

    reset_settings_cache()
    return generated


def restrict_permissions(path: Path) -> None:
    """يضيّق صلاحيات ملف/مجلد يحوي بيانات شخصية إلى المستخدم وحده.

    القاعدة وملفات التصدير تحوي أرقام لوحات وأوقاتاً ومواقع وإطارات إثبات قد
    تحوي وجوهاً. التشفير الكامل مبالغة لأداة محلية أحادية المستخدم (وREADME
    يقول «لا» صريحة)، لكن `0600/0700` شبه مجاني ويحمي من جهاز متعدد المستخدمين
    أو مجلد مُزامَن بالخطأ. على ويندوز لا معنى لبتات POSIX فنتجاهلها بصمت
    (الصلاحيات هناك موروثة من ACL المجلد).
    """
    if sys.platform == "win32" or not path.exists():
        return
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError as exc:
        logger.warning("تعذّر تضييق صلاحيات %s: %s", path, exc)


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
    # البيانات الشخصية: القاعدة والتصديرات وملف الإعدادات (يحوي ملح التجهيل)
    restrict_permissions(s.data_dir / "exports")
    restrict_permissions(s.db_path)
    restrict_permissions(_env_file_path())
