"""اختبارات كاشف عدم الالتزام بالمسار (LaneKeepingDetector)."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.detectors.lane_keeping import LaneKeepingDetector
from app.core.rules import Track, Zone
from app.utils.geometry import clip_segment_to_bbox


# ============================================
# اختبارات helper الهندسية
# ============================================
def test_clip_segment_inside_bbox_returns_full_length() -> None:
    """قطعة بالكامل داخل bbox → الطول الكامل."""
    length = clip_segment_to_bbox((10.0, 50.0), (90.0, 50.0), (0.0, 0.0, 100.0, 100.0))
    assert abs(length - 80.0) < 1e-6


def test_clip_segment_outside_bbox_returns_zero() -> None:
    """قطعة خارج الـ bbox تماماً → 0."""
    length = clip_segment_to_bbox((200.0, 200.0), (300.0, 300.0), (0.0, 0.0, 100.0, 100.0))
    assert length == 0.0


def test_clip_segment_partially_inside_bbox() -> None:
    """قطعة تمتد من داخل الـ bbox إلى خارجه."""
    length = clip_segment_to_bbox((50.0, 50.0), (150.0, 50.0), (0.0, 0.0, 100.0, 100.0))
    assert abs(length - 50.0) < 1e-6


# ============================================
# helpers لبناء tracks اصطناعية
# ============================================
def _make_vehicle_track(
    *, track_id: int, frames: int, bbox=(40.0, 40.0, 80.0, 100.0), fps: float = 30.0
) -> Track:
    dets = [
        Detection(
            frame_no=i,
            timestamp_ms=int(i * 1000 / fps),
            class_name="vehicle",
            confidence=0.9,
            bbox=bbox,
            track_id=track_id,
        )
        for i in range(frames)
    ]
    return Track(track_id=track_id, class_name="vehicle", detections=dets)


def _make_line_detection(frame_no: int, *, fps: float = 30.0) -> Detection:
    """خط يمر عبر صناديق المركبات أعلاه (من x=0 إلى x=200 على y=70)."""
    return Detection(
        frame_no=frame_no,
        timestamp_ms=int(frame_no * 1000 / fps),
        class_name="lane_line_dashed",
        confidence=0.7,
        bbox=(0.0, 65.0, 200.0, 75.0),
        track_id=None,
    )


# ============================================
# اختبارات الكاشف
# ============================================
def test_sustained_straddle_emits_violation() -> None:
    """مركبة فوق خط مسار لـ 90 فريم (3 ثوانٍ عند 30fps) → مخالفة."""
    fps = 30.0
    track = _make_vehicle_track(track_id=1, frames=90, fps=fps)
    by_frame = {i: [_make_line_detection(i, fps=fps)] for i in range(90)}

    detector = LaneKeepingDetector(min_straddle_sec=2.0)
    result = detector.detect([track], by_frame, [], fps)

    assert len(result) == 1
    assert result[0].violation_type == ViolationType.LANE_KEEPING
    assert result[0].track_id == 1
    assert result[0].confidence >= 0.7


def test_brief_drift_does_not_emit_violation() -> None:
    """تطفّل قصير (10 فريم = 0.33 ثانية) أقصر من العتبة → لا مخالفة."""
    fps = 30.0
    track = _make_vehicle_track(track_id=2, frames=10, fps=fps)
    by_frame = {i: [_make_line_detection(i, fps=fps)] for i in range(10)}

    detector = LaneKeepingDetector(min_straddle_sec=2.0)
    result = detector.detect([track], by_frame, [], fps)

    assert result == []


def test_no_line_no_violation() -> None:
    """مركبة طويلة بلا خطوط مسار قريبة → لا مخالفة."""
    fps = 30.0
    track = _make_vehicle_track(track_id=3, frames=90, fps=fps)
    detector = LaneKeepingDetector()
    result = detector.detect([track], {}, [], fps)
    assert result == []


def test_line_far_from_vehicle_no_violation() -> None:
    """خط مسار بعيد عن المركبة → لا تداخل → لا مخالفة."""
    fps = 30.0
    track = _make_vehicle_track(track_id=4, frames=90, bbox=(40.0, 40.0, 80.0, 100.0), fps=fps)
    # الخط على y=300، بعيد عن المركبة (y < 100)
    far_line = Detection(
        frame_no=0,
        timestamp_ms=0,
        class_name="lane_line_solid",
        confidence=0.7,
        bbox=(0.0, 295.0, 200.0, 305.0),
        track_id=None,
    )
    by_frame = {i: [Detection(**{**far_line.__dict__, "frame_no": i})] for i in range(90)}

    detector = LaneKeepingDetector()
    result = detector.detect([track], by_frame, [], fps)
    assert result == []


def test_zone_line_also_triggers_violation() -> None:
    """خط مسار من Zone مرسومة يدوياً (وليس YOLO) يجب أن يطلق المخالفة."""
    fps = 30.0
    track = _make_vehicle_track(track_id=5, frames=90, fps=fps)
    zone = Zone(zone_type="lane_line_solid", polygon=[(0.0, 70.0), (200.0, 70.0)])

    detector = LaneKeepingDetector(min_straddle_sec=2.0)
    result = detector.detect([track], {}, [zone], fps)

    assert len(result) == 1
    assert result[0].violation_type == ViolationType.LANE_KEEPING


def test_pedestrian_ignored() -> None:
    """يجب تجاهل المسارات التي ليست مركبة أو دراجة نارية."""
    fps = 30.0
    person_dets = [
        Detection(
            frame_no=i,
            timestamp_ms=int(i * 1000 / fps),
            class_name="person",
            confidence=0.9,
            bbox=(40.0, 40.0, 80.0, 100.0),
            track_id=99,
        )
        for i in range(90)
    ]
    track = Track(track_id=99, class_name="person", detections=person_dets)
    by_frame = {i: [_make_line_detection(i, fps=fps)] for i in range(90)}

    detector = LaneKeepingDetector()
    result = detector.detect([track], by_frame, [], fps)
    assert result == []
