"""محرك المخالفات — تشغيل الكواشف وتجميع نتائجها.

الكواشف نفسها تعيش في `app/core/detectors/`، وأنواعها المشتركة في
`app/core/violations.py`. هذا الملف هو **الواجهة والـpipeline** فقط، ويُعيد
تصدير كل ما سبق حفاظاً على توافق الاستيرادات القائمة (`from app.core.rules
import ...`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.analyzer import Detection
from app.core.detectors.illegal_overtaking import IllegalOvertakingDetector
from app.core.detectors.illegal_parking import IllegalParkingDetector
from app.core.detectors.no_helmet import NoHelmetDetector
from app.core.detectors.red_light import RedLightDetector
from app.core.detectors.speeding import SpeedingDetector
from app.core.detectors.wrong_direction import WrongDirectionDetector
from app.core.violations import (
    BaseViolationDetector,
    Track,
    ViolationCandidate,
    Zone,
    bbox_above,
    build_tracks,
    consecutive_runs,
    detections_by_frame,
    first_crossing_frame,
    load_zones_from_db,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectorRunResult:
    """ناتج تشغيل مجموعة كواشف — المخالفات **والإخفاقات**.

    إرجاع الإخفاقات صراحةً بدل ابتلاعها في السجل يسمح للواجهة بإخبار المستخدم
    لماذا خرج بـ«0 مخالفة» بدل تركه يظن أن التطبيق معطّل.
    """

    candidates: list[ViolationCandidate] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


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
) -> DetectorRunResult:
    """يُشغّل كل الكواشف ويُرجع المخالفات مع أسماء الكواشف التي فشلت."""
    detectors = detectors or all_default_detectors()
    tracks = build_tracks(detections)
    by_frame = detections_by_frame(detections)
    out: list[ViolationCandidate] = []
    failures: list[str] = []
    for detector in detectors:
        name = detector.__class__.__name__
        try:
            out.extend(detector.detect(tracks, by_frame, zones, fps))
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل الكاشف %s: %s", name, exc)
            failures.append(f"{name}: {exc}")
    return DetectorRunResult(candidates=out, failures=failures)


__all__ = [
    "BaseViolationDetector",
    "DetectorRunResult",
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
    "bbox_above",
    "build_tracks",
    "consecutive_runs",
    "detections_by_frame",
    "first_crossing_frame",
    "load_zones_from_db",
    "run_detectors",
]
