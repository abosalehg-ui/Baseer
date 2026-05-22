"""اختبارات كاشف المسافة الآمنة (FollowingDistanceDetector)."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.detectors.following_distance import FollowingDistanceDetector
from app.core.rules import Track


def _vehicle_track(
    track_id: int,
    *,
    bbox_at_frame,
    frames: int,
    fps: float = 30.0,
) -> Track:
    dets = [
        Detection(
            frame_no=i,
            timestamp_ms=int(i * 1000 / fps),
            class_name="vehicle",
            confidence=0.9,
            bbox=bbox_at_frame(i),
            track_id=track_id,
        )
        for i in range(frames)
    ]
    return Track(track_id=track_id, class_name="vehicle", detections=dets)


def test_no_calibration_returns_empty() -> None:
    """بدون meters_per_px → لا مخالفات."""
    detector = FollowingDistanceDetector(meters_per_px=None)
    track = _vehicle_track(1, bbox_at_frame=lambda f: (0.0, 0.0, 10.0, 10.0), frames=10)
    assert detector.detect([track, track], {}, [], fps=30.0) == []


def test_close_following_at_high_speed_fires_violation() -> None:
    """مركبتان في نفس المسار بمسافة 1m فقط لمدة 4 ثوانٍ بسرعة 60+ كم/س → مخالفة."""
    fps = 30.0
    # كلاهما يتحركان أفقياً بنفس السرعة (3px/frame) — المسافة الرأسية ثابتة 5px
    leader = _vehicle_track(
        track_id=1,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 100.0, 140.0 + f * 3.0, 130.0),
        frames=120,
        fps=fps,
    )
    follower = _vehicle_track(
        track_id=2,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 135.0, 140.0 + f * 3.0, 165.0),
        frames=120,
        fps=fps,
    )

    detector = FollowingDistanceDetector(
        meters_per_px=0.2,
        ttc_threshold_sec=2.0,
        min_violation_sec=2.0,
    )
    result = detector.detect([leader, follower], {}, [], fps)
    assert len(result) == 1
    assert result[0].violation_type == ViolationType.UNSAFE_FOLLOWING
    # المتبوع هو الـtrack الأقرب للكاميرا (bottom_y أكبر) — أي track_id=2
    assert result[0].track_id == 2


def test_different_lanes_no_violation() -> None:
    """مركبتان في مسارين مختلفين (x مختلف بكثير) → لا مخالفة حتى لو متقاربتان رأسياً."""
    fps = 30.0
    leader = _vehicle_track(
        track_id=1,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 100.0, 140.0 + f * 3.0, 130.0),
        frames=90,
        fps=fps,
    )
    follower = _vehicle_track(
        track_id=2,
        bbox_at_frame=lambda f: (400.0 + f * 3.0, 135.0, 440.0 + f * 3.0, 165.0),
        frames=90,
        fps=fps,
    )
    detector = FollowingDistanceDetector(meters_per_px=0.2)
    result = detector.detect([leader, follower], {}, [], fps)
    assert result == []


def test_stopped_traffic_no_violation() -> None:
    """مركبتان ثابتتان قريبتان (إشارة حمراء) → لا مخالفة لأن السرعة < 15 كم/س."""
    fps = 30.0
    leader = _vehicle_track(
        track_id=1, bbox_at_frame=lambda f: (100.0, 100.0, 140.0, 130.0), frames=90, fps=fps
    )
    follower = _vehicle_track(
        track_id=2, bbox_at_frame=lambda f: (100.0, 135.0, 140.0, 165.0), frames=90, fps=fps
    )
    detector = FollowingDistanceDetector(meters_per_px=0.2, min_speed_kmh=15.0)
    result = detector.detect([leader, follower], {}, [], fps)
    assert result == []


def test_safe_distance_no_violation() -> None:
    """مركبتان في نفس المسار بمسافة كافية (50m) → لا مخالفة."""
    fps = 30.0
    # مسافة رأسية = 250 بكسل × 0.2 m/px = 50 متر — آمنة
    leader = _vehicle_track(
        track_id=1,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 100.0, 140.0 + f * 3.0, 130.0),
        frames=120,
        fps=fps,
    )
    follower = _vehicle_track(
        track_id=2,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 380.0, 140.0 + f * 3.0, 410.0),
        frames=120,
        fps=fps,
    )
    detector = FollowingDistanceDetector(meters_per_px=0.2)
    result = detector.detect([leader, follower], {}, [], fps)
    assert result == []


def test_brief_close_pass_does_not_emit_violation() -> None:
    """تقارب قصير (< min_violation_sec) لا يولّد مخالفة حتى لو كان شديد القرب."""
    fps = 30.0
    # 30 فريم فقط = 1 ثانية (أقل من min_violation_sec=2.0)
    leader = _vehicle_track(
        track_id=1,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 100.0, 140.0 + f * 3.0, 130.0),
        frames=30,
        fps=fps,
    )
    follower = _vehicle_track(
        track_id=2,
        bbox_at_frame=lambda f: (100.0 + f * 3.0, 135.0, 140.0 + f * 3.0, 165.0),
        frames=30,
        fps=fps,
    )
    detector = FollowingDistanceDetector(meters_per_px=0.2, min_violation_sec=2.0)
    result = detector.detect([leader, follower], {}, [], fps)
    assert result == []
