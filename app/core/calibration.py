"""معايرة الكاميرا — تحويل الإزاحة بالبكسل إلى متر/سرعة."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.core.db import Database, get_database
from app.utils.geometry import Point, euclidean_distance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Calibration:
    """معايرة كاميرا واحدة."""

    video_id: int
    meters_per_px: float
    reference_pts: list[Point]


def compute_meters_per_px(
    image_points: list[Point],
    real_distances_m: list[float],
) -> float:
    """يحسب meters_per_px من نقاط مرجعية + مسافاتها الحقيقية.

    يأخذ متوسط نسبة (مسافة حقيقية / مسافة بكسل) عبر كل أزواج النقاط.
    """
    if len(image_points) < 2:
        raise ValueError("تحتاج نقطتين على الأقل")
    if len(real_distances_m) != len(image_points) - 1:
        raise ValueError("عدد المسافات الحقيقية يجب أن يساوي عدد النقاط ناقص واحد")
    if any(d <= 0 for d in real_distances_m):
        raise ValueError("كل المسافات الحقيقية يجب أن تكون موجبة")

    ratios: list[float] = []
    for i, real in enumerate(real_distances_m):
        pixel = euclidean_distance(image_points[i], image_points[i + 1])
        if pixel <= 0:
            raise ValueError(f"المسافة بالبكسل صفر بين النقطتين {i} و {i + 1}")
        ratios.append(real / pixel)

    return sum(ratios) / len(ratios)


def estimate_speed_kmh(
    displacement_px: float,
    dt_seconds: float,
    meters_per_px: float,
) -> float:
    """يقدّر السرعة بـ كم/ساعة من إزاحة بكسلية وزمن."""
    if dt_seconds <= 0:
        return 0.0
    meters = displacement_px * meters_per_px
    return (meters / dt_seconds) * 3.6


def estimate_track_speed_kmh(
    points_with_timestamps: list[tuple[Point, float]],
    meters_per_px: float,
) -> float:
    """يقدّر متوسط السرعة لـ track من سلسلة (نقطة، ts بالثواني)."""
    if len(points_with_timestamps) < 2:
        return 0.0
    points = [p for p, _ in points_with_timestamps]
    ts = [t for _, t in points_with_timestamps]
    total_px = sum(euclidean_distance(points[i], points[i + 1]) for i in range(len(points) - 1))
    duration = ts[-1] - ts[0]
    return estimate_speed_kmh(total_px, duration, meters_per_px)


# ============================================
# خدمة المعايرة (DB)
# ============================================
class CalibrationService:
    """يدير معايرات الكاميرات في DB."""

    def __init__(self, *, db: Database | None = None) -> None:
        self._db = db or get_database()

    def save_calibration(
        self,
        video_id: int,
        image_points: list[Point],
        real_distances_m: list[float],
    ) -> Calibration:
        """يحسب المعايرة ويحفظها في الـ DB."""
        mpp = compute_meters_per_px(image_points, real_distances_m)
        self._db.execute("DELETE FROM calibrations WHERE video_id = ?", (video_id,))
        self._db.execute(
            """
            INSERT INTO calibrations (video_id, reference_pts, meters_per_px)
            VALUES (?, ?, ?)
            """,
            (video_id, json.dumps(image_points), mpp),
        )
        logger.info("حُفظت معايرة المقطع %d — meters_per_px=%.5f", video_id, mpp)
        return Calibration(video_id=video_id, meters_per_px=mpp, reference_pts=image_points)

    def get_calibration(self, video_id: int) -> Calibration | None:
        """يجلب معايرة مقطع، أو None لو غير موجودة."""
        row = self._db.fetch_one(
            "SELECT video_id, meters_per_px, reference_pts " "FROM calibrations WHERE video_id = ?",
            (video_id,),
        )
        if row is None:
            return None
        pts = json.loads(row[2]) if row[2] else []
        return Calibration(
            video_id=int(row[0]),
            meters_per_px=float(row[1]),
            reference_pts=[(float(p[0]), float(p[1])) for p in pts],
        )

    def delete_calibration(self, video_id: int) -> None:
        self._db.execute("DELETE FROM calibrations WHERE video_id = ?", (video_id,))


__all__ = [
    "Calibration",
    "CalibrationService",
    "compute_meters_per_px",
    "estimate_speed_kmh",
    "estimate_track_speed_kmh",
]
