"""محرك المخالفات — يفحص الكشوفات والـ tracks ضد قواعد محددة."""

from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.utils.geometry import (
    BBox,
    Point,
    bbox_center,
    euclidean_distance,
    heading_angle,
    iou,
    is_stationary,
    point_in_polygon,
    segments_intersect,
)

logger = logging.getLogger(__name__)


# ============================================
# هياكل البيانات
# ============================================
@dataclass(frozen=True)
class Zone:
    """منطقة محددة في الفيديو (polygon + نوع)."""

    zone_type: str
    polygon: list[Point]
    metadata: dict | None = None


@dataclass
class Track:
    """مسار object واحد عبر فريمات متعددة."""

    track_id: int
    class_name: str
    detections: list[Detection]

    @property
    def start_frame(self) -> int:
        return self.detections[0].frame_no if self.detections else 0

    @property
    def end_frame(self) -> int:
        return self.detections[-1].frame_no if self.detections else 0

    @property
    def start_ms(self) -> int:
        return self.detections[0].timestamp_ms if self.detections else 0

    @property
    def end_ms(self) -> int:
        return self.detections[-1].timestamp_ms if self.detections else 0

    @property
    def centers(self) -> list[Point]:
        return [bbox_center(d.bbox) for d in self.detections]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class ViolationCandidate:
    """مخالفة مرشّحة — تُخزَّن لاحقاً في جدول violations."""

    violation_type: ViolationType
    track_id: int | None
    start_ms: int
    end_ms: int
    confidence: float
    evidence_frames: list[int] = field(default_factory=list)
    notes: str = ""


# ============================================
# بناء tracks من detections
# ============================================
def build_tracks(detections: list[Detection]) -> list[Track]:
    """يجمّع الكشوفات حسب track_id إلى Track objects."""
    by_track: dict[int, list[Detection]] = defaultdict(list)
    for d in detections:
        if d.track_id is not None:
            by_track[d.track_id].append(d)
    tracks: list[Track] = []
    for tid, dets in by_track.items():
        dets.sort(key=lambda d: d.frame_no)
        classes = {d.class_name for d in dets}
        # الـ class الأكثر تكراراً
        main_class = max(classes, key=lambda c: sum(1 for d in dets if d.class_name == c))
        tracks.append(Track(track_id=tid, class_name=main_class, detections=dets))
    return tracks


def detections_by_frame(detections: list[Detection]) -> dict[int, list[Detection]]:
    """يُجمّع الكشوفات حسب رقم الفريم."""
    out: dict[int, list[Detection]] = defaultdict(list)
    for d in detections:
        out[d.frame_no].append(d)
    return dict(out)


# ============================================
# Base detector
# ============================================
class BaseViolationDetector(ABC):
    """قاعدة كاشف المخالفات."""

    @abstractmethod
    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]: ...


# ============================================
# 1. قطع الإشارة الحمراء
# ============================================
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
            crossed_at = self._frame_where_track_crosses(track, stop_lines)
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
    def _frame_where_track_crosses(track: Track, stop_lines: list[Zone]) -> int | None:
        centers = track.centers
        for i in range(len(centers) - 1):
            a, b = centers[i], centers[i + 1]
            for line in stop_lines:
                if len(line.polygon) < 2:
                    continue
                if segments_intersect(a, b, line.polygon[0], line.polygon[1]):
                    return track.detections[i + 1].frame_no
        return None

    @staticmethod
    def _evidence(track: Track, target_frame: int) -> list[int]:
        all_frames = [d.frame_no for d in track.detections]
        if not all_frames:
            return []
        idx = min(range(len(all_frames)), key=lambda i: abs(all_frames[i] - target_frame))
        start = max(0, idx - 2)
        end = min(len(all_frames), idx + 3)
        return all_frames[start:end]


# ============================================
# 2. الاتجاه المعاكس
# ============================================
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


# ============================================
# 3. عدم لبس الخوذة
# ============================================
class NoHelmetDetector(BaseViolationDetector):
    """motorcycle مع person بدون helmet متداخل لـ > 2 ثانية."""

    def __init__(self, *, min_duration_sec: float = 2.0, iou_threshold: float = 0.1) -> None:
        self._min_duration_sec = min_duration_sec
        self._iou_threshold = iou_threshold

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
                    d.class_name == "person" and _bbox_above(d.bbox, det.bbox) for d in same_frame
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
            duration_s = (no_helmet_frames[-1] - no_helmet_frames[0]) / max(fps, 1e-6)
            if duration_s < self._min_duration_sec:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.NO_HELMET,
                    track_id=track.track_id,
                    start_ms=track.start_ms,
                    end_ms=track.end_ms,
                    confidence=0.80,
                    evidence_frames=no_helmet_frames[:5],
                    notes=f"دراجة بدون خوذة لـ {duration_s:.1f} ثانية",
                )
            )
        return violations


