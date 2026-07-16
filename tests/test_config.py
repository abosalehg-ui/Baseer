"""اختبارات وحدة الإعدادات."""

from __future__ import annotations

from pathlib import Path

from app.config import PROJECT_ROOT, AppSettings, CvatSettings, ensure_directories


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


def test_env_example_keys_are_all_recognized() -> None:
    """كل مفتاح في .env.example يجب أن يطابق حقلاً معروفاً في الإعدادات.

    يمنع نكوص H3: مفاتيح بلا بادئة BASEER_ (مثل LOG_LEVEL) كانت تُتجاهل بصمت.
    """
    env_example = PROJECT_ROOT / ".env.example"
    assert env_example.exists(), ".env.example مفقود"

    app_fields = {f"BASEER_{name.upper()}" for name in AppSettings.model_fields}
    cvat_fields = {name.upper() for name in CvatSettings.model_fields}
    recognized = app_fields | cvat_fields

    unknown: list[str] = []
    for raw_line in env_example.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().upper()
        if key not in recognized:
            unknown.append(key)

    assert not unknown, f"مفاتيح غير معروفة في .env.example (ستُتجاهل بصمت): {unknown}"
