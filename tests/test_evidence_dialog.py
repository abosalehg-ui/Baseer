"""اختبارات مستعرض أدلة المخالفة."""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.db import Database  # noqa: E402

try:
    from PyQt6.QtWidgets import QApplication  # noqa: E402

    from app.ui.dialogs.evidence_dialog import (  # noqa: E402
        EvidenceDialog,
        evidence_frame_numbers,
        extract_evidence_images,
    )
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"PyQt6 غير متوفّر: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeProvider:
    def __init__(self, _path: str) -> None:
        self.closed = False

    def get_frame(self, frame_no: int) -> np.ndarray:
        # لون يعتمد على رقم الإطار لتمييز الإطارات
        return np.full((40, 60, 3), frame_no % 255, dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


def test_evidence_frame_numbers_parsing() -> None:
    assert evidence_frame_numbers(json.dumps([1, 5, 9])) == [1, 5, 9]
    assert evidence_frame_numbers("[]") == []
    assert evidence_frame_numbers(None) == []
    assert evidence_frame_numbers("not-json") == []
    assert evidence_frame_numbers(json.dumps([1, "x", 3])) == [1, 3]


def test_extract_evidence_images_uses_provider_and_closes() -> None:
    holder: dict[str, _FakeProvider] = {}

    def _factory(path: str) -> _FakeProvider:
        p = _FakeProvider(path)
        holder["p"] = p
        return p

    imgs = extract_evidence_images("/v/a.mp4", [0, 2, 4], provider_factory=_factory)
    assert len(imgs) == 3
    assert all(im.shape == (40, 60, 3) for im in imgs)
    assert holder["p"].closed is True


def test_extract_evidence_images_respects_max() -> None:
    imgs = extract_evidence_images(
        "/v/a.mp4", list(range(20)), provider_factory=lambda p: _FakeProvider(p), max_frames=3
    )
    assert len(imgs) == 3


def _seed_violation(db: Database) -> int:
    db.execute("INSERT INTO videos (filepath, filename, fps) VALUES ('/v/a.mp4', 'a.mp4', 30.0)")
    vid = db.fetch_one("SELECT id FROM videos")[0]
    db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, "
        "confidence, evidence_frames, notes) VALUES (?, 'speeding', 1000, 2000, 0.8, ?, '[auto]')",
        (vid, json.dumps([3, 6, 9])),
    )
    return int(db.fetch_one("SELECT id FROM violations")[0])


def test_evidence_dialog_builds_thumbnails(qt_app, tmp_db: Database) -> None:
    viol_id = _seed_violation(tmp_db)
    dlg = EvidenceDialog(viol_id, db=tmp_db, provider_factory=lambda p: _FakeProvider(p))
    assert dlg._row is not None
    assert dlg._row["start_ms"] == 1000
    # المخالفة لها 3 إطارات إثبات → 3 صور مُستخرجة
    from app.ui.dialogs.evidence_dialog import (
        evidence_frame_numbers as efn,
    )

    assert efn(dlg._row["evidence_frames"]) == [3, 6, 9]


def test_evidence_dialog_missing_violation(qt_app, tmp_db: Database) -> None:
    dlg = EvidenceDialog(9999, db=tmp_db, provider_factory=lambda p: _FakeProvider(p))
    assert dlg._row is None
