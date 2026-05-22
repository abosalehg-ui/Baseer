"""خدمة الداشبورد — KPIs وتجميعات المخالفات للعرض والتصدير."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from app.constants import VIOLATION_ARABIC_NAMES, ReviewStatus, ViolationType
from app.core.db import Database, get_database

logger = logging.getLogger(__name__)


# ============================================
# هياكل البيانات
# ============================================
@dataclass(frozen=True)
class DashboardKPIs:
    """مؤشرات الأداء الرئيسية."""

    total_videos: int
    total_violations: int
    avg_violations_per_video: float
    sources_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ViolationRow:
    """صف مخالفة مُعدّ للعرض/التصدير."""

    id: int
    video_id: int
    video_filename: str
    violation_type: str
    violation_type_ar: str
    start_ms: int
    end_ms: int
    confidence: float
    license_plate: str | None
    review_status: str
    notes: str | None
    created_at: datetime | None


# ============================================
# خدمة الداشبورد
# ============================================
class DashboardService:
    """تجميعات وقراءات للداشبورد."""

    def __init__(self, *, db: Database | None = None) -> None:
        self._db = db or get_database()

    # ============================================
    # KPIs
    # ============================================
    def get_kpis(self) -> DashboardKPIs:
        total_videos = int(self._db.fetch_one("SELECT COUNT(*) FROM videos")[0])
        total_violations = int(self._db.fetch_one("SELECT COUNT(*) FROM violations")[0])
        avg = total_violations / total_videos if total_videos else 0.0

        source_rows = self._db.fetch_all(
            "SELECT COALESCE(source_type, 'other'), COUNT(*) FROM videos " "GROUP BY source_type"
        )
        sources = {str(r[0]): int(r[1]) for r in source_rows}

        return DashboardKPIs(
            total_videos=total_videos,
            total_violations=total_violations,
            avg_violations_per_video=avg,
            sources_breakdown=sources,
        )

    # ============================================
    # تجميعات
    # ============================================
    def violations_by_type(self) -> list[tuple[str, int]]:
        """يُرجع (violation_type, count) مرتباً نزولياً."""
        rows = self._db.fetch_all(
            "SELECT violation_type, COUNT(*) FROM violations "
            "GROUP BY violation_type ORDER BY COUNT(*) DESC"
        )
        return [(str(r[0]), int(r[1])) for r in rows]

    def violations_by_review_status(self) -> dict[str, int]:
        """عدد المخالفات لكل حالة مراجعة."""
        rows = self._db.fetch_all(
            "SELECT review_status, COUNT(*) FROM violations GROUP BY review_status"
        )
        return {str(r[0]): int(r[1]) for r in rows}

    def violations_by_hour(self) -> list[tuple[int, int]]:
        """يُرجع (hour 0-23, count) باستخدام recorded_at من المقطع."""
        rows = self._db.fetch_all(
            "SELECT EXTRACT(hour FROM v.recorded_at)::INTEGER, COUNT(vi.id) "
            "FROM violations vi JOIN videos v ON vi.video_id = v.id "
            "WHERE v.recorded_at IS NOT NULL "
            "GROUP BY 1 ORDER BY 1"
        )
        return [(int(r[0]), int(r[1])) for r in rows]

    def violations_by_weekday(self) -> list[tuple[int, int]]:
        """يُرجع (weekday 0=Mon..6=Sun, count)."""
        rows = self._db.fetch_all(
            "SELECT (EXTRACT(dow FROM v.recorded_at)::INTEGER + 6) % 7, COUNT(vi.id) "
            "FROM violations vi JOIN videos v ON vi.video_id = v.id "
            "WHERE v.recorded_at IS NOT NULL "
            "GROUP BY 1 ORDER BY 1"
        )
        return [(int(r[0]), int(r[1])) for r in rows]

    def violations_heatmap(self) -> dict[tuple[int, int], int]:
        """خريطة حرارية {(weekday, hour): count}."""
        rows = self._db.fetch_all(
            "SELECT (EXTRACT(dow FROM v.recorded_at)::INTEGER + 6) % 7, "
            "EXTRACT(hour FROM v.recorded_at)::INTEGER, COUNT(vi.id) "
            "FROM violations vi JOIN videos v ON vi.video_id = v.id "
            "WHERE v.recorded_at IS NOT NULL "
            "GROUP BY 1, 2"
        )
        return {(int(r[0]), int(r[1])): int(r[2]) for r in rows}

    def violations_over_time(self) -> list[tuple[date, int]]:
        """عدد المخالفات لكل يوم."""
        rows = self._db.fetch_all(
            "SELECT DATE(v.recorded_at), COUNT(vi.id) "
            "FROM violations vi JOIN videos v ON vi.video_id = v.id "
            "WHERE v.recorded_at IS NOT NULL "
            "GROUP BY 1 ORDER BY 1"
        )
        out: list[tuple[date, int]] = []
        for r in rows:
            d_value = r[0]
            if isinstance(d_value, datetime):
                d_value = d_value.date()
            out.append((d_value, int(r[1])))
        return out

    # ============================================
    # قائمة المخالفات
    # ============================================
    def list_violations(
        self,
        *,
        violation_type: str | None = None,
        review_status: str | None = None,
        video_id: int | None = None,
        limit: int | None = None,
    ) -> list[ViolationRow]:
        """يُرجع قائمة المخالفات مع فلاتر اختيارية."""
        sql = (
            "SELECT vi.id, vi.video_id, v.filename, vi.violation_type, "
            "vi.start_ms, vi.end_ms, vi.confidence, vi.license_plate, "
            "vi.review_status, vi.notes, vi.created_at "
            "FROM violations vi JOIN videos v ON vi.video_id = v.id"
        )
        clauses: list[str] = []
        params: list = []
        if violation_type:
            clauses.append("vi.violation_type = ?")
            params.append(violation_type)
        if review_status:
            clauses.append("vi.review_status = ?")
            params.append(review_status)
        if video_id is not None:
            clauses.append("vi.video_id = ?")
            params.append(video_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY vi.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._db.fetch_all(sql, tuple(params) if params else None)
        return [self._row_to_violation(r) for r in rows]

    @staticmethod
    def _row_to_violation(r: tuple) -> ViolationRow:
        vtype = str(r[3])
        try:
            ar = VIOLATION_ARABIC_NAMES[ViolationType(vtype)]
        except (KeyError, ValueError):
            ar = vtype
        return ViolationRow(
            id=int(r[0]),
            video_id=int(r[1]),
            video_filename=str(r[2]),
            violation_type=vtype,
            violation_type_ar=ar,
            start_ms=int(r[4]),
            end_ms=int(r[5]),
            confidence=float(r[6]),
            license_plate=str(r[7]) if r[7] else None,
            review_status=str(r[8]),
            notes=str(r[9]) if r[9] else None,
            created_at=r[10] if isinstance(r[10], datetime) else None,
        )

    # ============================================
    # تحديث المراجعة
    # ============================================
    def update_review_status(self, violation_id: int, status: ReviewStatus | str) -> None:
        """يُحدّث حالة مراجعة مخالفة."""
        value = status.value if isinstance(status, ReviewStatus) else status
        self._db.execute(
            "UPDATE violations SET review_status = ?, reviewed_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (value, violation_id),
        )


__all__ = ["DashboardKPIs", "DashboardService", "ViolationRow"]
