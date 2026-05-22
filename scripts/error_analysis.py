"""سكربت سطر أوامر لتقييم النموذج وتحديد الـ classes الضعيفة."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dataset import collect_samples, compute_class_stats  # noqa: E402
from app.core.error_analysis import (  # noqa: E402
    ErrorAnalysisReport,
    analyze,
    write_report,
)
from app.core.trainer import TrainerService  # noqa: E402


def _print_report(report: ErrorAnalysisReport) -> None:
    print("\n" + "=" * 60)
    print("تقرير تحليل الأخطاء")
    print("=" * 60)
    print(f"  mAP50 الإجمالي: {report.overall_map50:.3f}")
    print(f"  mAP الإجمالي:   {report.overall_map:.3f}")
    print(f"  الحد الأدنى:    {report.threshold:.3f}")
    print(f"  يجتاز الحد؟    {'✔ نعم' if report.passes_threshold else '✗ لا'}")

    if report.weak_classes:
        print(f"\n  الـ classes الضعيفة ({len(report.weak_classes)}):")
        for w in report.weak_classes:
            print(f"    • {w.class_name}: mAP50={w.map50:.3f}")
            for reason in w.reasons:
                print(f"        - {reason}")
            tips = report.recommendations.get(w.class_name, [])
            for tip in tips:
                print(f"        → {tip}")
    else:
        print("\n  ✔ كل الـ classes تجتاز الحد")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="تحليل أخطاء النموذج المدرَّب")
    parser.add_argument(
        "--model",
        type=Path,
        required=True,
        help="مسار best.pt",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="مسار dataset.yaml",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="الحد الأدنى لـ mAP50 لكل class",
    )
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=None,
        help="مجلد عينات (لحساب التوزيع — اختياري)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="مسار JSON للتقرير",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    service = TrainerService()
    try:
        eval_report = service.evaluate(args.model, args.data)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ فشل التقييم: {exc}", file=sys.stderr)
        return 1

    dataset_stats = None
    if args.samples_dir is not None and args.samples_dir.exists():
        samples = collect_samples(args.samples_dir)
        dataset_stats = compute_class_stats(samples)

    report = analyze(eval_report, threshold=args.threshold, dataset_stats=dataset_stats)
    _print_report(report)

    if args.output:
        out = write_report(report, args.output)
        print(f"\n✔ كُتب التقرير في: {out}")

    return 0 if report.passes_threshold else 2


if __name__ == "__main__":
    sys.exit(main())
