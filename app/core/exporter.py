"""تصدير الدراسات بصيغ متعددة (JSON, CSV, Excel, PDF عربي)."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.constants import SOURCE_ARABIC_NAMES, VIOLATION_ARABIC_NAMES, SourceType, ViolationType
from app.core.dashboard import DashboardService, ViolationRow

logger = logging.getLogger(__name__)


# ============================================
# تجميع دراسة كاملة
# ============================================
def build_study(service: DashboardService) -> dict:
    """يجمع كل بيانات الدراسة في dict واحد قابل للتسلسل."""
    kpis = service.get_kpis()
    return {
        "generated_at": datetime.now().isoformat(),
        "kpis": asdict(kpis),
        "violations": [asdict(v) for v in service.list_violations()],
        "by_type": service.violations_by_type(),
        "by_hour": service.violations_by_hour(),
        "by_weekday": service.violations_by_weekday(),
        "by_review_status": service.violations_by_review_status(),
    }


# ============================================
# JSON
# ============================================
def export_json(study: dict, output_path: Path | str) -> Path:
    """يكتب الدراسة كـ JSON بدعم عربي كامل."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(study, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return out


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


# ============================================
# CSV
# ============================================
CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "video_id",
    "video_filename",
    "violation_type",
    "violation_type_ar",
    "start_ms",
    "end_ms",
    "confidence",
    "license_plate",
    "review_status",
    "notes",
)


def export_csv(violations: list[ViolationRow], output_path: Path | str) -> Path:
    """يصدّر قائمة المخالفات كـ CSV."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for v in violations:
            row = {col: getattr(v, col, "") for col in CSV_COLUMNS}
            writer.writerow(row)
    return out


# ============================================
# Excel (لو openpyxl متاح)
# ============================================
def export_excel(
    study: dict,
    violations: list[ViolationRow],
    output_path: Path | str,
) -> Path:
    """يصدّر الدراسة كـ Excel متعدد الـ sheets."""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("يحتاج openpyxl — ثبّت requirements.txt") from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # Summary sheet
    summary = wb.active
    summary.title = "الملخص"
    kpis = study.get("kpis", {})
    summary.append(["مؤشر", "القيمة"])
    summary.append(["إجمالي المقاطع", kpis.get("total_videos", 0)])
    summary.append(["إجمالي المخالفات", kpis.get("total_violations", 0)])
    summary.append(["متوسط مخالفات/مقطع", round(kpis.get("avg_violations_per_video", 0.0), 2)])
    summary.append([])
    summary.append(["المصدر", "عدد المقاطع"])
    for src, count in (kpis.get("sources_breakdown") or {}).items():
        ar = _source_arabic_name(src)
        summary.append([ar, count])

    # By type sheet
    by_type_sheet = wb.create_sheet("حسب النوع")
    by_type_sheet.append(["النوع (الكود)", "النوع (عربي)", "العدد"])
    for vtype, count in study.get("by_type", []):
        by_type_sheet.append([vtype, _violation_arabic_name(vtype), count])

    # By hour sheet
    by_hour_sheet = wb.create_sheet("حسب الساعة")
    by_hour_sheet.append(["الساعة", "عدد المخالفات"])
    for hour, count in study.get("by_hour", []):
        by_hour_sheet.append([hour, count])

    # Details sheet
    details = wb.create_sheet("التفاصيل")
    details.append(list(CSV_COLUMNS))
    for v in violations:
        details.append([getattr(v, col, "") for col in CSV_COLUMNS])

    wb.save(out)
    return out


# ============================================
# PDF عربي (reportlab + arabic-reshaper + bidi)
# ============================================
def export_pdf(
    study: dict,
    violations: list[ViolationRow],
    output_path: Path | str,
    *,
    title: str = "تقرير بَصير — تحليل المخالفات المرورية",
) -> Path:
    """يُصدّر تقرير PDF عربي RTL مع الرسوم الأساسية كجداول."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError("يحتاج reportlab — ثبّت requirements.txt") from exc

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Baseer Study",
    )

    styles = getSampleStyleSheet()
    rtl_style = ParagraphStyle(
        "rtl",
        parent=styles["Normal"],
        alignment=2,  # right
        fontName=styles["Normal"].fontName,
        fontSize=11,
        leading=16,
    )
    title_style = ParagraphStyle(
        "rtl_title",
        parent=styles["Heading1"],
        alignment=2,
        fontSize=18,
        leading=22,
    )

    story: list = [Paragraph(_shape(title), title_style), Spacer(1, 12)]

    kpis = study.get("kpis", {})
    story.append(Paragraph(_shape("المؤشرات الرئيسية"), rtl_style))
    story.append(_kpi_table(kpis))
    story.append(Spacer(1, 12))

    story.append(Paragraph(_shape("المخالفات حسب النوع"), rtl_style))
    story.append(_by_type_table(study.get("by_type", [])))
    story.append(Spacer(1, 12))

    if violations:
        story.append(Paragraph(_shape("أحدث المخالفات (آخر 30)"), rtl_style))
        story.append(_violations_table(violations[:30]))

    doc.build(story)
    return out


