"""تنزيل النماذج الجاهزة (YOLOv8x) إلى models/pretrained/."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = PROJECT_ROOT / "models" / "pretrained"


MODELS = {
    "yolov8x.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x.pt",
    "yolov8m.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m.pt",
}


def download(url: str, dest: Path, *, chunk: int = 1 << 20) -> None:
    """ينزّل ملفاً من URL إلى dest مع عرض التقدم."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"➜ تنزيل {url}")
    sha = hashlib.sha256()
    with urlopen(url) as response, dest.open("wb") as fp:  # noqa: S310
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
    print(f"\n✔ حُفظ في {dest}")
    print(f"  SHA256: {sha.hexdigest()[:16]}...")


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
    args = parser.parse_args()

    for name in args.models:
        dest = args.dest / name
        if dest.exists():
            print(f"⤳ موجود مسبقاً: {dest} — تخطي")
            continue
        try:
            download(MODELS[name], dest)
        except Exception as exc:  # noqa: BLE001
            print(f"✗ فشل تنزيل {name}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
