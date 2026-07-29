"""خدمة الداشبورد — KPIs وتجميعات المخالفات للعرض والتصدير."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.constants import VIOLATION_ARABIC_NAMES, ReviewStatus, ViolationType
from app.core.db import Database, current_actor, get_database

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
        videos_row = self._db.fetch_one("SELECT COUNT(*) FROM videos")
        violations_row = self._db.fetch_one("SELECT COUNT(*) FROM violations")
        total_videos = int(videos_row[0]) if videos_row else 0
        total_violations = int(violations_row[0]) if violations_row else 0
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
        clauses, params = self._filter_clauses(violation_type, review_status, video_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY vi.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = self._db.fetch_all(sql, tuple(params) if params else None)
        return [self._row_to_violation(r) for r in rows]

    @staticmethod
    def _filter_clauses(
        violation_type: str | None,
        review_status: str | None,
        video_id: int | None,
    ) -> tuple[list[str], list[Any]]:
        """يبني شروط WHERE المشتركة بين `list_violations` و`count_violations`."""
        clauses: list[str] = []
        params: list[Any] = []
        if violation_type:
            clauses.append("vi.violation_type = ?")
            params.append(violation_type)
        if review_status:
            clauses.append("vi.review_status = ?")
            params.append(review_status)
        if video_id is not None:
            clauses.append("vi.video_id = ?")
            params.append(video_id)
        return clauses, params

    @staticmethod
    def _row_to_violation(r: tuple[Any, ...]) -> ViolationRow:
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
        """يُحدّث حالة مراجعة مخالفة ويسجّل التغيير في سجل التدقيق."""
        value = status.value if isinstance(status, ReviewStatus) else status
        previous = self._db.fetch_one(
            "SELECT review_status FROM violations WHERE id = ?", (violation_id,)
        )
        self._db.execute(
            "UPDATE violations SET review_status = ?, reviewed_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (value, violation_id),
        )
        # الكتابة فوق الحالة السابقة بلا أثر كانت تعني ضياع «من غيّر ماذا ومتى»
        self._db.record_audit(
            entity="violation",
            entity_id=violation_id,
            action="review_status",
            old_value=str(previous[0]) if previous and previous[0] is not None else None,
            new_value=value,
        )

    def count_violations(
        self,
        *,
        violation_type: str | None = None,
        review_status: str | None = None,
        video_id: int | None = None,
    ) -> int:
        """عدد المخالفات المطابقة للفلاتر — لعرض «س من ص» بدل بتر صامت."""
        sql = "SELECT COUNT(*) FROM violations vi"
        clauses, params = self._filter_clauses(violation_type, review_status, video_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        row = self._db.fetch_one(sql, tuple(params) if params else None)
        return int(row[0]) if row else 0

    def list_violations_for_editing(self, *, limit: int = 500) -> list[tuple[Any, ...]]:
        """صفوف المخالفات لجدول التحرير في تبويب التحليل (مع المصدر والملاحظات)."""
        return self._db.fetch_all(
            "SELECT vi.id, v.filename, vi.violation_type, vi.start_ms, vi.end_ms, "
            "COALESCE(vi.license_plate, ''), COALESCE(vi.source, 'auto'), COALESCE(vi.notes, '') "
            "FROM violations vi LEFT JOIN videos v ON v.id = vi.video_id "
            f"ORDER BY vi.id DESC LIMIT {int(limit)}"
        )

    def get_violation_for_edit(self, violation_id: int) -> dict[str, Any] | None:
        """الحقول القابلة للتعديل لمخالفة واحدة، أو None لو غير موجودة."""
        row = self._db.fetch_one(
            "SELECT id, video_id, violation_type, start_ms, end_ms, license_plate, notes "
            "FROM violations WHERE id = ?",
            (violation_id,),
        )
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "video_id": int(row[1]),
            "violation_type": str(row[2]),
            "start_ms": int(row[3] or 0),
            "end_ms": int(row[4] or 0),
            "license_plate": row[5],
            "notes": row[6],
        }

    def insert_manual_violation(
        self,
        *,
        video_id: int,
        violation_type: str,
        start_ms: int,
        end_ms: int,
        evidence_frames_json: str,
        license_plate: str | None,
        notes: str,
    ) -> None:
        """يُدرج مخالفة يدوية (`source='manual'`) ويسجّلها في التدقيق.

        `source='manual'` يحميها من الحذف عند إعادة التحليل
        (`DELETE ... AND source='auto'`).
        """
        actor = current_actor()
        self._db.execute(
            """
            INSERT INTO violations (
                video_id, violation_type, start_ms, end_ms,
                confidence, evidence_frames, license_plate,
                review_status, notes, source, manual_user
            ) VALUES (?, ?, ?, ?, 1.0, ?, ?, 'confirmed', ?, 'manual', ?)
            """,
            (
                video_id,
                violation_type,
                start_ms,
                end_ms,
                evidence_frames_json,
                license_plate,
                notes,
                actor,
            ),
        )
        self._db.record_audit(
            entity="violation",
            entity_id=None,
            action="create_manual",
            new_value=f"{violation_type} @ video {video_id}",
            actor=actor,
        )

    def update_violation_as_manual(
        self,
        violation_id: int,
        *,
        video_id: int,
        violation_type: str,
        start_ms: int,
        end_ms: int,
        evidence_frames_json: str,
        license_plate: str | None,
        notes: str,
    ) -> None:
        """يُحدّث مخالفة ويحوّلها إلى `source='manual'` مع أثر تدقيق.

        التحويل مقصود: تعديل بشري يجب ألا يُمحى عند إعادة التحليل التلقائي.
        الواجهة تُعلم المستخدم بهذا صراحةً قبل الحفظ.
        """
        actor = current_actor()
        previous = self._db.fetch_one(
            "SELECT violation_type, source FROM violations WHERE id = ?", (violation_id,)
        )
        self._db.execute(
            """
            UPDATE violations SET
                video_id = ?, violation_type = ?, start_ms = ?, end_ms = ?,
                evidence_frames = ?, license_plate = ?, notes = ?,
                source = 'manual', manual_user = ?
            WHERE id = ?
            """,
            (
                video_id,
                violation_type,
                start_ms,
                end_ms,
                evidence_frames_json,
                license_plate,
                notes,
                actor,
                violation_id,
            ),
        )
        self._db.record_audit(
            entity="violation",
            entity_id=violation_id,
            action="edit",
            old_value=f"{previous[0]} (source={previous[1]})" if previous else None,
            new_value=f"{violation_type} (source=manual)",
            actor=actor,
        )

    def record_export_entry(
        self,
        *,
        study_name: str,
        fmt: str,
        output_path: Path,
        filter_json: str | None = None,
    ) -> None:
        """يسجّل عملية تصدير في جدول `exports` (بدل تمرير `_db` من الواجهة)."""
        from app.core.exporter import record_export

        record_export(
            self._db,
            study_name=study_name,
            fmt=fmt,
            output_path=output_path,
            filter_json=filter_json,
        )

    def delete_violation(self, violation_id: int) -> None:
        """يحذف مخالفة ويسجّل الحذف في سجل التدقيق."""
        previous = self._db.fetch_one(
            "SELECT violation_type, source FROM violations WHERE id = ?", (violation_id,)
        )
        self._db.execute("DELETE FROM violations WHERE id = ?", (violation_id,))
        self._db.record_audit(
            entity="violation",
            entity_id=violation_id,
            action="delete",
            old_value=f"{previous[0]} (source={previous[1]})" if previous else None,
        )


__all__ = ["DashboardKPIs", "DashboardService", "ViolationRow"]
