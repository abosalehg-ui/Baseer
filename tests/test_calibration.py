"""اختبارات معايرة الكاميرا وحساب السرعة."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.constants import VideoStatus
from app.core.calibration import (
    CalibrationService,
    compute_meters_per_px,
    estimate_speed_kmh,
    estimate_track_speed_kmh,
)
from app.core.db import Database


# ============================================
# compute_meters_per_px
# ============================================
def test_compute_meters_per_px_simple() -> None:
    # نقطتان بمسافة 100 بكسل = 10 متر → 0.1 m/px
    pts = [(0, 0), (100, 0)]
    distances = [10.0]
    assert compute_meters_per_px(pts, distances) == pytest.approx(0.1)


def test_compute_meters_per_px_multiple_pairs() -> None:
    pts = [(0, 0), (100, 0), (200, 0)]
    distances = [10.0, 10.0]
    assert compute_meters_per_px(pts, distances) == pytest.approx(0.1)


def test_compute_meters_per_px_averages_ratios() -> None:
    # متوسط 0.1 و 0.2 = 0.15
    pts = [(0, 0), (100, 0), (300, 0)]  # 100px=10m, 200px=40m
    distances = [10.0, 40.0]
    assert compute_meters_per_px(pts, distances) == pytest.approx(0.15)


def test_compute_meters_per_px_rejects_single_point() -> None:
    with pytest.raises(ValueError, match="نقطتين"):
        compute_meters_per_px([(0, 0)], [])


def test_compute_meters_per_px_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="المسافات"):
        compute_meters_per_px([(0, 0), (10, 0), (20, 0)], [5.0])


def test_compute_meters_per_px_rejects_zero_distance() -> None:
    with pytest.raises(ValueError):
        compute_meters_per_px([(0, 0), (10, 0)], [0])


# ============================================
# estimate_speed_kmh
# ============================================
def test_estimate_speed_kmh_basic() -> None:
    # 100 بكسل × 0.1 m/px = 10 م في 1 ثانية = 36 كم/س
    assert estimate_speed_kmh(100, 1.0, 0.1) == pytest.approx(36.0)


def test_estimate_speed_kmh_zero_time_returns_zero() -> None:
    assert estimate_speed_kmh(100, 0, 0.1) == 0.0


def test_estimate_track_speed_with_timestamps() -> None:
    # حركة 100 بكسل عبر ثانية واحدة + 100 بكسل عبر ثانية أخرى
    pts = [((0, 0), 0.0), ((100, 0), 1.0), ((200, 0), 2.0)]
    assert estimate_track_speed_kmh(pts, 0.1) == pytest.approx(36.0)


def test_estimate_track_speed_empty_returns_zero() -> None:
    assert estimate_track_speed_kmh([], 0.1) == 0.0


# ============================================
# CalibrationService (DB)
# ============================================
@pytest.fixture()
def video_id(tmp_db: Database, tmp_path: Path) -> int:
    video = tmp_path / "cctv.mp4"
    video.write_bytes(b"x")
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, status) VALUES (?, ?, ?)",
        (str(video), "cctv.mp4", VideoStatus.IMPORTED.value),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(video),))
    assert row is not None
    return int(row[0])


def test_save_and_get_calibration(tmp_db: Database, video_id: int) -> None:
    service = CalibrationService(db=tmp_db)
    cal = service.save_calibration(video_id, [(0, 0), (100, 0)], [10.0])

    assert cal.video_id == video_id
    assert cal.meters_per_px == pytest.approx(0.1)
    assert cal.reference_pts == [(0, 0), (100, 0)]

    loaded = service.get_calibration(video_id)
    assert loaded is not None
    assert loaded.meters_per_px == pytest.approx(0.1)


def test_get_calibration_returns_none_when_missing(tmp_db: Database, video_id: int) -> None:
    service = CalibrationService(db=tmp_db)
    assert service.get_calibration(video_id) is None


def test_save_calibration_overwrites_existing(tmp_db: Database, video_id: int) -> None:
    service = CalibrationService(db=tmp_db)
    service.save_calibration(video_id, [(0, 0), (100, 0)], [10.0])
    service.save_calibration(video_id, [(0, 0), (50, 0)], [10.0])  # 0.2 m/px

    loaded = service.get_calibration(video_id)
    assert loaded is not None
    assert loaded.meters_per_px == pytest.approx(0.2)


def test_delete_calibration(tmp_db: Database, video_id: int) -> None:
    service = CalibrationService(db=tmp_db)
    service.save_calibration(video_id, [(0, 0), (100, 0)], [10.0])
    service.delete_calibration(video_id)
    assert service.get_calibration(video_id) is None
