"""سكربت سطر أوامر لتشغيل OCR على لوحات السيارات المحفوظة."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.ocr import OCRService, looks_like_saudi_plate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="قراءة لوحات السيارات عبر PaddleOCR")
    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="صورة لوحة (أو عدة صور لنفس track)",
    )
    parser.add_argument("--lang", default="ar", help="لغة OCR (افتراضي ar)")
    parser.add_argument("--gpu", action="store_true", help="استخدام GPU")
    parser.add_argument("--min-conf", type=float, default=0.3, help="حد أدنى للثقة")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    missing = [p for p in args.images if not p.exists()]
    if missing:
        for p in missing:
            print(f"✗ غير موجود: {p}", file=sys.stderr)
        return 1

    service = OCRService(lang=args.lang, use_gpu=args.gpu)

    if len(args.images) == 1:
        result = service.read_image(args.images[0])
        print(f"النص: {result.text!r}")
        print(f"خام:  {result.raw_text!r}")
        print(f"ثقة:  {result.confidence:.3f}")
        print(f"يشبه لوحة سعودية؟ {looks_like_saudi_plate(result.text)}")
        return 0

    plate = service.read_track_plates(list(args.images), min_confidence=args.min_conf)
    print("=== أفضل قراءة من الـ track ===")
    print(f"النص:           {plate.text!r}")
    print(f"الثقة المتوسطة: {plate.confidence:.3f}")
    print(f"عدد القراءات:    {plate.reads_count}/{len(args.images)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
