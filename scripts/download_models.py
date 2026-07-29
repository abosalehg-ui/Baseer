"""تنزيل النماذج الجاهزة (YOLOv8x) إلى models/pretrained/."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = PROJECT_ROOT / "models" / "pretrained"


# (url, sha256) لكل نموذج.
# ⚠️ ملفات `.pt` حمولات pickle **تُنفِّذ كوداً عند التحميل**. التحقق من البصمة
# هو ما يحوّل «نزّلنا من رابط HTTPS» إلى ضمان فعلي بأن الملف هو المتوقَّع.
# كان السكربت يحسب SHA256 **ويطبعه فقط** بلا مقارنة — تحقق شكلي بلا فائدة.
#
# لتحديث البصمات بعد ترقية نسخة النموذج:
#     python scripts/download_models.py --print-hashes
MODELS: dict[str, tuple[str, str | None]] = {
    "yolov8x.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x.pt",
        None,  # ضع بصمة SHA256 هنا لتفعيل التحقق الصارم
    ),
    "yolov8m.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt",
        None,
    ),
}


class ChecksumMismatchError(RuntimeError):
    """يُرفع عند اختلاف بصمة الملف المُنزَّل عن المتوقَّعة."""


def download(
    url: str, dest: Path, *, expected_sha256: str | None = None, chunk: int = 1 << 20
) -> str:
    """ينزّل ملفاً ويتحقق من بصمته. يُرجع البصمة المحسوبة.

    يُنزَّل إلى ملف مؤقت أولاً: ملف نصفه منزَّل أو فاشل التحقق يجب ألا يبقى
    باسمه النهائي حيث يلتقطه التطبيق لاحقاً كأنه سليم.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"روابط النماذج يجب أن تكون HTTPS: {url}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"➜ تنزيل {url}")
    sha = hashlib.sha256()
    try:
        with urlopen(url) as response, tmp.open("wb") as fp:  # noqa: S310
            total = int(response.headers.get("content-length", 0) or 0)
            downloaded = 0
            while True:
                buf = response.read(chunk)
                if not buf:
                    break
                fp.write(buf)
                sha.update(buf)
                downloaded += len(buf)
                if total:
                    pct = 100 * downloaded / total
                    print(
                        f"  {downloaded / 1e6:8.1f} م.ب / {total / 1e6:.1f} م.ب  ({pct:5.1f}%)",
                        end="\r",
                    )

        digest = sha.hexdigest()
        if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
            raise ChecksumMismatchError(
                f"بصمة {dest.name} لا تطابق المتوقَّع.\n"
                f"  المتوقَّع: {expected_sha256}\n"
                f"  المحسوب: {digest}\n"
                "لا تستخدم هذا الملف — قد يكون تالفاً أو مُستبدَلاً."
            )
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)

    print(f"\n✔ حُفظ في {dest}")
    if expected_sha256 is None:
        print(f"  SHA256: {digest}  (لا يوجد تحقق — أضف البصمة إلى MODELS)")
    else:
        print(f"  SHA256 ✔ مطابقة: {digest[:16]}...")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="تنزيل نماذج YOLO الجاهزة")
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"مجلد التنزيل (افتراضي: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(MODELS.keys()),
        choices=list(MODELS.keys()),
        help="النماذج المراد تنزيلها",
    )
    parser.add_argument(
        "--print-hashes",
        action="store_true",
        help="ينزّل ويطبع البصمات لتثبيتها في MODELS (بلا تحقق)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="يُعيد التنزيل حتى لو كان الملف موجوداً",
    )
    args = parser.parse_args()

    digests: dict[str, str] = {}
    for name in args.models:
        dest = args.dest / name
        url, expected = MODELS[name]
        if dest.exists() and not args.force:
            print(f"⤳ موجود مسبقاً: {dest} — تخطي")
            continue
        try:
            digests[name] = download(
                url, dest, expected_sha256=None if args.print_hashes else expected
            )
        except ChecksumMismatchError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001
            print(f"✗ فشل تنزيل {name}: {exc}", file=sys.stderr)
            return 1

    if args.print_hashes and digests:
        print("\n# انسخ هذه القيم إلى MODELS في هذا الملف:")
        for name, digest in digests.items():
            print(f'#   "{name}": (..., "{digest}"),')
    return 0


if __name__ == "__main__":
    sys.exit(main())
