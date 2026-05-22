"""اختبارات تحليل الأخطاء وتوصيات التحسين."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.dataset import ClassStats
from app.core.error_analysis import (
    DEFAULT_AUGMENT_RECIPE,
    analyze,
    build_augment_recipe,
    identify_weak_classes,
    recommend_augmentation,
    report_to_json,
    write_report,
)
from app.core.trainer import EvalReport


def _make_eval_report(
    map50: float = 0.75,
    overall_map: float = 0.55,
    precision: float = 0.8,
    recall: float = 0.7,
    per_class: dict[str, float] | None = None,
) -> EvalReport:
    return EvalReport(
        map50=map50,
        map=overall_map,
        precision=precision,
        recall=recall,
        per_class_map50=per_class or {"vehicle": 0.85, "helmet": 0.35, "person": 0.55},
    )


def test_identify_weak_classes_uses_threshold() -> None:
    weak = identify_weak_classes(_make_eval_report(), threshold=0.5)
    names = {w.class_name for w in weak}
    assert names == {"helmet"}


def test_identify_weak_classes_sorted_by_map50() -> None:
    report = _make_eval_report(per_class={"a": 0.45, "b": 0.20, "c": 0.40, "d": 0.90})
    weak = identify_weak_classes(report, threshold=0.5)
    assert [w.class_name for w in weak] == ["b", "c", "a"]


def test_identify_weak_includes_stats_when_provided() -> None:
    stats = [
        ClassStats(class_id=0, class_name="helmet", instances=30, images=20),
        ClassStats(class_id=1, class_name="person", instances=500, images=300),
    ]
    weak = identify_weak_classes(_make_eval_report(), threshold=0.5, dataset_stats=stats)
    helmet = next(w for w in weak if w.class_name == "helmet")
    assert helmet.instances == 30
    assert any("عينات قليلة" in r for r in helmet.reasons)


def test_identify_weak_returns_empty_when_all_pass() -> None:
    report = _make_eval_report(per_class={"a": 0.8, "b": 0.9, "c": 0.95})
    assert identify_weak_classes(report, threshold=0.5) == []


def test_recommend_augmentation_handles_low_samples() -> None:
    stats = [ClassStats(class_id=0, class_name="helmet", instances=30, images=20)]
    weak = identify_weak_classes(_make_eval_report(), threshold=0.5, dataset_stats=stats)
    recs = recommend_augmentation(weak)
    assert "helmet" in recs
    assert any("اجمع عينات" in tip for tip in recs["helmet"])


def test_recommend_augmentation_handles_false_positives() -> None:
    report = _make_eval_report(precision=0.5, recall=0.8)
    weak = identify_weak_classes(report, threshold=0.5)
    recs = recommend_augmentation(weak)
    assert any(any("conf threshold" in tip for tip in tips) for tips in recs.values())


def test_analyze_returns_complete_report() -> None:
    stats = [
        ClassStats(class_id=0, class_name="helmet", instances=30, images=20),
        ClassStats(class_id=1, class_name="vehicle", instances=2000, images=1500),
    ]
    eval_report = _make_eval_report(per_class={"vehicle": 0.85, "helmet": 0.35, "person": 0.45})
    report = analyze(eval_report, threshold=0.5, dataset_stats=stats)
    assert report.threshold == 0.5
    assert report.overall_map50 == 0.75
    weak_names = {w.class_name for w in report.weak_classes}
    assert weak_names == {"helmet", "person"}
    assert "helmet" in report.recommendations
    assert not report.passes_threshold


def test_analyze_passes_threshold_when_all_classes_strong() -> None:
    report = analyze(
        _make_eval_report(map50=0.85, per_class={"a": 0.80, "b": 0.78}),
        threshold=0.5,
    )
    assert report.passes_threshold


def test_build_augment_recipe_baseline_when_no_weak_classes() -> None:
    assert build_augment_recipe([]) == DEFAULT_AUGMENT_RECIPE


def test_build_augment_recipe_bumps_copypaste_for_low_samples() -> None:
    stats = [ClassStats(class_id=0, class_name="helmet", instances=30, images=20)]
    weak = identify_weak_classes(_make_eval_report(), threshold=0.5, dataset_stats=stats)
    recipe = build_augment_recipe(weak)
    assert recipe["copy_paste"] >= 0.2
    assert recipe["mixup"] >= DEFAULT_AUGMENT_RECIPE["mixup"]


def test_report_to_json_is_valid_and_includes_arabic() -> None:
    report = analyze(_make_eval_report(), threshold=0.5)
    text = report_to_json(report)
    parsed = json.loads(text)
    assert parsed["threshold"] == 0.5
    assert "weak_classes" in parsed


def test_write_report_creates_file(tmp_path: Path) -> None:
    report = analyze(_make_eval_report(), threshold=0.5)
    out = write_report(report, tmp_path / "report.json")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "overall_map50" in data
