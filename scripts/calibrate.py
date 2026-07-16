"""سكربت سطر أوامر لمعايرة مقطع (meters_per_px) من نقاط مرجعية.

يفكّ حصار كاشفَي السرعة الزائدة والمسافة الآمنة اللذين يحتاجان المعايرة،
ريثما تتوفر أداة المعايرة في الواجهة.

مثال (نقطتان تبعدان 10 أمتار في الواقع):
    python scripts/calibrate.py --video-id 3 --points 100 500 400 500 --distances 10

مثال (3 نقاط، مسافتان):
    python scripts/calibrate.py --video-id 3 \\
        --points 100 500 400 500 700 500 --distances 10 10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.calibration import CalibrationService  # noqa: E402


def _pairs(flat: list[float]) -> list[tuple[float, float]]:
    if len(flat) % 2 != 0:
        raise ValueError("عدد قيم --points يجب أن يكون زوجياً (x y x y ...)")
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def main() -> int:
    parser = argparse.ArgumentParser(description="معايرة مقطع (meters_per_px)")
    parser.add_argument("--video-id", type=int, required=True, help="معرّف المقطع في DB")
    parser.add_argument(
        "--points",
        type=float,
        nargs="+",
        required=True,
        metavar="X Y",
        help="إحداثيات النقاط المرجعية بالبكسل: x1 y1 x2 y2 ...",
    )
    parser.add_argument(
        "--distances",
        type=float,
        nargs="+",
        required=True,
        metavar="M",
        help="المسافات الحقيقية بالأمتار بين النقاط المتتالية (عددها = عدد النقاط - 1)",
    )
    parser.add_argument("--show", action="store_true", help="عرض المعايرة الحالية والخروج")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    service = CalibrationService()

    if args.show:
        cal = service.get_calibration(args.video_id)
        if cal is None:
            print(f"لا توجد معايرة للمقطع #{args.video_id}")
        else:
            print(f"المقطع #{args.video_id}: meters_per_px={cal.meters_per_px:.5f}")
        return 0

    try:
        points = _pairs(args.points)
        cal = service.save_calibration(args.video_id, points, args.distances)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ فشلت المعايرة: {exc}", file=sys.stderr)
        return 1

    print(
        f"✔ حُفظت معايرة المقطع #{args.video_id}: "
        f"meters_per_px={cal.meters_per_px:.5f} "
        f"(1 بكسل ≈ {cal.meters_per_px * 100:.2f} سم)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
