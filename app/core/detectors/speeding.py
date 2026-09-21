"""كاشف السرعة الزائدة — يحتاج معايرة meters_per_px."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import speed_from_timed_centers_kmh


class SpeedingDetector(BaseViolationDetector):
    """السرعة > الحد المسموح (يحتاج Calibration)."""

    def __init__(
        self,
        *,
        speed_limit_kmh: float = 80.0,
        meters_per_px: float | None = None,
    ) -> None:
        # لا `fps_override` هنا عن قصد: السرعة تُحسب من توقيتات الكشوفات
        # (`timed_centers`) لا من معدّل الإطارات، فمعامل fps لم يبقَ له أثر على
        # الناتج — إبقاؤه كان سيوحي بتحكّم لا وجود له.
        self._speed_limit_kmh = speed_limit_kmh
        self._meters_per_px = meters_per_px

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        meters_per_px = self._meters_per_px
        if meters_per_px is None or meters_per_px <= 0:
            return []

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in ("vehicle", "motorcycle"):
                continue
            if len(track.detections) < 2:
                continue
            speed = speed_from_timed_centers_kmh(track.timed_centers, meters_per_px)
            if speed <= self._speed_limit_kmh:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.SPEEDING,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=0.75,
                    evidence_frames=[track.start_frame, track.end_frame],
                    notes=f"السرعة {speed:.0f} كم/س > الحد {self._speed_limit_kmh:.0f}",
                )
            )
        return violations


__all__ = ["SpeedingDetector"]
