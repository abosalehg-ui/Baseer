"""اختبارات محرك المخالفات."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.rules import (
    IllegalOvertakingDetector,
    IllegalParkingDetector,
    NoHelmetDetector,
    RedLightDetector,
    SpeedingDetector,
    Track,
    WrongDirectionDetector,
    Zone,
    build_tracks,
    detections_by_frame,
    run_detectors,
)


# ============================================
# Helpers
# ============================================
def _det(
    frame: int,
    track_id: int,
    class_name: str,
    bbox: tuple[float, float, float, float],
    conf: float = 0.9,
    ms: int | None = None,
    fps: float = 30.0,
) -> Detection:
    return Detection(
        frame_no=frame,
        timestamp_ms=ms if ms is not None else int(1000 * frame / fps),
        class_name=class_name,
        confidence=conf,
        bbox=bbox,
        track_id=track_id,
    )


# ============================================
# build_tracks / detections_by_frame
# ============================================
def test_build_tracks_groups_by_track_id() -> None:
    dets = [
        _det(0, 1, "vehicle", (0, 0, 10, 10)),
        _det(1, 1, "vehicle", (5, 0, 15, 10)),
        _det(0, 2, "person", (50, 50, 60, 70)),
    ]
    tracks = build_tracks(dets)
    assert len(tracks) == 2
    by_id = {t.track_id: t for t in tracks}
    assert len(by_id[1].detections) == 2
    assert by_id[1].class_name == "vehicle"


def test_build_tracks_ignores_detections_without_track_id() -> None:
    dets = [
        Detection(0, 0, "vehicle", 0.9, (0, 0, 10, 10), track_id=None),
    ]
    assert build_tracks(dets) == []


def test_detections_by_frame() -> None:
    dets = [
        _det(0, 1, "vehicle", (0, 0, 10, 10)),
        _det(0, 2, "person", (50, 50, 60, 70)),
        _det(5, 1, "vehicle", (20, 0, 30, 10)),
    ]
    by_frame = detections_by_frame(dets)
    assert len(by_frame[0]) == 2
    assert len(by_frame[5]) == 1


# ============================================
# Red light running
# ============================================
def test_red_light_detector_fires_when_vehicle_crosses_with_red() -> None:
    # سيارة تتحرك من y=0 إلى y=100، تعبر stop_line عند y=50
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(1, 1, "vehicle", (40, 40, 60, 50)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),  # عبرت الخط
        _det(2, 99, "traffic_light_red", (200, 0, 220, 20)),
    ]
    zones = [Zone(zone_type="stop_line", polygon=[(0, 50), (200, 50)])]
    violations = RedLightDetector().detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=30.0
    )
    assert len(violations) == 1
    assert violations[0].violation_type == ViolationType.RED_LIGHT_RUNNING


def test_red_light_detector_no_fire_without_red_signal() -> None:
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),
    ]
    zones = [Zone(zone_type="stop_line", polygon=[(0, 50), (200, 50)])]
    violations = RedLightDetector().detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=30.0
    )
    assert violations == []


def test_red_light_detector_no_fire_without_stop_line() -> None:
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),
        _det(2, 99, "traffic_light_red", (200, 0, 220, 20)),
    ]
    violations = RedLightDetector().detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=30.0
    )
    assert violations == []


# ============================================
# Wrong direction
# ============================================
def test_wrong_direction_detector_fires() -> None:
    # 4 tracks تتجه شرقاً، 1 track يتجه غرباً (عكس الاتجاه)
    dets: list[Detection] = []
    for tid in (1, 2, 3, 4):
        # شرقاً
        for f in range(60):
            dets.append(_det(f, tid, "vehicle", (f * 5 + tid, 0, f * 5 + 10 + tid, 10), ms=f * 100))

    # tid=5 يتجه غرباً
    for f in range(60):
        x = 300 - f * 5
        dets.append(_det(f, 5, "vehicle", (x, 100, x + 10, 110), ms=f * 100))

    violations = WrongDirectionDetector(min_duration_sec=1.0).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=10.0
    )
    assert any(v.track_id == 5 for v in violations)
    assert all(v.violation_type == ViolationType.WRONG_DIRECTION for v in violations)


def test_wrong_direction_no_fire_with_too_few_samples() -> None:
    dets = [_det(0, 1, "vehicle", (0, 0, 10, 10)), _det(5, 1, "vehicle", (50, 0, 60, 10))]
    violations = WrongDirectionDetector().detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=30.0
    )
    assert violations == []


# ============================================
# No helmet
# ============================================
def test_no_helmet_detector_fires_when_motorcycle_has_no_helmet() -> None:
    # motorcycle مع person فوقها بدون helmet
    dets = []
    for f in range(60):
        dets.append(_det(f, 1, "motorcycle", (100, 200, 150, 280), ms=f * 100))
        # person فوق motorcycle (y أصغر)
        dets.append(_det(f, 2, "person", (110, 150, 140, 220), ms=f * 100))

    violations = NoHelmetDetector(min_duration_sec=1.0).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=10.0
    )
    assert len(violations) == 1
    assert violations[0].violation_type == ViolationType.NO_HELMET


def test_no_helmet_no_fire_when_helmet_present() -> None:
    dets = []
    for f in range(60):
        dets.append(_det(f, 1, "motorcycle", (100, 200, 150, 280), ms=f * 100))
        dets.append(_det(f, 2, "person", (110, 150, 140, 220), ms=f * 100))
        # helmet متداخل مع motorcycle
        dets.append(_det(f, 3, "helmet", (110, 195, 140, 230), ms=f * 100))

    violations = NoHelmetDetector(min_duration_sec=1.0).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=10.0
    )
    assert violations == []


# ============================================
# Illegal parking
# ============================================
def test_illegal_parking_fires_when_stationary_in_zone() -> None:
    # سيارة ثابتة لـ 90 ثانية داخل zone
    dets = []
    fps = 1.0
    for f in range(90):
        # نفس الموقع تقريباً
        dets.append(_det(f, 1, "vehicle", (100, 100, 150, 130), ms=f * 1000))

    zones = [Zone(zone_type="no_parking", polygon=[(0, 0), (200, 0), (200, 200), (0, 200)])]
    violations = IllegalParkingDetector(min_duration_sec=60.0).detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=fps
    )
    assert len(violations) == 1
    assert violations[0].violation_type == ViolationType.ILLEGAL_PARKING


def test_illegal_parking_no_fire_when_moving() -> None:
    dets = []
    for f in range(90):
        dets.append(_det(f, 1, "vehicle", (f * 5, 100, f * 5 + 50, 130), ms=f * 1000))

    zones = [Zone(zone_type="no_parking", polygon=[(0, 0), (500, 0), (500, 200), (0, 200)])]
    violations = IllegalParkingDetector(min_duration_sec=60.0).detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=1.0
    )
    assert violations == []


def test_illegal_parking_no_fire_outside_zone() -> None:
    dets = []
    for f in range(90):
        dets.append(_det(f, 1, "vehicle", (500, 500, 550, 530), ms=f * 1000))

    zones = [Zone(zone_type="no_parking", polygon=[(0, 0), (100, 0), (100, 100), (0, 100)])]
    violations = IllegalParkingDetector(min_duration_sec=60.0).detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=1.0
    )
    assert violations == []


# ============================================
# Illegal overtaking
# ============================================
def test_illegal_overtaking_fires_when_crosses_solid_line() -> None:
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(1, 1, "vehicle", (40, 40, 60, 50)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),
    ]
    zones = [Zone(zone_type="lane_line_solid", polygon=[(0, 50), (200, 50)])]
    violations = IllegalOvertakingDetector().detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=30.0
    )
    assert len(violations) == 1


def test_illegal_overtaking_no_fire_without_solid_line() -> None:
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),
    ]
    zones = [Zone(zone_type="lane_line_dashed", polygon=[(0, 50), (200, 50)])]
    violations = IllegalOvertakingDetector().detect(
        build_tracks(dets), detections_by_frame(dets), zones, fps=30.0
    )
    assert violations == []


# ============================================
# Speeding
# ============================================
def test_speeding_fires_when_above_limit() -> None:
    # 30 بكسل × 0.5 m/px = 15م في 1 ثانية = 54 كم/س > 50
    dets = []
    fps = 30.0
    for f in range(31):
        dets.append(_det(f, 1, "vehicle", (f, 0, f + 10, 10)))

    violations = SpeedingDetector(speed_limit_kmh=50, meters_per_px=0.5).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=fps
    )
    assert len(violations) == 1


def test_speeding_no_fire_below_limit() -> None:
    dets = []
    for f in range(31):
        dets.append(_det(f, 1, "vehicle", (f, 0, f + 10, 10)))

    violations = SpeedingDetector(speed_limit_kmh=200, meters_per_px=0.5).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=30.0
    )
    assert violations == []


def test_speeding_no_fire_without_calibration() -> None:
    dets = []
    for f in range(31):
        dets.append(_det(f, 1, "vehicle", (f * 10, 0, f * 10 + 10, 10)))

    violations = SpeedingDetector(speed_limit_kmh=50, meters_per_px=None).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=30.0
    )
    assert violations == []


# ============================================
# Pipeline
# ============================================
def test_run_detectors_returns_all_violations() -> None:
    dets = [
        _det(0, 1, "vehicle", (40, 0, 60, 10)),
        _det(1, 1, "vehicle", (40, 40, 60, 50)),
        _det(2, 1, "vehicle", (40, 60, 60, 70)),
        _det(2, 99, "traffic_light_red", (200, 0, 220, 20)),
    ]
    zones = [
        Zone(zone_type="stop_line", polygon=[(0, 50), (200, 50)]),
        Zone(zone_type="lane_line_solid", polygon=[(0, 55), (200, 55)]),
    ]
    violations = run_detectors(dets, zones, fps=30.0)
    types = {v.violation_type for v in violations}
    assert ViolationType.RED_LIGHT_RUNNING in types
    assert ViolationType.ILLEGAL_OVERTAKING in types


def test_run_detectors_isolates_detector_failures() -> None:
    """فشل كاشف واحد لا يُسقط البقية."""

    class _BrokenDetector:
        def detect(self, *args, **kwargs):  # noqa: D401
            raise RuntimeError("boom")

    dets = [_det(0, 1, "vehicle", (40, 0, 60, 10))]
    out = run_detectors(dets, [], fps=30.0, detectors=[_BrokenDetector()])
    assert out == []  # لم يرفع خطأ


def test_track_properties() -> None:
    dets = [_det(0, 1, "vehicle", (0, 0, 10, 10)), _det(10, 1, "vehicle", (50, 0, 60, 10))]
    track = build_tracks(dets)[0]
    assert track.start_frame == 0
    assert track.end_frame == 10
    assert track.duration_ms > 0
