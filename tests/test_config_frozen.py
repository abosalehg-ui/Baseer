"""اختبارات سلوك config عند تشغيل PyInstaller bundle (frozen)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import config


def test_default_root_uses_project_when_not_frozen(monkeypatch) -> None:
    """في التطوير المحلي (غير frozen) → الجذر هو جذر المستودع."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert not config._is_frozen()
    root = config._default_root()
    assert root == config.PROJECT_ROOT


def test_default_root_uses_user_dir_when_frozen(monkeypatch, tmp_path: Path) -> None:
    """في PyInstaller bundle → الجذر هو user data dir."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    assert config._is_frozen()
    # نعيد حساب الجذر يدوياً (موديول cached)
    root = config._user_data_dir()
    assert "Baseer" in str(root)
    if sys.platform == "win32":
        assert str(tmp_path / "LocalAppData") in str(root)


def test_user_data_dir_falls_back_to_home_when_no_env(monkeypatch) -> None:
    """على لينكس بدون XDG_DATA_HOME → يقع على ~/.local/share/Baseer."""
    if sys.platform != "linux":
        pytest.skip("اختبار لينكس فقط")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    root = config._user_data_dir()
    assert root == Path.home() / ".local" / "share" / "Baseer"
