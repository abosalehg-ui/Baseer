"""تنزيل النماذج الجاهزة (YOLOv8x) إلى models/pretrained/."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.model_integrity import write_sidecar  # noqa: E402

DEFAULT_DEST = PROJECT_ROOT / "models" / "pretrained"


# (url, sha256) لكل نموذج.
# ⚠️ ملفات `.pt` حمولات pickle **تُنفِّذ كوداً عند التحميل**. التحقق من البصمة
# هو ما يحوّل «نزّلنا من رابط HTTPS» إلى ضمان فعلي بأن الملف هو المتوقَّع.
#
# البصمتان `None` هنا **عن قصد**: لا يجوز أن يُثبِّتها من لم ينزّل النموذج من
# مصدره ويتحقق منه خارج النطاق (out-of-band) — بصمة مكتوبة من تنزيلٍ غير موثوق
# تبدو ضماناً وهي ليست كذلك، وهذا أسوأ من غيابها. والسكربت الآن **يفشل مُغلَقاً**
# (fail closed) بدل التنزيل بلا تحقق: الخطوة الأولى للمستخدم هي
#
#     python scripts/download_models.py --print-hashes
#
# ثم يلصق القيمتين هنا (بعد مقارنتهما بما ينشره Ultralytics). بعدها يعمل
# التنزيل العادي بتحقق صارم، ويُكتب ملف بصمة مجاور `<model>.sha256` يقارنه
# `app/core/model_integrity` عند **كل** تحميل — فاستبدال الملف على القرص لاحقاً
# لا يمر بصمت.
MODELS: dict[str, tuple[str, str | None]] = {
    "yolov8x.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x.pt",
        None,  # ضع بصمة SHA256 هنا (انظر --print-hashes أعلاه)
    ),
    "yolov8m.pt": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt",
        None,
    ),
}


class ChecksumMismatchError(RuntimeError):
    """يُرفع عند اختلاف بصمة الملف المُنزَّل عن المتوقَّعة."""


class UnverifiedModelError(RuntimeError):
    """يُرفع عند محاولة تنزيل/استخدام نموذج بلا بصمة مثبَّتة."""


def download(
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    chunk: int = 1 << 20,
    allow_unverified: bool = False,
) -> str:
    """ينزّل ملفاً ويتحقق من بصمته. يُرجع البصمة المحسوبة.

    يُنزَّل إلى ملف مؤقت أولاً: ملف نصفه منزَّل أو فاشل التحقق يجب ألا يبقى
    باسمه النهائي حيث يلتقطه التطبيق لاحقاً كأنه سليم.

    `allow_unverified=True` يسمح بالتنزيل بلا بصمة مثبَّتة — لخطوة
    `--print-hashes` وحدها، ولا يكتب ملف بصمة مجاوراً.
    """
    if not url.lower().startswith("https://"):
        raise ValueError(f"روابط النماذج يجب أن تكون HTTPS: {url}")
    if expected_sha256 is None and not allow_unverified:
        raise UnverifiedModelError(
            f"لا توجد بصمة مثبَّتة لـ{dest.name}. ملفات .pt تُنفِّذ كوداً عند التحميل، "
            "فلا نُنزّلها بلا تحقق.\n"
            "  1) شغّل: python scripts/download_models.py --print-hashes\n"
            "  2) قارن القيم بما ينشره مصدر النموذج، ثم ثبّتها في MODELS\n"
            "  3) أعد التشغيل عادةً — سيتحقق تلقائياً ويكتب <model>.sha256 بجواره"
        )

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
        # بصمة مجاورة يقارنها التطبيق عند كل تحميل — لا عند التنزيل فقط
        sidecar = write_sidecar(dest, digest)
        print(f"  بصمة مجاورة: {sidecar.name}")
    return digest


def verify_existing(dest: Path, expected_sha256: str | None) -> bool:
    """يتحقق من ملف موجود مسبقاً بدل تخطيه بلا نظر.

    التخطي على أساس «الملف موجود» كان يعني أن ملفاً استُبدل على القرص بعد
    التنزيل لا يُعاد التحقق منه **أبداً**.
    """
    if expected_sha256 is None:
        print(f"⤳ موجود مسبقاً بلا بصمة مثبَّتة: {dest} — لا يمكن التحقق")
        return False
    actual = hashlib.sha256(dest.read_bytes()).hexdigest()
    if actual.lower() != expected_sha256.lower():
        print(
            f"✗ الملف الموجود {dest.name} لا يطابق البصمة المثبَّتة — "
            "استُبدل أو تلف. أعد التنزيل بـ--force",
            file=sys.stderr,
        )
        return False
    write_sidecar(dest, actual)
    print(f"✔ الملف الموجود {dest.name} مطابق للبصمة المثبَّتة")
    return True


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
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="ينزّل بلا بصمة مثبَّتة (غير مستحسن — ملفات .pt تُنفِّذ كوداً عند التحميل)",
    )
    args = parser.parse_args()

    digests: dict[str, str] = {}
    exit_code = 0
    for name in args.models:
        dest = args.dest / name
        url, expected = MODELS[name]
        if dest.exists() and not args.force:
            if not verify_existing(dest, expected):
                exit_code = max(exit_code, 3)
            continue
        try:
            digests[name] = download(
                url,
                dest,
                expected_sha256=None if args.print_hashes else expected,
                allow_unverified=args.print_hashes or args.allow_unverified,
            )
        except ChecksumMismatchError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 2
        except UnverifiedModelError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 4
        except Exception as exc:  # noqa: BLE001
            print(f"✗ فشل تنزيل {name}: {exc}", file=sys.stderr)
            return 1

    if args.print_hashes and digests:
        print("\n# انسخ هذه القيم إلى MODELS في هذا الملف:")
        for name, digest in digests.items():
            print(f'#   "{name}": (..., "{digest}"),')
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
