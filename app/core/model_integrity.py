"""التحقق من سلامة ملفات النماذج قبل تحميلها.

ملفات `.pt` حمولات **pickle**: تحميلها ينفّذ كوداً بصلاحيات المستخدم. الحماية
الحقيقية ليست «نزّلنا من رابط HTTPS» بل مطابقة بصمة معروفة، وأن تُعاد المطابقة
**عند كل تحميل** لا عند التنزيل مرة واحدة — الملف على القرص قابل للاستبدال بعد
ذلك (برمجية على الجهاز، مجلد مُزامَن، نسخة يدوية من مصدر آخر).

الآلية: `scripts/download_models.py` يكتب بصمة الملف في ملف مجاور
`<model>.sha256` بعد تنزيل **مُتحقَّق منه**، وهذه الوحدة تقارن البصمة الفعلية به
قبل التحميل. غياب الملف المجاور ليس خطأً (نموذج درّبه المستخدم بنفسه مثلاً)
لكنه يُسجَّل تحذيراً حتى لا يمرّ «بلا تحقق» بصمت.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.utils.hash_utils import full_file_hash

logger = logging.getLogger(__name__)

SIDECAR_SUFFIX = ".sha256"


class ModelIntegrityError(RuntimeError):
    """تُرفع عند اختلاف بصمة النموذج عن البصمة المسجَّلة بجواره."""


def sidecar_path(model_path: Path | str) -> Path:
    """مسار ملف البصمة المجاور للنموذج."""
    path = Path(model_path)
    return path.with_name(path.name + SIDECAR_SUFFIX)


def write_sidecar(model_path: Path | str, digest: str) -> Path:
    """يكتب بصمة نموذج تحقّقنا منه، ليُقارن بها في كل تحميل لاحق."""
    out = sidecar_path(model_path)
    out.write_text(f"{digest}\n", encoding="utf-8")
    return out


def read_sidecar(model_path: Path | str) -> str | None:
    """البصمة المسجَّلة للنموذج، أو None لو لا يوجد ملف مجاور."""
    path = sidecar_path(model_path)
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip().split()
    return value[0].lower() if value else None


def verify_model_file(model_path: Path | str) -> bool:
    """يتحقق من بصمة النموذج قبل تحميله.

    يُرجع True لو طابقت البصمة، وFalse لو لا توجد بصمة مسجَّلة (مع تحذير).
    يرفع `ModelIntegrityError` عند **اختلاف** البصمة — الاختلاف ليس تحذيراً:
    الملف تغيّر عمّا تحقّقنا منه، وتحميله تنفيذ كود من مصدر مجهول.
    """
    path = Path(model_path)
    expected = read_sidecar(path)
    if expected is None:
        logger.warning(
            "لا توجد بصمة مسجَّلة للنموذج %s — يُحمَّل بلا تحقق. "
            "نزّل النماذج عبر scripts/download_models.py ليُسجَّل %s بجوارها.",
            path.name,
            SIDECAR_SUFFIX,
        )
        return False
    actual = full_file_hash(path).lower()
    if actual != expected:
        raise ModelIntegrityError(
            f"بصمة النموذج {path.name} لا تطابق المسجَّلة بجواره.\n"
            f"  المسجَّلة: {expected}\n"
            f"  الفعلية:  {actual}\n"
            "ملفات .pt تُنفِّذ كوداً عند التحميل — لا تُحمِّله. أعد التنزيل عبر "
            "scripts/download_models.py، أو احذف ملف البصمة إن كنت استبدلت النموذج بقصد."
        )
    logger.info("بصمة النموذج %s مطابقة", path.name)
    return True


__all__ = [
    "ModelIntegrityError",
    "SIDECAR_SUFFIX",
    "read_sidecar",
    "sidecar_path",
    "verify_model_file",
    "write_sidecar",
]
