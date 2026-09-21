"""جاهزية المقاطع لاستخراج المخالفات — أي متطلبات الكواشف متوفرة.

مفصولة عن `analyzer.py` لسببين: الملف كان على حدّ الأسطر المُعلَن في
`docs/architecture.md`، وحساب الجاهزية منطق قراءة مستقل عن الاستدلال نفسه.
`analyzer` يُعيد تصدير `VideoReadiness` فالاستيرادات القائمة تبقى صالحة.

**لماذا نسخة مجمَّعة (`readiness_bulk`)؟** النسخة المفردة تُنفّذ خمس عمليات I/O
لكل مقطع (مناطق + معايرة + عدّ الكشوفات المتعقَّبة + عدّ الكشوفات + وجود الملف
على القرص). `analysis_view.refresh()` كان يستدعيها في حلقة على كل صف وفي
الـmain thread، فمكتبة 500 مقطع = ~2500 استعلام + 500 stat عند كل تحديث —
وتُكرَّر كاملة في `_explain_zero_violations`. المجمَّعة تُنفّذ أربعة استعلامات
`GROUP BY` لكل الدفعة.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["VideoReadiness", "readiness_bulk", "readiness_for"]


@dataclass(frozen=True)
class VideoReadiness:
    """جاهزية مقطع لاستخراج المخالفات — أي متطلبات الكواشف متوفرة.

    الكواشف تعود مبكراً بصمت عند غياب متطلبها، فهذا الملخّص يجعل السبب مرئياً
    في الواجهة قبل أن يضغط المستخدم «استخراج» ويحصل على صفر بلا تفسير.
    """

    video_id: int
    has_detections: bool
    has_tracks: bool
    zone_types: set[str] = field(default_factory=set)
    has_calibration: bool = False
    has_video_file: bool = False

    @property
    def blocked_detectors(self) -> list[str]:
        """أسماء الكواشف المعطّلة عربياً مع سبب التعطيل."""
        out: list[str] = []
        if not self.has_tracks:
            out.append("كل الكواشف (لا توجد tracks — فعّل التتبّع عند الاستدلال)")
            return out
        if "stop_line" not in self.zone_types:
            out.append("قطع الإشارة الحمراء (تحتاج منطقة stop_line)")
        if "no_parking" not in self.zone_types:
            out.append("الوقوف الخاطئ (تحتاج منطقة no_parking)")
        if "lane_line_solid" not in self.zone_types:
            out.append("التجاوز الخاطئ (يحتاج خط lane_line_solid)")
        if not self.has_calibration:
            out.append("السرعة الزائدة والمسافة الآمنة (تحتاجان معايرة)")
        if not self.has_video_file:
            out.append("إساءة أنوار التلاقي (تحتاج ملف الفيديو)")
        return out

    @property
    def summary(self) -> str:
        """سطر مختصر للعرض في عمود «الجاهزية»."""
        marks = [
            f"tracks: {'✓' if self.has_tracks else '✗'}",
            f"مناطق: {len(self.zone_types)}",
            f"معايرة: {'✓' if self.has_calibration else '✗'}",
        ]
        return " • ".join(marks)


def readiness_for(db: Any, video_id: int) -> VideoReadiness:
    """جاهزية مقطع واحد."""
    return readiness_bulk(db, [video_id])[video_id]


def readiness_bulk(db: Any, video_ids: list[int]) -> dict[int, VideoReadiness]:
    """جاهزية دفعة مقاطع بأربعة استعلامات مجمَّعة بدل خمسة لكل مقطع.

    المقطع غير الموجود في القاعدة يعود بجاهزية صفرية (لا استثناء) حتى لا يُسقط
    صفٌّ محذوف بناء الجدول كله.
    """
    if not video_ids:
        return {}
    unique_ids = sorted(set(video_ids))
    placeholders = ", ".join("?" for _ in unique_ids)
    params = tuple(unique_ids)

    zone_types: dict[int, set[str]] = {}
    for vid, ztype in db.fetch_all(
        f"SELECT DISTINCT video_id, zone_type FROM zones WHERE video_id IN ({placeholders})",
        params,
    ):
        zone_types.setdefault(int(vid), set()).add(str(ztype))

    calibrated = {
        int(r[0])
        for r in db.fetch_all(
            "SELECT video_id FROM calibrations "
            f"WHERE video_id IN ({placeholders}) AND meters_per_px > 0",
            params,
        )
    }

    counts: dict[int, tuple[int, int]] = {}
    for vid, total, tracked in db.fetch_all(
        "SELECT video_id, COUNT(*), COUNT(track_id) FROM detections "
        f"WHERE video_id IN ({placeholders}) GROUP BY video_id",
        params,
    ):
        counts[int(vid)] = (int(total), int(tracked))

    filepaths = {
        int(r[0]): str(r[1]) if r[1] else ""
        for r in db.fetch_all(
            f"SELECT id, filepath FROM videos WHERE id IN ({placeholders})", params
        )
    }

    out: dict[int, VideoReadiness] = {}
    for vid in unique_ids:
        total, tracked = counts.get(vid, (0, 0))
        filepath = filepaths.get(vid, "")
        out[vid] = VideoReadiness(
            video_id=vid,
            has_detections=total > 0,
            has_tracks=tracked > 0,
            zone_types=zone_types.get(vid, set()),
            has_calibration=vid in calibrated,
            has_video_file=bool(filepath) and Path(filepath).exists(),
        )
    return out
