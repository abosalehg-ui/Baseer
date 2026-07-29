"""كاشف السرعة الزائدة — يحتاج معايرة meters_per_px."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import speed_from_centers_kmh


class SpeedingDetector(BaseViolationDetector):
    """السرعة > الحد المسموح (يحتاج Calibration)."""

    def __init__(
        self,
        *,
        speed_limit_kmh: float = 80.0,
        meters_per_px: float | None = None,
        fps_override: float | None = None,
    ) -> None:
        self._speed_limit_kmh = speed_limit_kmh
        self._meters_per_px = meters_per_px
        self._fps_override = fps_override

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        if self._meters_per_px is None or self._meters_per_px <= 0:
            return []
        effective_fps = self._fps_override or fps
        if effective_fps <= 0:
            return []

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in ("vehicle", "motorcycle"):
                continue
            if len(track.centers) < 2:
                continue
            assert self._meters_per_px is not None
            speed = speed_from_centers_kmh(track.centers, effective_fps, self._meters_per_px)
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
