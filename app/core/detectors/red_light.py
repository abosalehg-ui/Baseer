"""كاشف قطع الإشارة الحمراء — مركبة تعبر خط التوقف والإشارة حمراء."""

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


class RedLightDetector(BaseViolationDetector):
    """مركبة تعبر خط التوقف بينما الإشارة حمراء."""

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        stop_lines = [z for z in zones if z.zone_type == "stop_line"]
        if not stop_lines:
            return []

        red_frames = {
            f
            for f, dets in frame_detections.items()
            if any(d.class_name == "traffic_light_red" for d in dets)
        }
        if not red_frames:
            return []

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in ("vehicle", "motorcycle"):
                continue
            crossed_at = first_crossing_frame(track, stop_lines)
            if crossed_at is None or crossed_at not in red_frames:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.RED_LIGHT_RUNNING,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=0.85,
                    evidence_frames=self._evidence(track, crossed_at),
                    notes=f"عبر خط التوقف في الفريم {crossed_at} والإشارة حمراء",
                )
            )
        return violations

    @staticmethod
    def _evidence(track: Track, target_frame: int) -> list[int]:
        all_frames = [d.frame_no for d in track.detections]
        if not all_frames:
            return []
        idx = min(range(len(all_frames)), key=lambda i: abs(all_frames[i] - target_frame))
        start = max(0, idx - 2)
        end = min(len(all_frames), idx + 3)
        return all_frames[start:end]


__all__ = ["RedLightDetector"]
