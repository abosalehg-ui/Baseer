"""كاشف السير بالاتجاه المعاكس — مقارنة بالاتجاه السائد للمقطع."""

from __future__ import annotations

import math

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import Point, heading_angle


class WrongDirectionDetector(BaseViolationDetector):
    """track يتحرك ضد الاتجاه السائد > 80% لمدة > 2 ثانية."""

    def __init__(
        self,
        *,
        min_duration_sec: float = 2.0,
        opposite_threshold: float = 0.8,
    ) -> None:
        self._min_duration_sec = min_duration_sec
        self._opposite_threshold = opposite_threshold

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        # تحديد الاتجاه السائد من كل الـ tracks
        vehicle_tracks = [
            t for t in tracks if t.class_name in ("vehicle", "motorcycle") and len(t.centers) >= 2
        ]
        if len(vehicle_tracks) < 3:
            return []  # نحتاج عيّنة كافية

        prevailing = self._prevailing_direction(vehicle_tracks)
        if prevailing is None:
            return []

        violations: list[ViolationCandidate] = []
        for track in vehicle_tracks:
            opposite_ratio = self._opposite_ratio(track.centers, prevailing)
            if opposite_ratio < self._opposite_threshold:
                continue
            duration_s = track.duration_ms / 1000.0
            if duration_s < self._min_duration_sec:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.WRONG_DIRECTION,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=min(0.95, opposite_ratio),
                    evidence_frames=[
                        d.frame_no for d in track.detections[:: max(1, len(track.detections) // 3)]
                    ],
                    notes=f"{opposite_ratio:.0%} حركة عكسية للاتجاه السائد",
                )
            )
        return violations

    @staticmethod
    def _prevailing_direction(tracks: list[Track]) -> float | None:
        angles: list[float] = []
        for t in tracks:
            angles.append(heading_angle(t.centers[0], t.centers[-1]))
        if not angles:
            return None
        # متوسط دائري
        sin_sum = sum(math.sin(a) for a in angles)
        cos_sum = sum(math.cos(a) for a in angles)
        return math.atan2(sin_sum, cos_sum)

    @staticmethod
    def _opposite_ratio(centers: list[Point], prevailing: float) -> float:
        opposite = math.pi  # 180°
        opposite_count = 0
        total = 0
        for i in range(len(centers) - 1):
            ang = heading_angle(centers[i], centers[i + 1])
            diff = abs(((ang - prevailing) + math.pi) % (2 * math.pi) - math.pi)
            total += 1
            # عكس الاتجاه: الفرق قريب من π (180°) ضمن tolerance ±60°
            if abs(diff - opposite) < (math.pi / 3):
                opposite_count += 1
        return opposite_count / total if total else 0.0


__all__ = ["WrongDirectionDetector"]
