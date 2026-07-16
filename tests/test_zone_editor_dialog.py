"""اختبارات محرر المناطق وحوار المعايرة (ودجات حقيقية headless)."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.db import Database  # noqa: E402

try:
    from PyQt6.QtGui import QImage  # noqa: E402
    from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

    from app.ui.dialogs.zone_editor_dialog import (  # noqa: E402
        CalibrationDialog,
        ZoneEditorDialog,
        numpy_bgr_to_qimage,
    )
    from app.ui.widgets.frame_canvas import FrameCanvas  # noqa: E402
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PyQt6 غير متوفّر: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def silence_message_boxes(monkeypatch):
    for name in ("warning", "critical", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.StandardButton.Ok)


def _seed_video(db: Database) -> int:
    db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/a.mp4', 'a.mp4')")
    row = db.fetch_one("SELECT id FROM videos WHERE filepath = '/v/a.mp4'")
    assert row is not None
    return int(row[0])


def _fake_image(w: int = 200, h: int = 120) -> QImage:
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    return numpy_bgr_to_qimage(frame)


def test_numpy_bgr_to_qimage_dimensions() -> None:
    frame = np.zeros((80, 160, 3), dtype=np.uint8)
    frame[:, :, 2] = 255  # أحمر في BGR→ يجب أن يصبح R في RGB
    img = numpy_bgr_to_qimage(frame)
    assert img.width() == 160
    assert img.height() == 80
    # البكسل أحمر (R=255)
    px = img.pixel(0, 0)
    assert (px >> 16) & 0xFF == 255


def test_frame_canvas_collects_points(qt_app) -> None:
    canvas = FrameCanvas(_fake_image())
    canvas.add_point_image_coords(10, 20)
    canvas.add_point_image_coords(30, 40)
    assert canvas.points() == [(10.0, 20.0), (30.0, 40.0)]
    canvas.undo_point()
    assert canvas.points() == [(10.0, 20.0)]
    canvas.clear_points()
    assert canvas.points() == []


def test_zone_editor_saves_zone(qt_app, tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    dlg = ZoneEditorDialog(video_id=vid, image=_fake_image(), db=tmp_db)
    dlg._canvas.add_point_image_coords(0, 50)
    dlg._canvas.add_point_image_coords(200, 50)
    # النوع الافتراضي stop_line (أول عنصر)
    dlg._on_save_zone()

    from app.core.zones import ZoneService

    zones = ZoneService(db=tmp_db).list_zones(vid)
    assert len(zones) == 1
    assert zones[0].zone_type == "stop_line"
    assert zones[0].polygon == [(0.0, 50.0), (200.0, 50.0)]
    # بعد الحفظ تُمسح النقاط
    assert dlg._canvas.points() == []


def test_zone_editor_rejects_insufficient_points(qt_app, tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    dlg = ZoneEditorDialog(video_id=vid, image=_fake_image(), db=tmp_db)
    dlg._canvas.add_point_image_coords(10, 10)  # نقطة واحدة فقط
    dlg._on_save_zone()

    from app.core.zones import ZoneService

    assert ZoneService(db=tmp_db).list_zones(vid) == []


def test_calibration_dialog_saves(qt_app, tmp_db: Database) -> None:
    vid = _seed_video(tmp_db)
    dlg = CalibrationDialog(video_id=vid, image=_fake_image(), db=tmp_db)
    dlg._canvas.add_point_image_coords(100, 500)
    dlg._canvas.add_point_image_coords(400, 500)  # 300px
    dlg._distance.setValue(30.0)  # 30م → 0.1 م/بكسل
    dlg._on_save()

    from app.core.calibration import CalibrationService

    cal = CalibrationService(db=tmp_db).get_calibration(vid)
    assert cal is not None
    assert cal.meters_per_px == pytest.approx(0.1, rel=1e-3)
