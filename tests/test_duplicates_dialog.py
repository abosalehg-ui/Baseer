"""اختبارات حوار مراجعة التكرارات."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.db import Database  # noqa: E402

try:
    from PyQt6.QtCore import Qt  # noqa: E402
    from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

    from app.ui.dialogs.duplicates_dialog import DuplicatesDialog  # noqa: E402
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PyQt6 غير متوفّر: {exc}", allow_module_level=True)

from app.core.library import LibraryService  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def silence_message_boxes(monkeypatch):
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def _insert_video(db: Database, name: str, file_hash: str) -> int:
    db.execute(
        "INSERT INTO videos (filepath, filename, file_hash) VALUES (?, ?, ?)",
        (f"/v/{name}", name, file_hash),
    )
    return int(db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (f"/v/{name}",))[0])


def test_duplicates_dialog_lists_exact_group(qt_app, tmp_db: Database) -> None:
    rep = _insert_video(tmp_db, "a.mp4", "HASH1")
    dup = _insert_video(tmp_db, "b.mp4", "HASH1")  # نفس الـ hash → مكرر
    _insert_video(tmp_db, "c.mp4", "OTHER")

    service = LibraryService(db=tmp_db)
    dlg = DuplicatesDialog(service=service)
    assert dlg._tree.topLevelItemCount() == 1
    parent = dlg._tree.topLevelItem(0)
    assert parent.childCount() == 1
    child = parent.child(0)
    assert int(child.data(0, Qt.ItemDataRole.UserRole)) == dup
    # الممثِّل غير قابل للحذف
    assert parent.data(0, Qt.ItemDataRole.UserRole) is None
    assert rep != dup


def test_duplicates_dialog_deletes_selected(qt_app, tmp_db: Database) -> None:
    _insert_video(tmp_db, "a.mp4", "H")
    dup = _insert_video(tmp_db, "b.mp4", "H")

    service = LibraryService(db=tmp_db)
    dlg = DuplicatesDialog(service=service)
    child = dlg._tree.topLevelItem(0).child(0)
    child.setSelected(True)
    dlg._on_delete_selected()

    # المكرر حُذف، لم يعد هناك تكرار
    assert tmp_db.fetch_one("SELECT COUNT(*) FROM videos WHERE id = ?", (dup,))[0] == 0
    assert dlg._tree.topLevelItemCount() == 0


def test_duplicates_dialog_empty(qt_app, tmp_db: Database) -> None:
    _insert_video(tmp_db, "solo.mp4", "UNIQUE")
    dlg = DuplicatesDialog(service=LibraryService(db=tmp_db))
    assert dlg._tree.topLevelItemCount() == 0
