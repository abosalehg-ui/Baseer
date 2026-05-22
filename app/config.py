"""إعدادات التطبيق — تُقرأ من متغيرات البيئة (.env)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    """إعدادات التطبيق الشاملة."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="BASEER_",
        extra="ignore",
        case_sensitive=False,
    )

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    models_dir: Path = Field(default=PROJECT_ROOT / "models")
    db_path: Path = Field(default=PROJECT_ROOT / "data" / "results.duckdb")

    log_level: str = Field(default="INFO")
    log_file: Path = Field(default=PROJECT_ROOT / "logs" / "baseer.log")

    ui_theme: str = Field(default="dark")
    ui_language: str = Field(default="ar")

    cuda_device: int = Field(default=0)


class CvatSettings(BaseSettings):
    """إعدادات تكامل CVAT (تُقرأ بدون البادئة)."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    cvat_url: str = Field(default="http://localhost:8080")
    cvat_username: str = Field(default="admin")
    cvat_password: str = Field(default="")


def get_settings() -> AppSettings:
    """يعيد إعدادات التطبيق الأساسية."""
    return AppSettings()


def get_cvat_settings() -> CvatSettings:
    """يعيد إعدادات تكامل CVAT."""
    return CvatSettings()


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