def _bbox_above(person_bbox: BBox, vehicle_bbox: BBox) -> bool:
    """هل مركز الـ person فوق الـ motorcycle/vehicle (تقريباً)؟"""
    px, py = bbox_center(person_bbox)
    vx, vy = bbox_center(vehicle_bbox)
    horizontal_align = vehicle_bbox[0] <= px <= vehicle_bbox[2]
    return horizontal_align and py < vy


# ============================================
# 4. الوقوف الخاطئ
# ============================================
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


# ============================================
# 5. التجاوز الخاطئ (يعبر خط مستمر)
# ============================================
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
            crossed_at = self._frame_where_track_crosses(track, solid_lines)
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

    @staticmethod
    def _frame_where_track_crosses(track: Track, lines: list[Zone]) -> int | None:
        centers = track.centers
        for i in range(len(centers) - 1):
            for line in lines:
                if len(line.polygon) < 2:
                    continue
                if segments_intersect(centers[i], centers[i + 1], line.polygon[0], line.polygon[1]):
                    return track.detections[i + 1].frame_no
        return None


# ============================================
# 6. السرعة الزائدة (اختياري — يحتاج معايرة)
# ============================================
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
            speed = self._estimate_speed(track, effective_fps)
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

    def _estimate_speed(self, track: Track, fps: float) -> float:
        assert self._meters_per_px is not None
        centers = track.centers
        total_px = sum(
            euclidean_distance(centers[i], centers[i + 1]) for i in range(len(centers) - 1)
        )
        n_intervals = len(centers) - 1
        dt_s = n_intervals / fps
        if dt_s <= 0:
            return 0.0
        return (total_px * self._meters_per_px / dt_s) * 3.6


# ============================================
# الـ pipeline الرئيسي
# ============================================
def all_default_detectors() -> list[BaseViolationDetector]:
    """يُرجع كل الكواشف الافتراضية (بدون speeding/high_beam — يحتاجان معايرة/فيديو)."""
    from app.core.detectors import LaneKeepingDetector

    return [
        RedLightDetector(),
        WrongDirectionDetector(),
        NoHelmetDetector(),
        IllegalParkingDetector(),
        IllegalOvertakingDetector(),
        LaneKeepingDetector(),
    ]


def run_detectors(
    detections: list[Detection],
    zones: list[Zone],
    fps: float,
    detectors: list[BaseViolationDetector] | None = None,
) -> list[ViolationCandidate]:
    """يُشغّل كل الكواشف ويُرجع المخالفات الـ candidates."""
    detectors = detectors or all_default_detectors()
    tracks = build_tracks(detections)
    by_frame = detections_by_frame(detections)
    out: list[ViolationCandidate] = []
    for detector in detectors:
        try:
            out.extend(detector.detect(tracks, by_frame, zones, fps))
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل الكاشف %s: %s", detector.__class__.__name__, exc)
    return out


def load_zones_from_db(video_id: int, db) -> list[Zone]:
    """يقرأ zones مقطع من جدول zones."""
    rows = db.fetch_all(
        "SELECT zone_type, polygon, metadata FROM zones WHERE video_id = ?",
        (video_id,),
    )
    out: list[Zone] = []
    for r in rows:
        polygon_data = json.loads(r[1]) if r[1] else []
        polygon = [(float(p[0]), float(p[1])) for p in polygon_data]
        metadata = json.loads(r[2]) if r[2] else None
        out.append(Zone(zone_type=str(r[0]), polygon=polygon, metadata=metadata))
    return out


__all__ = [
    "BaseViolationDetector",
    "IllegalOvertakingDetector",
    "IllegalParkingDetector",
    "NoHelmetDetector",
    "RedLightDetector",
    "SpeedingDetector",
    "Track",
    "ViolationCandidate",
    "WrongDirectionDetector",
    "Zone",
    "all_default_detectors",
    "build_tracks",
    "detections_by_frame",
    "load_zones_from_db",
    "run_detectors",
]
