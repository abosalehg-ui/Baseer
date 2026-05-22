"""اختبارات وحدة الإعدادات."""

from __future__ import annotations

from pathlib import Path

from app.config import AppSettings, ensure_directories


def test_default_settings_have_paths() -> None:
    s = AppSettings()
    assert isinstance(s.data_dir, Path)
    assert isinstance(s.db_path, Path)
    assert s.ui_language in {"ar", "en"}


def test_ensure_directories_creates_data_subfolders(tmp_path: Path) -> None:
    s = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    ensure_directories(s)
    for sub in ("videos", "thumbnails", "frames", "exports"):
        assert (s.data_dir / sub).is_dir()
    assert (s.data_dir / "annotations" / "raw").is_dir()
    assert (s.data_dir / "annotations" / "reviewed").is_dir()
    assert s.log_file.parent.is_dir()
