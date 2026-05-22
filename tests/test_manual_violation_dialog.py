"""اختبارات حوار المخالفة اليدوية — منطق الإدراج/التعديل/الحذف.

الاختبارات تستخدم منصة Qt minimal وتُعطّل QMessageBox لتجنّب modal dialogs.
"""

from __future__ import annotations

import os

import pytest

# يجب تعيين المنصة قبل استيراد PyQt6
os.environ.setdefault("QT_QPA_PLATFORM", "minimal")

from app.core.db import Database  # noqa: E402

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

    from app.ui.dialogs.manual_violation_dialog import ManualViolationDialog  # noqa: E402
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PyQt6 غير متوفّر: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def silence_message_boxes(monkeypatch):
    """يستبدل QMessageBox.warning/critical/information/question بـ no-op لمنع modals."""
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def _seed_video(db: Database, filename: str = "x.mp4") -> int:
    db.execute(
        "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
        (f"/tmp/{filename}", filename),
    )
    row = db.fetch_one("SELECT id FROM videos WHERE filename = ?", (filename,))
    assert row is not None
    return int(row[0])


def test_dialog_inserts_manual_violation(qt_app, tmp_db: Database) -> None:
    """الحوار يحفظ مخالفة بـ source='manual' و notes تبدأ بـ [manual]."""
    video_id = _seed_video(tmp_db)
    dlg = ManualViolationDialog(videos=[(video_id, "x.mp4")], db=tmp_db, current_time_ms=5000)
    dlg._notes.setPlainText("شوهد يقطع المسار")
    dlg._start_ms.setValue(5000)
    dlg._end_ms.setValue(8000)
    dlg._plate.setText("أ ب ج 1234")
    dlg._insert_violation()

    row = tmp_db.fetch_one(
        "SELECT violation_type, start_ms, end_ms, license_plate, notes, source, manual_user "
        "FROM violations WHERE video_id = ?",
        (video_id,),
    )
    assert row is not None
    assert row[1] == 5000
    assert row[2] == 8000
    assert row[3] == "أ ب ج 1234"
    assert row[4].startswith("[manual]")
    assert "شوهد يقطع المسار" in row[4]
    assert row[5] == "manual"
    assert row[6]  # اسم المستخدم غير فارغ


def test_dialog_validation_rejects_invalid_time_range(qt_app, tmp_db: Database) -> None:
    """نهاية الوقت ≤ البداية → الـ validate يفشل."""
    video_id = _seed_video(tmp_db)
    dlg = ManualViolationDialog(videos=[(video_id, "x.mp4")], db=tmp_db)
    dlg._start_ms.setValue(5000)
    dlg._end_ms.setValue(5000)  # غير صحيح
    assert dlg._validate() is False


def test_dialog_update_modifies_existing(qt_app, tmp_db: Database) -> None:
    """الحوار في وضع التعديل يُعدّل صف موجود."""
    video_id = _seed_video(tmp_db)
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, "
        "confidence, notes, source, manual_user) "
        "VALUES (?, 'manual_other', 1000, 2000, 1.0, '[manual] original', 'manual', 'tester')",
        (video_id,),
    )
    row = tmp_db.fetch_one("SELECT id FROM violations LIMIT 1")
    assert row is not None
    viol_id = int(row[0])

    existing = {
        "id": viol_id,
        "video_id": video_id,
        "violation_type": "manual_other",
        "start_ms": 1000,
        "end_ms": 2000,
        "license_plate": None,
        "notes": "[manual] original",
    }
    dlg = ManualViolationDialog(videos=[(video_id, "x.mp4")], db=tmp_db, existing=existing)
    assert dlg._start_ms.value() == 1000
    assert dlg._end_ms.value() == 2000

    dlg._end_ms.setValue(3500)
    dlg._notes.setPlainText("updated notes")
    dlg._update_violation()

    updated = tmp_db.fetch_one("SELECT end_ms, notes FROM violations WHERE id = ?", (viol_id,))
    assert updated is not None
    assert updated[0] == 3500
    assert updated[1] == "[manual] updated notes"
