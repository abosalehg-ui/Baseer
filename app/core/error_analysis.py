"""تحليل أخطاء النموذج — تحديد الـ classes الضعيفة وتوصيات التحسين."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.constants import DETECTION_CLASSES
from app.core.dataset import ClassStats
from app.core.trainer import EvalReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeakClass:
    """class ضعيف يحتاج تحسين."""

    class_name: str
    map50: float
    threshold: float
    instances: int | None = None
    images: int | None = None
    reasons: tuple[str, ...] = ()


@dataclass
class ErrorAnalysisReport:
    """تقرير شامل عن نقاط ضعف النموذج."""

    threshold: float
    overall_map50: float
    overall_map: float
    weak_classes: list[WeakClass] = field(default_factory=list)
    recommendations: dict[str, list[str]] = field(default_factory=dict)

    @property
    def passes_threshold(self) -> bool:
        return not self.weak_classes and self.overall_map50 >= self.threshold


# ============================================
# تحديد الـ classes الضعيفة
# ============================================
def identify_weak_classes(
    eval_report: EvalReport,
    *,
    threshold: float = 0.5,
    dataset_stats: Iterable[ClassStats] | None = None,
) -> list[WeakClass]:
    """يُرجع الـ classes التي mAP50 لديها تحت الـ threshold."""
    stats_map: dict[str, ClassStats] = {}
    if dataset_stats:
        stats_map = {s.class_name: s for s in dataset_stats}

    weak: list[WeakClass] = []
    for class_name, map50 in eval_report.per_class_map50.items():
        if map50 >= threshold:
            continue
        stat = stats_map.get(class_name)
        reasons = _diagnose(map50, eval_report, stat, threshold)
        weak.append(
            WeakClass(
                class_name=class_name,
                map50=float(map50),
                threshold=threshold,
                instances=stat.instances if stat else None,
                images=stat.images if stat else None,
                reasons=tuple(reasons),
            )
        )

    weak.sort(key=lambda w: w.map50)
    return weak


def _diagnose(
    map50: float,
    report: EvalReport,
    stat: ClassStats | None,
    threshold: float,
) -> list[str]:
    """يستنتج أسباباً محتملة لضعف class."""
    reasons: list[str] = []
    if stat is not None and stat.instances < 100:
        reasons.append(f"عينات قليلة ({stat.instances} instance)")
    if report.precision < report.recall - 0.1:
        reasons.append("precision أقل من recall — كثير false positives")
    elif report.recall < report.precision - 0.1:
        reasons.append("recall أقل من precision — كشف ناقص")
    if map50 < threshold * 0.5:
        reasons.append("mAP50 أقل من نصف الحد — صعب أصلاً للكشف")
    if not reasons:
        reasons.append(f"mAP50 ({map50:.2f}) تحت الحد ({threshold:.2f})")
    return reasons


# ============================================
# توصيات التحسين
# ============================================
def recommend_augmentation(weak_classes: Iterable[WeakClass]) -> dict[str, list[str]]:
    """يُولّد توصيات augmentation لكل class ضعيف."""
    recommendations: dict[str, list[str]] = {}
    for w in weak_classes:
        tips: list[str] = []
        if w.instances is not None and w.instances < 100:
            tips.append("اجمع عينات إضافية (>100 لكل class)")
            tips.append("استخدم copy_paste augmentation لتضخيم الـ class")
        if w.map50 < 0.3:
            tips.append("راجع جودة الـ annotations لهذا الـ class")
            tips.append("ارفع mosaic=1.0 و mixup=0.15")
        else:
            tips.append("اضبط hsv_h=0.02 و hsv_s=0.8 لتنوع ألوان")
            tips.append("اضبط fliplr=0.5 و scale=0.5")
        if any("false positives" in r for r in w.reasons):
            tips.append("ارفع conf threshold عند الـ inference")
            tips.append("اضبط cls weight أعلى في loss")
        if any("كشف ناقص" in r for r in w.reasons):
            tips.append("اخفض conf threshold عند الـ inference")
            tips.append("استخدم imgsz أكبر (e.g. 960)")
        recommendations[w.class_name] = tips
    return recommendations


# ============================================
# الواجهة الرئيسية
# ============================================
def analyze(
    eval_report: EvalReport,
    *,
    threshold: float = 0.5,
    dataset_stats: Iterable[ClassStats] | None = None,
) -> ErrorAnalysisReport:
    """يُجري التحليل الكامل ويُولّد التقرير."""
    weak = identify_weak_classes(eval_report, threshold=threshold, dataset_stats=dataset_stats)
    return ErrorAnalysisReport(
        threshold=threshold,
        overall_map50=float(eval_report.map50),
        overall_map=float(eval_report.map),
        weak_classes=weak,
        recommendations=recommend_augmentation(weak),
    )


# ============================================
# Augmentation recipe (YAML hint للـ trainer)
# ============================================
DEFAULT_AUGMENT_RECIPE: dict[str, float | bool] = {
    "augment": True,
    "mosaic": 1.0,
    "mixup": 0.1,
    "hsv_h": 0.015,
    "hsv_s": 0.7,
    "hsv_v": 0.4,
    "degrees": 5.0,
    "translate": 0.1,
    "scale": 0.5,
    "fliplr": 0.5,
    "copy_paste": 0.0,
}


def build_augment_recipe(weak_classes: Iterable[WeakClass]) -> dict[str, float | bool]:
    """يبني وصفة augmentation معدّلة بناءً على الـ classes الضعيفة."""
    recipe = dict(DEFAULT_AUGMENT_RECIPE)
    weak_list = list(weak_classes)
    if not weak_list:
        return recipe

    low_sample = any((w.instances is not None and w.instances < 100) for w in weak_list)
    very_weak = any(w.map50 < 0.3 for w in weak_list)

    if low_sample:
        recipe["copy_paste"] = 0.3
        recipe["mixup"] = 0.15
    if very_weak:
        recipe["mosaic"] = 1.0
        recipe["hsv_s"] = 0.8

    return recipe


# ============================================
# تصدير التقرير
# ============================================
def report_to_json(report: ErrorAnalysisReport) -> str:
    """يُسلسل التقرير إلى JSON."""
    data = {
        "threshold": report.threshold,
        "overall_map50": report.overall_map50,
        "overall_map": report.overall_map,
        "weak_classes": [asdict(w) for w in report.weak_classes],
        "recommendations": report.recommendations,
        "passes_threshold": report.passes_threshold,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def write_report(report: ErrorAnalysisReport, output_path: Path | str) -> Path:
    """يكتب التقرير إلى ملف JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_to_json(report), encoding="utf-8")
    return out


def known_class_names() -> list[str]:
    """يُرجع أسماء كل الـ classes المعروفة (لـ default analyses)."""
    return list(DETECTION_CLASSES.values())


__all__ = [
    "DEFAULT_AUGMENT_RECIPE",
    "ErrorAnalysisReport",
    "WeakClass",
    "analyze",
    "build_augment_recipe",
    "identify_weak_classes",
    "recommend_augmentation",
    "report_to_json",
    "write_report",
]
