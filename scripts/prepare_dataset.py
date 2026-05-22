"""سكربت سطر أوامر لتجهيز الـ dataset من CVAT export إلى بنية YOLOv8."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# نضمن أن جذر المشروع في PYTHONPATH عند التشغيل المباشر
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.dataset import DatasetReport, DatasetService  # noqa: E402


def _print_report(report: DatasetReport) -> None:
    print("\n" + "=" * 60)
    print("تقرير تجهيز الـ Dataset")
    print("=" * 60)
    print(f"  إجمالي العينات: {report.total_samples}")
    print(
        f"  train: {report.train_count}  |  val: {report.val_count}  |  test: {report.test_count}"
    )
    print("\n  توزيع الـ classes:")
    print(f"    {'class':>20}  {'instances':>10}  {'images':>10}")
    print(f"    {'-' * 20}  {'-' * 10}  {'-' * 10}")
    for cs in report.per_class:
        marker = "  ⚠" if cs.instances < 100 else ""
        print(f"    {cs.class_name:>20}  {cs.instances:>10}  {cs.images:>10}{marker}")

    if report.issues:
        print("\n  ⚠ تحذيرات:")
        for issue in report.issues:
            print(f"    • {issue}")
    else:
        print("\n  ✔ لا توجد تحذيرات")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="تجهيز dataset YOLOv8 من CVAT YOLO 1.1 export")
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data" / "annotations" / "reviewed",
        help="مجلد CVAT export (يحتوي الصور وملفات .txt)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "dataset",
        help="مجلد إخراج dataset YOLOv8",
    )
    parser.add_argument(
        "--ratios",
        nargs=3,
        type=float,
        default=[0.7, 0.2, 0.1],
        metavar=("TRAIN", "VAL", "TEST"),
        help="نسب التقسيم (الافتراضي: 0.7 0.2 0.1)",
    )
    parser.add_argument("--seed", type=int, default=42, help="seed للتقسيم")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="نسخ الملفات بدل إنشاء symlinks",
    )
    parser.add_argument(
        "--min-per-class",
        type=int,
        default=100,
        help="الحد الأدنى للـ instances لكل class (افتراضي 100)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    service = DatasetService()
    try:
        report = service.prepare(
            args.source,
            args.output,
            ratios=tuple(args.ratios),
            seed=args.seed,
            copy_files=args.copy,
            min_per_class=args.min_per_class,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"✗ فشل التجهيز: {exc}", file=sys.stderr)
        return 1

    _print_report(report)
    print(f"\n✔ dataset.yaml: {args.output / 'dataset.yaml'}")
    return 0 if not report.issues else 2


if __name__ == "__main__":
    sys.exit(main())
