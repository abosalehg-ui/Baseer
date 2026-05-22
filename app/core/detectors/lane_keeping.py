"""كاشف عدم الالتزام بالمسار — تطفّل مستمر على خط مسار (متصل أو متقطع)."""

from __future__ import annotations

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.rules import BaseViolationDetector, Track, ViolationCandidate, Zone
from app.utils.geometry import BBox, clip_segment_to_bbox

LANE_LINE_CLASSES = ("lane_line_solid", "lane_line_dashed")


class LaneKeepingDetector(BaseViolationDetector):
    """يكشف بقاء المركبة فوق خط المسار (straddle) لمدة مطوّلة.

    الفرق عن `IllegalOvertakingDetector`:
    - ذاك يكشف عبور **مرة واحدة** لخط متصل.
    - هذا يكشف **التطفل المستمر** (drift/straddle) على أي خط، حتى المتقطع.
    """

    def __init__(
        self,
        *,
        min_straddle_sec: float = 2.0,
        straddle_overlap_ratio: float = 0.15,
    ) -> None:
        self._min_straddle_sec = min_straddle_sec
        self._straddle_overlap_ratio = straddle_overlap_ratio

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        if fps <= 0:
            return []

        zone_lines = [z for z in zones if z.zone_type in LANE_LINE_CLASSES]

        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in ("vehicle", "motorcycle"):
                continue
            straddle_runs = self._find_straddle_runs(track, frame_detections, zone_lines, fps)
            for start_frame, end_frame, max_overlap_ratio in straddle_runs:
                duration_s = (end_frame - start_frame + 1) / fps
                if duration_s < self._min_straddle_sec:
                    continue
                start_ms = int(start_frame * 1000 / fps)
                end_ms = int(end_frame * 1000 / fps)
                violations.append(
                    ViolationCandidate(
                        violation_type=ViolationType.LANE_KEEPING,
                        track_id=track.track_id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=min(0.95, duration_s / 4.0),
                        evidence_frames=[start_frame, (start_frame + end_frame) // 2, end_frame],
                        notes=(
                            f"تطفّل على خط المسار لمدة {duration_s:.1f} ثانية "
                            f"(نسبة تداخل قصوى {max_overlap_ratio:.0%})"
                        ),
                    )
                )
        return violations

    def _find_straddle_runs(
        self,
        track: Track,
        frame_detections: dict[int, list[Detection]],
        zone_lines: list[Zone],
        fps: float,
    ) -> list[tuple[int, int, float]]:
        runs: list[tuple[int, int, float]] = []
        current_start: int | None = None
        current_max: float = 0.0
        last_frame: int | None = None

        for det in track.detections:
            bbox_w = max(1.0, det.bbox[2] - det.bbox[0])
            bbox_h = max(1.0, det.bbox[3] - det.bbox[1])
            threshold = self._straddle_overlap_ratio * min(bbox_w, bbox_h)

            overlap_ratio = self._max_line_overlap_in_frame(
                det.bbox, det.frame_no, frame_detections, zone_lines
            ) / min(bbox_w, bbox_h)

            is_straddle = (overlap_ratio * min(bbox_w, bbox_h)) > threshold

            if is_straddle:
                if current_start is None:
                    current_start = det.frame_no
                current_max = max(current_max, overlap_ratio)
                last_frame = det.frame_no
            else:
                if current_start is not None and last_frame is not None:
                    runs.append((current_start, last_frame, current_max))
                current_start = None
                current_max = 0.0
                last_frame = None

        if current_start is not None and last_frame is not None:
            runs.append((current_start, last_frame, current_max))
        return runs

    @staticmethod
    def _max_line_overlap_in_frame(
        bbox: BBox,
        frame_no: int,
        frame_detections: dict[int, list[Detection]],
        zone_lines: list[Zone],
    ) -> float:
        """يعيد أكبر طول تداخل (بكسل) بين أي خط مسار وصندوق المركبة في هذا الفريم."""
        max_overlap = 0.0

        # 1) خطوط مكتشفة من YOLO في نفس الفريم — bbox الخط نُمثّله بقطعة بين زاويتي قُطر الـbbox
        for det in frame_detections.get(frame_no, []):
            if det.class_name not in LANE_LINE_CLASSES:
                continue
            lx1, ly1, lx2, ly2 = det.bbox
            # نختار القُطر الأطول كتقريب لاتجاه الخط (الخطوط عادةً طويلة وضيقة)
            length = clip_segment_to_bbox((lx1, ly1), (lx2, ly2), bbox)
            if length > max_overlap:
                max_overlap = length

        # 2) خطوط من Zones (مرسومة يدوياً) — polygon أول نقطتين تمثلان قطعة الخط
        for zone in zone_lines:
            if len(zone.polygon) < 2:
                continue
            length = clip_segment_to_bbox(zone.polygon[0], zone.polygon[1], bbox)
            if length > max_overlap:
                max_overlap = length

        return max_overlap
