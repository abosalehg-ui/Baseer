"""اختبارات كاشف إساءة استخدام أنوار التلاقي (HighBeamDetector)."""

from __future__ import annotations

import numpy as np

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.detectors.high_beam import HighBeamDetector
from app.core.frame_sampler import FrameProvider
from app.core.rules import Track


# ============================================
# FrameProvider اصطناعي للاختبار
# ============================================
class FakeFrameProvider:
    """FrameProvider يولّد إطارات numpy حسب دالة الـ frame_no."""

    def __init__(self, frames: dict[int, np.ndarray]) -> None:
        self._frames = frames

    def get_frame(self, frame_no: int) -> np.ndarray | None:
        return self._frames.get(frame_no)

    def close(self) -> None:
        pass


def _dark_frame(h: int = 200, w: int = 200) -> np.ndarray:
    """إطار ليلي مظلم (BGR)."""
    return np.full((h, w, 3), 20, dtype=np.uint8)


def _bright_frame(h: int = 200, w: int = 200) -> np.ndarray:
    """إطار نهاري ساطع — يجب تخطي الكشف عليه."""
    return np.full((h, w, 3), 200, dtype=np.uint8)


def _add_headlight_glare(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    """يضيف بقعتين بيضاوين مشبعتين (مصابيح عالية) في الثُلث السفلي من bbox."""
    out = frame.copy()
    x1, y1, x2, y2 = bbox
    # الثُلث السفلي
    third_y1 = y1 + 2 * (y2 - y1) // 3
    h_third = y2 - third_y1
    w_bbox = x2 - x1
    # مصباح يسار
    cx_l = x1 + w_bbox // 4
    cy = third_y1 + h_third // 2
    r = 8
    out[cy - r : cy + r, cx_l - r : cx_l + r] = 255  # أبيض مشبع
    # مصباح يمين
    cx_r = x1 + 3 * w_bbox // 4
    out[cy - r : cy + r, cx_r - r : cx_r + r] = 255
    return out


def _vehicle_track(track_id: int, *, frames: int, bbox, fps: float = 30.0) -> Track:
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


# ============================================
# الاختبارات
# ============================================
def test_no_video_or_provider_returns_empty() -> None:
    """بدون video_path أو provider → لا مخالفات (silent skip)."""
    detector = HighBeamDetector()
    track = _vehicle_track(1, frames=90, bbox=(40, 40, 100, 100))
    assert detector.detect([track], {}, [], fps=30.0) == []


def test_high_beam_at_night_fires_violation() -> None:
    """إطارات ليلية + بقع مشبعة في منطقة المصابيح لـ 2+ ثانية → مخالفة."""
    fps = 30.0
    bbox = (40, 40, 100, 130)
    # ننشئ 90 فريم كلها ليلية مع توهج
    frames = {i: _add_headlight_glare(_dark_frame(), bbox=(40, 40, 100, 130)) for i in range(90)}
    provider = FakeFrameProvider(frames)
    track = _vehicle_track(1, frames=90, bbox=bbox, fps=fps)

    detector = HighBeamDetector(
        frame_provider=provider, sample_every_n_frames=5, min_duration_sec=2.0
    )
    result = detector.detect([track], {}, [], fps)

    assert len(result) == 1
    assert result[0].violation_type == ViolationType.HIGH_BEAM_MISUSE
    assert result[0].track_id == 1
    assert "[heuristic]" in result[0].notes


def test_daytime_frame_no_violation() -> None:
    """إطار نهاري ساطع → فحص الليل يفشل → لا مخالفة."""
    fps = 30.0
    bbox = (40, 40, 100, 130)
    frames = {i: _add_headlight_glare(_bright_frame(), bbox=(40, 40, 100, 130)) for i in range(90)}
    provider = FakeFrameProvider(frames)
    track = _vehicle_track(1, frames=90, bbox=bbox, fps=fps)

    detector = HighBeamDetector(frame_provider=provider, sample_every_n_frames=5)
    result = detector.detect([track], {}, [], fps)
    assert result == []


def test_night_no_glare_no_violation() -> None:
    """إطارات ليلية بدون بقع ساطعة (مصابيح عادية أو مطفأة) → لا مخالفة."""
    fps = 30.0
    bbox = (40, 40, 100, 130)
    frames = {i: _dark_frame() for i in range(90)}
    provider = FakeFrameProvider(frames)
    track = _vehicle_track(1, frames=90, bbox=bbox, fps=fps)

    detector = HighBeamDetector(frame_provider=provider, sample_every_n_frames=5)
    result = detector.detect([track], {}, [], fps)
    assert result == []


def test_brief_glare_does_not_emit_violation() -> None:
    """توهج قصير (نصف ثانية فقط) أقل من العتبة → لا مخالفة."""
    fps = 30.0
    bbox = (40, 40, 100, 130)
    # 15 فريم فقط = 0.5 ثانية
    frames = {i: _add_headlight_glare(_dark_frame(), bbox=(40, 40, 100, 130)) for i in range(15)}
    provider = FakeFrameProvider(frames)
    track = _vehicle_track(1, frames=15, bbox=bbox, fps=fps)

    detector = HighBeamDetector(
        frame_provider=provider, sample_every_n_frames=1, min_duration_sec=2.0
    )
    result = detector.detect([track], {}, [], fps)
    assert result == []


def test_pedestrian_track_ignored() -> None:
    """مسارات الأشخاص (وليس المركبات) يجب تجاهلها."""
    fps = 30.0
    bbox = (40, 40, 100, 130)
    frames = {i: _add_headlight_glare(_dark_frame(), bbox=(40, 40, 100, 130)) for i in range(90)}
    provider = FakeFrameProvider(frames)
    person_dets = [
        Detection(
            frame_no=i,
            timestamp_ms=int(i * 1000 / fps),
            class_name="person",
            confidence=0.9,
            bbox=bbox,
            track_id=99,
        )
        for i in range(90)
    ]
    track = Track(track_id=99, class_name="person", detections=person_dets)

    detector = HighBeamDetector(frame_provider=provider, sample_every_n_frames=5)
    result = detector.detect([track], {}, [], fps)
    assert result == []
