"""دوال hashing للملفات والمحتوى البصري."""

from __future__ import annotations

import hashlib
from pathlib import Path

DEFAULT_SAMPLE_SIZE: int = 4 * 1024 * 1024


def file_hash(
    filepath: Path | str,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    algorithm: str = "sha256",
) -> str:
    """يحسب hash جزئي للملف (بداية + نهاية + الحجم).

    لا نحسب hash الملف بالكامل لأن مقاطع الفيديو الكبيرة بطيئة.
    دمج بداية ونهاية الملف مع حجمه يعطي تمييزاً عالياً مع سرعة كافية.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"الملف غير موجود: {path}")
    size = path.stat().st_size
    digest = hashlib.new(algorithm)
    digest.update(size.to_bytes(8, "little"))

    with path.open("rb") as fp:
        digest.update(fp.read(sample_size))
        if size > sample_size * 2:
            fp.seek(max(0, size - sample_size))
            digest.update(fp.read(sample_size))
    return digest.hexdigest()


def perceptual_hash_from_image_path(image_path: Path | str, hash_size: int = 16) -> str:
    """يحسب perceptual hash لصورة (يُستخدم على thumbnails)."""
    try:
        import imagehash
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("يحتاج imagehash و Pillow — ثبّت requirements.txt") from exc

    with Image.open(image_path) as img:
        phash = imagehash.phash(img, hash_size=hash_size)
    return str(phash)


def phash_distance(hash_a: str, hash_b: str) -> int:
    """يحسب مسافة Hamming بين hash مدركَين بصرياً (16 hex chars × 4 bits)."""
    int_a = int(hash_a, 16)
    int_b = int(hash_b, 16)
    return bin(int_a ^ int_b).count("1")
