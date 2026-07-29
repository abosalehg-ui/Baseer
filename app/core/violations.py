"""أنواع محرك المخالفات ومساعداته المشتركة.

مفصولة عن `rules.py` حتى تستوردها كل الكواشف في `app/core/detectors/` بلا
دورة استيراد، وحتى يبقى كل ملف ضمن حد الأسطر المُعلَن في `docs/architecture.md`.

`rules.py` يُعيد تصدير كل ما هنا، فالاستيراد منه يبقى صالحاً.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.utils.geometry import (
    BBox,
    Point,
    bbox_center,
    parse_metadata_json,
    parse_polygon_json,
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
    metadata: dict[str, Any] | None = None


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
# مساعدات مشتركة بين الكواشف
# ============================================
def first_crossing_frame(track: Track, lines: list[Zone]) -> int | None:
    """رقم أول فريم يعبر فيه مركز الـtrack أياً من الخطوط المعطاة، أو None.

    مشتركة بين `RedLightDetector` و`IllegalOvertakingDetector` — كانت مكرّرة
    حرفياً في الاثنين. كل zone يُمثَّل خطه بأول نقطتين من الـpolygon.
    """
    centers = track.centers
    for i in range(len(centers) - 1):
        for line in lines:
            if len(line.polygon) < 2:
                continue
            if segments_intersect(centers[i], centers[i + 1], line.polygon[0], line.polygon[1]):
                return track.detections[i + 1].frame_no
    return None


def consecutive_runs(frames: list[int], *, max_gap: int = 1) -> list[tuple[int, int]]:
    """يقسم أرقام إطارات متفرقة إلى فترات متتالية (start, end).

    يسمح بفجوة `max_gap` إطاراً (كشف مفقود عابر) قبل قطع الفترة. ضروري لأن
    حساب المدة من (الأخير − الأول) على مجموعة متفرقة يبالغ في التقدير بشدة:
    كشف في الإطار 10 وآخر في الإطار 400 ليس «13 ثانية متواصلة».
    """
    if not frames:
        return []
    ordered = sorted(set(frames))
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for f in ordered[1:]:
        if f - prev > max_gap + 1:
            runs.append((start, prev))
            start = f
        prev = f
    runs.append((start, prev))
    return runs


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


def bbox_above(person_bbox: BBox, vehicle_bbox: BBox) -> bool:
    """هل مركز الـ person فوق الـ motorcycle/vehicle (تقريباً)؟"""
    px, py = bbox_center(person_bbox)
    vx, vy = bbox_center(vehicle_bbox)
    horizontal_align = vehicle_bbox[0] <= px <= vehicle_bbox[2]
    return horizontal_align and py < vy


def load_zones_from_db(video_id: int, db: Any) -> list[Zone]:
    """يقرأ zones مقطع من جدول zones."""
    rows = db.fetch_all(
        "SELECT zone_type, polygon, metadata FROM zones WHERE video_id = ?",
        (video_id,),
    )
    out: list[Zone] = []
    for r in rows:
        # تحليل دفاعي: صف zones تالف لا يجب أن يُسقط استخراج المخالفات كله
        out.append(
            Zone(
                zone_type=str(r[0]),
                polygon=parse_polygon_json(r[1]),
                metadata=parse_metadata_json(r[2]),
            )
        )
    return out


__all__ = [
    "BaseViolationDetector",
    "Track",
    "ViolationCandidate",
    "Zone",
    "bbox_above",
    "build_tracks",
    "consecutive_runs",
    "detections_by_frame",
    "first_crossing_frame",
    "load_zones_from_db",
]
