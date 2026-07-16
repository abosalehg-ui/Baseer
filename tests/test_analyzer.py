"""اختبارات خدمة التحليل (مع inference mock)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from app.constants import VideoStatus
from app.core.analyzer import (
    AnalysisConfig,
    AnalyzerService,
    Detection,
    detections_grouped_by_frame,
    detections_to_json,
)
from app.core.db import Database


@pytest.fixture()
def fake_video(tmp_path: Path) -> Path:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"placeholder" * 100)
    return video


@pytest.fixture()
def seeded_video(tmp_db: Database, fake_video: Path) -> int:
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, width, height, status, fps) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(fake_video), fake_video.name, 1920, 1080, VideoStatus.IMPORTED.value, 30.0),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(fake_video),))
    assert row is not None
    return int(row[0])


def _fake_inference_factory(detections: list[Detection]):
    def _fn(_path: Path, _config: AnalysisConfig) -> Iterable[Detection]:
        yield from detections

    return _fn


def test_analyze_video_stores_detections(
    tmp_db: Database, seeded_video: int, tmp_path: Path
) -> None:
    dets = [
        Detection(
            frame_no=0, timestamp_ms=0, class_name="vehicle", confidence=0.9, bbox=(10, 10, 50, 50)
        ),
        Detection(
            frame_no=0, timestamp_ms=0, class_name="person", confidence=0.7, bbox=(60, 60, 80, 100)
        ),
        Detection(
            frame_no=10,
            timestamp_ms=333,
            class_name="vehicle",
            confidence=0.85,
            bbox=(20, 30, 90, 80),
        ),
    ]
    service = AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory(dets))
    config = AnalysisConfig(model_path=tmp_path / "fake.pt")

    result = service.analyze_video(seeded_video, config)

    assert result.detections_count == 3
    assert result.total_frames == 2

    stored = service.detections_for_video(seeded_video)
    assert len(stored) == 3
    assert {d.class_name for d in stored} == {"vehicle", "person"}


def test_analyze_video_updates_status_to_prelabeled(
    tmp_db: Database, seeded_video: int, tmp_path: Path
) -> None:
    service = AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory([]))
    service.analyze_video(seeded_video, AnalysisConfig(model_path=tmp_path / "x.pt"))

    row = tmp_db.fetch_one("SELECT status FROM videos WHERE id = ?", (seeded_video,))
    assert row is not None
    assert row[0] == VideoStatus.PRELABELED.value


def test_reanalyze_replaces_old_detections(
    tmp_db: Database, seeded_video: int, tmp_path: Path
) -> None:
    first = [
        Detection(
            frame_no=0, timestamp_ms=0, class_name="vehicle", confidence=0.5, bbox=(0, 0, 1, 1)
        )
    ]
    second = [
        Detection(
            frame_no=5, timestamp_ms=166, class_name="person", confidence=0.9, bbox=(10, 10, 20, 20)
        ),
        Detection(
            frame_no=5, timestamp_ms=166, class_name="helmet", confidence=0.7, bbox=(15, 10, 18, 12)
        ),
    ]
    cfg = AnalysisConfig(model_path=tmp_path / "x.pt")

    AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory(first)).analyze_video(
        seeded_video, cfg
    )
    AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory(second)).analyze_video(
        seeded_video, cfg
    )

    final = AnalyzerService(db=tmp_db).detections_for_video(seeded_video)
    assert len(final) == 2
    assert {d.class_name for d in final} == {"person", "helmet"}


def test_analyze_video_raises_for_missing_video(tmp_db: Database, tmp_path: Path) -> None:
    service = AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory([]))
    with pytest.raises(ValueError, match="لا يوجد مقطع"):
        service.analyze_video(999, AnalysisConfig(model_path=tmp_path / "x.pt"))


def test_list_unanalyzed_returns_only_imported(tmp_db: Database, tmp_path: Path) -> None:
    files = []
    for i in range(3):
        f = tmp_path / f"v{i}.mp4"
        f.write_bytes(b"x")
        files.append(f)
        tmp_db.execute(
            "INSERT INTO videos (filepath, filename, status) VALUES (?, ?, ?)",
            (str(f), f.name, VideoStatus.IMPORTED.value),
        )
    tmp_db.execute(
        "UPDATE videos SET status = ? WHERE filename = ?",
        (VideoStatus.ANALYZED.value, "v1.mp4"),
    )
    ids = AnalyzerService(db=tmp_db).list_unanalyzed_video_ids()
    rows = tmp_db.fetch_all("SELECT id, filename FROM videos WHERE id IN (?, ?)", (ids[0], ids[1]))
    names = {r[1] for r in rows}
    assert names == {"v0.mp4", "v2.mp4"}


def test_detections_grouped_by_frame() -> None:
    dets = [
        Detection(0, 0, "vehicle", 0.9, (0, 0, 1, 1)),
        Detection(0, 0, "person", 0.8, (1, 1, 2, 2)),
        Detection(5, 166, "vehicle", 0.95, (2, 2, 3, 3)),
    ]
    groups = detections_grouped_by_frame(dets)
    assert set(groups.keys()) == {0, 5}
    assert len(groups[0]) == 2
    assert len(groups[5]) == 1


def test_extract_violations_runs_rules_and_stores_to_db(
    tmp_db: Database, seeded_video: int, tmp_path: Path
) -> None:
    """يتأكد أن extract_violations يستخرج المخالفات ويخزّنها."""
    from app.core.rules import Zone

    # نزرع كشوفات + zone stop_line + إشارة حمراء
    detections = [
        Detection(0, 0, "vehicle", 0.9, (40, 0, 60, 10), track_id=1),
        Detection(1, 33, "vehicle", 0.9, (40, 40, 60, 50), track_id=1),
        Detection(2, 66, "vehicle", 0.9, (40, 60, 60, 70), track_id=1),
        Detection(2, 66, "traffic_light_red", 0.95, (200, 0, 220, 20), track_id=99),
    ]
    service = AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory(detections))
    service.analyze_video(seeded_video, AnalysisConfig(model_path=tmp_path / "x.pt"))

    # أضف zone للـ stop_line
    import json as _json

    tmp_db.execute(
        "INSERT INTO zones (video_id, zone_type, polygon) VALUES (?, ?, ?)",
        (seeded_video, "stop_line", _json.dumps([[0, 50], [200, 50]])),
    )

    count = service.extract_violations(seeded_video, fps=30.0)
    assert count == 1

    rows = tmp_db.fetch_all(
        "SELECT violation_type FROM violations WHERE video_id = ?", (seeded_video,)
    )
    assert rows[0][0] == "red_light_running"

    # حالة المقطع تحدّثت
    status = tmp_db.fetch_one("SELECT status FROM videos WHERE id = ?", (seeded_video,))
    assert status[0] == "analyzed"


def test_extract_violations_registers_speeding_when_calibrated(
    tmp_db: Database, seeded_video: int, tmp_path: Path
) -> None:
    """عند وجود معايرة، يُسجَّل SpeedingDetector ويكشف السرعة الزائدة (منع نكوص C1-ج)."""
    import json as _json

    # مركبة تتحرك بسرعة كبيرة عبر الفريمات
    detections = [
        Detection(
            i,
            int(i * 1000 / 30),
            "vehicle",
            0.9,
            (i * 60.0, 100.0, i * 60.0 + 40, 150.0),
            track_id=1,
        )
        for i in range(6)
    ]
    service = AnalyzerService(db=tmp_db, inference_fn=_fake_inference_factory(detections))
    service.analyze_video(seeded_video, AnalysisConfig(model_path=tmp_path / "x.pt"))

    # معايرة: 0.05 م/بكسل → ~60px/فريم × 30fps × 0.05 ≈ 90 م/س ⇒ سرعة عالية جداً
    tmp_db.execute(
        "INSERT INTO calibrations (video_id, reference_pts, meters_per_px) VALUES (?, ?, ?)",
        (seeded_video, _json.dumps([[0, 0], [100, 0]]), 0.05),
    )

    count = service.extract_violations(seeded_video, fps=30.0)
    assert count >= 1
    types = {
        r[0]
        for r in tmp_db.fetch_all(
            "SELECT violation_type FROM violations WHERE video_id = ?", (seeded_video,)
        )
    }
    assert "speeding" in types


def test_extract_violations_returns_zero_for_video_without_detections(
    tmp_db: Database, tmp_path: Path
) -> None:
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"x")
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, status) VALUES (?, ?, ?)",
        (str(video), "empty.mp4", "imported"),
    )
    row = tmp_db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(video),))
    assert row is not None
    service = AnalyzerService(db=tmp_db)
    assert service.extract_violations(int(row[0])) == 0


def test_detections_to_json_is_valid_json() -> None:
    import json

    dets = [Detection(1, 33, "helmet", 0.6, (10.5, 20.5, 30.5, 40.5), track_id=42)]
    parsed = json.loads(detections_to_json(dets))
    assert parsed[0]["class_name"] == "helmet"
    assert parsed[0]["track_id"] == 42
    assert parsed[0]["bbox"] == [10.5, 20.5, 30.5, 40.5]