def _kpi_table(kpis: dict) -> object:
    from reportlab.lib import colors
    from reportlab.platypus import Table

    data = [
        [_shape("المؤشر"), _shape("القيمة")],
        [_shape("إجمالي المقاطع"), str(kpis.get("total_videos", 0))],
        [_shape("إجمالي المخالفات"), str(kpis.get("total_violations", 0))],
        [_shape("متوسط مخالفات/مقطع"), f"{kpis.get('avg_violations_per_video', 0.0):.2f}"],
    ]
    table = Table(data, colWidths=[8, 4], hAlign="RIGHT")
    table.setStyle(_default_table_style(colors))
    return table


def _by_type_table(by_type: list) -> object:
    from reportlab.lib import colors
    from reportlab.platypus import Table

    data = [[_shape("النوع"), _shape("العدد")]]
    for vtype, count in by_type:
        data.append([_shape(_violation_arabic_name(vtype)), str(count)])
    table = Table(data, colWidths=[10, 3], hAlign="RIGHT")
    table.setStyle(_default_table_style(colors))
    return table


def _violations_table(violations: list[ViolationRow]) -> object:
    from reportlab.lib import colors
    from reportlab.platypus import Table

    data = [
        [
            _shape("الملف"),
            _shape("النوع"),
            _shape("الثقة"),
            _shape("الحالة"),
        ]
    ]
    for v in violations:
        data.append(
            [
                _shape(v.video_filename),
                _shape(v.violation_type_ar),
                f"{v.confidence:.2f}",
                _shape(v.review_status),
            ]
        )
    table = Table(data, colWidths=[6, 4, 2, 3], hAlign="RIGHT")
    table.setStyle(_default_table_style(colors))
    return table


def _default_table_style(colors_module) -> object:
    from reportlab.platypus import TableStyle

    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors_module.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors_module.white),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors_module.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ]
    )


def _shape(text: str) -> str:
    """يُعيد تشكيل النص العربي للعرض الصحيح في PDF."""
    if not text:
        return ""
    try:
        from app.utils.arabic_utils import shape_for_pdf

        return shape_for_pdf(text)
    except Exception:  # noqa: BLE001
        return text


def _violation_arabic_name(vtype: str) -> str:
    try:
        return VIOLATION_ARABIC_NAMES[ViolationType(vtype)]
    except (KeyError, ValueError):
        return vtype


def _source_arabic_name(source: str) -> str:
    try:
        return SOURCE_ARABIC_NAMES[SourceType(source)]
    except (KeyError, ValueError):
        return source


# ============================================
# تسجيل التصدير في DB
# ============================================
def record_export(
    db,
    *,
    study_name: str,
    fmt: str,
    output_path: Path,
    filter_json: str | None = None,
) -> None:
    """يُسجّل تصديراً في جدول exports."""
    db.execute(
        "INSERT INTO exports (study_name, filter_json, format, output_path) " "VALUES (?, ?, ?, ?)",
        (study_name, filter_json, fmt, str(output_path)),
    )


__all__ = [
    "build_study",
    "export_csv",
    "export_excel",
    "export_json",
    "export_pdf",
    "record_export",
]
