"""اختبارات خدمة الداشبورد."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.constants import ReviewStatus
from app.core.dashboard import DashboardService
from app.core.db import Database


# ============================================
# Helpers
# ============================================
def _insert_video(
    db: Database,
    *,
    video_id: int,
    filename: str = "v.mp4",
    source_type: str = "dashcam",
    recorded_at: datetime | None = None,
) -> None:
    db.execute(
        "INSERT INTO videos (id, filepath, filename, source_type, recorded_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            video_id,
            f"/tmp/{video_id}_{filename}",
            filename,
            source_type,
            recorded_at,
            "analyzed",
        ),
    )


def _insert_violation(
    db: Database,
    *,
    video_id: int,
    violation_type: str,
    confidence: float = 0.9,
    review_status: str = "pending",
) -> None:
    db.execute(
        "INSERT INTO violations "
        "(video_id, violation_type, start_ms, end_ms, confidence, review_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (video_id, violation_type, 0, 1000, confidence, review_status),
    )


# ============================================
# KPIs
# ============================================
def test_get_kpis_empty_db(tmp_db: Database) -> None:
    kpis = DashboardService(db=tmp_db).get_kpis()
    assert kpis.total_videos == 0
    assert kpis.total_violations == 0
    assert kpis.avg_violations_per_video == 0


def test_get_kpis_with_data(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1, source_type="dashcam")
    _insert_video(tmp_db, video_id=2, source_type="cctv")
    _insert_violation(tmp_db, video_id=1, violation_type="red_light_running")
    _insert_violation(tmp_db, video_id=1, violation_type="no_helmet")
    _insert_violation(tmp_db, video_id=2, violation_type="red_light_running")

    kpis = DashboardService(db=tmp_db).get_kpis()
    assert kpis.total_videos == 2
    assert kpis.total_violations == 3
    assert kpis.avg_violations_per_video == 1.5
    assert kpis.sources_breakdown == {"dashcam": 1, "cctv": 1}


# ============================================
# Aggregations
# ============================================
def test_violations_by_type_sorted_desc(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    for _ in range(3):
        _insert_violation(tmp_db, video_id=1, violation_type="red_light_running")
    _insert_violation(tmp_db, video_id=1, violation_type="no_helmet")

    rows = DashboardService(db=tmp_db).violations_by_type()
    assert rows[0] == ("red_light_running", 3)
    assert rows[1] == ("no_helmet", 1)


def test_violations_by_review_status(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="confirmed")
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="confirmed")
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="false_positive")

    by_status = DashboardService(db=tmp_db).violations_by_review_status()
    assert by_status["confirmed"] == 2
    assert by_status["false_positive"] == 1


def test_violations_by_hour(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1, recorded_at=datetime(2025, 6, 1, 14, 30))
    _insert_video(tmp_db, video_id=2, recorded_at=datetime(2025, 6, 1, 9, 0))
    _insert_violation(tmp_db, video_id=1, violation_type="x")
    _insert_violation(tmp_db, video_id=2, violation_type="x")

    rows = DashboardService(db=tmp_db).violations_by_hour()
    by_hour = dict(rows)
    assert by_hour[14] == 1
    assert by_hour[9] == 1


def test_violations_heatmap(tmp_db: Database) -> None:
    # الأحد 2025-06-01 الساعة 14:30
    _insert_video(tmp_db, video_id=1, recorded_at=datetime(2025, 6, 1, 14, 30))
    _insert_violation(tmp_db, video_id=1, violation_type="x")

    heatmap = DashboardService(db=tmp_db).violations_heatmap()
    assert sum(heatmap.values()) == 1


def test_violations_skips_records_without_recorded_at(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1, recorded_at=None)
    _insert_violation(tmp_db, video_id=1, violation_type="x")
    assert DashboardService(db=tmp_db).violations_by_hour() == []


# ============================================
# list_violations + filters
# ============================================
def test_list_violations_returns_arabic_names(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1, filename="cam.mp4")
    _insert_violation(tmp_db, video_id=1, violation_type="red_light_running")

    rows = DashboardService(db=tmp_db).list_violations()
    assert len(rows) == 1
    assert rows[0].violation_type_ar == "قطع الإشارة الحمراء"
    assert rows[0].video_filename == "cam.mp4"


def test_list_violations_filters_by_type(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    _insert_violation(tmp_db, video_id=1, violation_type="red_light_running")
    _insert_violation(tmp_db, video_id=1, violation_type="no_helmet")

    rows = DashboardService(db=tmp_db).list_violations(violation_type="red_light_running")
    assert len(rows) == 1
    assert rows[0].violation_type == "red_light_running"


def test_list_violations_filters_by_review_status(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="confirmed")
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="pending")

    rows = DashboardService(db=tmp_db).list_violations(review_status="confirmed")
    assert len(rows) == 1
    assert rows[0].review_status == "confirmed"


def test_list_violations_respects_limit(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    for _ in range(10):
        _insert_violation(tmp_db, video_id=1, violation_type="x")

    rows = DashboardService(db=tmp_db).list_violations(limit=3)
    assert len(rows) == 3


# ============================================
# update_review_status
# ============================================
def test_update_review_status_changes_value(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    _insert_violation(tmp_db, video_id=1, violation_type="x", review_status="pending")
    row_before = tmp_db.fetch_one("SELECT id FROM violations LIMIT 1")
    assert row_before is not None
    vid = int(row_before[0])

    service = DashboardService(db=tmp_db)
    service.update_review_status(vid, ReviewStatus.CONFIRMED)

    after = tmp_db.fetch_one("SELECT review_status FROM violations WHERE id = ?", (vid,))
    assert after is not None
    assert after[0] == "confirmed"


def test_update_review_status_accepts_string(tmp_db: Database) -> None:
    _insert_video(tmp_db, video_id=1)
    _insert_violation(tmp_db, video_id=1, violation_type="x")
    vid = int(tmp_db.fetch_one("SELECT id FROM violations LIMIT 1")[0])

    DashboardService(db=tmp_db).update_review_status(vid, "false_positive")
    after = tmp_db.fetch_one("SELECT review_status FROM violations WHERE id = ?", (vid,))
    assert after[0] == "false_positive"
