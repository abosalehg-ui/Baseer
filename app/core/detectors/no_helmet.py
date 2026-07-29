"""كاشف عدم لبس الخوذة — راكب دراجة بلا خوذة لفترة متواصلة."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.violations import (
    BaseViolationDetector,
    Track,
    ViolationCandidate,
    Zone,
    bbox_above,
    consecutive_runs,
)
from app.utils.geometry import iou


class NoHelmetDetector(BaseViolationDetector):
    """motorcycle مع person بدون helmet متداخل لـ > 2 ثانية."""

    def __init__(
        self,
        *,
        min_duration_sec: float = 2.0,
        iou_threshold: float = 0.1,
        max_gap_frames: int = 2,
    ) -> None:
        self._min_duration_sec = min_duration_sec
        self._iou_threshold = iou_threshold
        # فجوة مسموحة داخل الفترة المتتالية (كشف مفقود عابر لا يقطع المخالفة)
        self._max_gap_frames = max_gap_frames

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name != "motorcycle":
                continue
            no_helmet_frames: list[int] = []
            for det in track.detections:
                same_frame = frame_detections.get(det.frame_no, [])
                has_person = any(
                    d.class_name == "person" and bbox_above(d.bbox, det.bbox) for d in same_frame
                )
                if not has_person:
                    continue
                has_helmet = any(
                    d.class_name == "helmet" and iou(d.bbox, det.bbox) >= self._iou_threshold
                    for d in same_frame
                )
                if not has_helmet:
                    no_helmet_frames.append(det.frame_no)

            if not no_helmet_frames:
                continue

            # المدة تُحسب من أطول فترة **متتالية** لا من (الأخير − الأول): دراجة
            # بلا خوذة في الفريم 10 وأخرى في الفريم 400 ليست مخالفة 13 ثانية.
            runs = consecutive_runs(no_helmet_frames, max_gap=self._max_gap_frames)
            best = max(runs, key=lambda r: r[1] - r[0])
            duration_s = (best[1] - best[0] + 1) / max(fps, 1e-6)
            if duration_s < self._min_duration_sec:
                continue

            run_frames = [f for f in no_helmet_frames if best[0] <= f <= best[1]]
            frame_to_ms = {d.frame_no: d.timestamp_ms for d in track.detections}
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.NO_HELMET,
                    track_id=track.track_id,
                    start_ms=frame_to_ms.get(best[0], track.start_ms),
                    end_ms=frame_to_ms.get(best[1], track.end_ms),
                    confidence=0.80,
                    evidence_frames=run_frames[:5],
                    notes=f"دراجة بدون خوذة لـ {duration_s:.1f} ثانية متواصلة",
                )
            )
        return violations


__all__ = ["NoHelmetDetector"]
