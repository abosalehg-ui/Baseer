"""خدمة إدارة المناطق (Zones) — حفظ/قراءة/حذف مناطق المقاطع في DB.

الـ Zones (stop_line، no_parking، lane_line_solid…) شرطٌ لتشغيل عدة كواشف
(الإشارة الحمراء، الوقوف الخاطئ، التجاوز). هذه الخدمة توفّر نقطة دخول برمجية
لإنشائها بدل كتابة SQL خام، وتُغذّي `scripts/define_zones.py` وأي واجهة مستقبلية.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.core.db import Database, get_database
from app.utils.geometry import Point

logger = logging.getLogger(__name__)

# أنواع المناطق المدعومة (تطابق ما تفحصه الكواشف في rules.py/detectors)
ZONE_TYPES: tuple[str, ...] = (
    "stop_line",
    "no_parking",
    "lane_line_solid",
    "lane_line_dashed",
)


@dataclass(frozen=True)
class ZoneRecord:
    """منطقة مخزَّنة (صف من جدول zones)."""

    id: int
    video_id: int
    zone_type: str
    polygon: list[Point]
    metadata: dict | None = None


class ZoneService:
    """يدير مناطق المقاطع في قاعدة البيانات."""

    def __init__(self, *, db: Database | None = None) -> None:
        self._db = db or get_database()

    def add_zone(
        self,
        video_id: int,
        zone_type: str,
        polygon: list[Point],
        *,
        metadata: dict | None = None,
    ) -> int:
        """يُضيف منطقة لمقطع ويعيد معرّفها.

        Args:
            video_id: معرّف المقطع.
            zone_type: أحد `ZONE_TYPES`.
            polygon: قائمة نقاط (x, y). خطوط التوقف/المسار تحتاج نقطتين على الأقل،
                والمناطق المغلقة (no_parking) تحتاج ثلاث نقاط على الأقل.
            metadata: بيانات إضافية اختيارية.
        """
        if zone_type not in ZONE_TYPES:
            raise ValueError(f"نوع منطقة غير مدعوم: {zone_type} — المدعوم: {ZONE_TYPES}")
        min_points = 3 if zone_type == "no_parking" else 2
        if len(polygon) < min_points:
            raise ValueError(
                f"النوع '{zone_type}' يحتاج {min_points} نقاط على الأقل، الحالي: {len(polygon)}"
            )
        normalized = [(float(x), float(y)) for x, y in polygon]
        self._db.execute(
            "INSERT INTO zones (video_id, zone_type, polygon, metadata) VALUES (?, ?, ?, ?)",
            (
                video_id,
                zone_type,
                json.dumps(normalized),
                json.dumps(metadata) if metadata is not None else None,
            ),
        )
        logger.info("أُضيفت منطقة %s للمقطع %d (%d نقاط)", zone_type, video_id, len(normalized))
        row = self._db.fetch_one(
            "SELECT id FROM zones WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,)
        )
        assert row is not None
        return int(row[0])

    def list_zones(self, video_id: int) -> list[ZoneRecord]:
        """يُرجع كل مناطق مقطع."""
        rows = self._db.fetch_all(
            "SELECT id, video_id, zone_type, polygon, metadata FROM zones "
            "WHERE video_id = ? ORDER BY id",
            (video_id,),
        )
        out: list[ZoneRecord] = []
        for r in rows:
            polygon = [(float(p[0]), float(p[1])) for p in (json.loads(r[3]) if r[3] else [])]
            metadata = json.loads(r[4]) if r[4] else None
            out.append(
                ZoneRecord(
                    id=int(r[0]),
                    video_id=int(r[1]),
                    zone_type=str(r[2]),
                    polygon=polygon,
                    metadata=metadata,
                )
            )
        return out

    def delete_zone(self, zone_id: int) -> None:
        """يحذف منطقة واحدة بمعرّفها."""
        self._db.execute("DELETE FROM zones WHERE id = ?", (zone_id,))

    def clear_zones(self, video_id: int) -> None:
        """يحذف كل مناطق مقطع."""
        self._db.execute("DELETE FROM zones WHERE video_id = ?", (video_id,))


__all__ = ["ZONE_TYPES", "ZoneRecord", "ZoneService"]
