"""كاشف التجاوز الخاطئ — عبور خط مستمر (lane_line_solid)."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import (
    BaseViolationDetector,
    Track,
    ViolationCandidate,
    Zone,
    first_crossing_frame,
)


class IllegalOvertakingDetector(BaseViolationDetector):
    """مركبة تعبر خط lane_line_solid."""

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        solid_lines = [z for z in zones if z.zone_type == "lane_line_solid"]
        if not solid_lines:
            return []

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in ("vehicle", "motorcycle"):
                continue
            crossed_at = first_crossing_frame(track, solid_lines)
            if crossed_at is None:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.ILLEGAL_OVERTAKING,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=0.70,
                    evidence_frames=[crossed_at],
                    notes=f"عبر خطاً مستمراً في الفريم {crossed_at}",
                )
            )
        return violations


__all__ = ["IllegalOvertakingDetector"]
