"""كاشف الوقوف الخاطئ — مركبة ثابتة داخل منطقة ممنوع الوقوف."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import is_stationary, point_in_polygon


class IllegalParkingDetector(BaseViolationDetector):
    """مركبة ثابتة لفترة طويلة داخل zone no_parking."""

    def __init__(
        self,
        *,
        min_duration_sec: float = 60.0,
        stationary_threshold_px: float = 5.0,
    ) -> None:
        self._min_duration_sec = min_duration_sec
        self._stationary_threshold_px = stationary_threshold_px

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        no_parking_zones = [z for z in zones if z.zone_type == "no_parking"]
        if not no_parking_zones:
            return []

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name != "vehicle":
                continue
            duration_s = track.duration_ms / 1000.0
            if duration_s < self._min_duration_sec:
                continue
            if not is_stationary(track.centers, threshold_px=self._stationary_threshold_px):
                continue
            # المركز داخل أي zone؟
            center = track.centers[len(track.centers) // 2]
            in_zone = any(point_in_polygon(center, z.polygon) for z in no_parking_zones)
            if not in_zone:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.ILLEGAL_PARKING,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=0.90,
                    evidence_frames=[track.start_frame, track.end_frame],
                    notes=f"وقوف ثابت لـ {duration_s:.0f} ثانية داخل منطقة ممنوع الوقوف",
                )
            )
        return violations


__all__ = ["IllegalParkingDetector"]
