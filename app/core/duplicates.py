"""كشف تكرار المقاطع — تطابق ثنائي مؤكَّد + تشابه بصري للمراجعة البشرية.

مفصولة عن `library.py` لأن الملف تجاوز حدّ الأسطر المُعلَن في
`docs/architecture.md` بعد إضافة تأكيد البصمة الكاملة. `LibraryService` يُعيد
تصدير الواجهة (`detect_duplicates`, `DuplicateGroup`) فالمستدعون لا يتغيّرون.

**مبدأ القسم:** الإسقاط التلقائي لا يجوز إلا على دليل قاطع. البصمة الجزئية
(`file_hash`) فلتر أوّلي سريع يُؤكَّد بـhash كامل؛ والتشابه البصري (`phash`) لا
يُسقط شيئاً تلقائياً أبداً — يُعرض في `DuplicatesDialog` ليقرر إنسان.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.hash_utils import full_file_hash, phash_distance

logger = logging.getLogger(__name__)

# عتبة مسافة Hamming للتشابه البصري (phash بطول 16×16 بت = 256 بت).
# القيمة محافظة عمداً: كلما ارتفعت زاد التقاط المتشابهات وزادت الإيجابيات
# الكاذبة. النتائج تُراجَع بشرياً في DuplicatesDialog ولا تُحذف تلقائياً.
PHASH_MAX_DISTANCE: int = 10


@dataclass
class DuplicateGroup:
    """مجموعة مقاطع متطابقة."""

    representative_id: int
    duplicate_ids: list[int]
    match_type: str  # "exact" | "perceptual"


def confirmed_duplicate(db: Any, file_path: Path, partial_hash: str) -> bool:
    """هل الملف مطابق **ثنائياً** لمقطع موجود؟ — مؤكَّداً بـhash كامل.

    `videos.file_hash` بصمة **جزئية** (أول 4 م.ب + آخر 4 م.ب + الحجم) اختيرت
    للسرعة، فتصادمها واقعي: مقطعان بنفس الحجم ونفس الترويسة والذيل — تصدير
    دفعة واحدة من نفس الكاميرا، أو قصّ من نفس المنتصف — يعطيان نفس البصمة.
    الإسقاط التلقائي عليها كان يرفض **دليلاً مختلفاً بصمت** في تطبيق مادّته
    الأدلة، فصارت البصمة الجزئية فلتراً أوّلياً ويؤكّدها hash كامل للملفين.
    الحساب الكامل يجري عند الاشتباه وحده فتبقى تكلفته محصورة.

    عند تعذّر التأكيد (ملف المقطع القديم لم يبقَ على القرص) **لا نُسقط**: نستورد
    ونترك المطابقة لـ`find_duplicate_groups()` ومراجعة بشرية — خسارة صفٍّ مكرر
    أهون من خسارة دليل.
    """
    rows = db.fetch_all("SELECT id, filepath FROM videos WHERE file_hash = ?", (partial_hash,))
    if not rows:
        return False
    try:
        incoming = full_file_hash(file_path)
    except OSError as exc:
        logger.warning("تعذّر حساب البصمة الكاملة لـ %s: %s — نستورده", file_path.name, exc)
        return False

    for video_id, candidate_path in rows:
        path = Path(str(candidate_path))
        if not path.exists():
            logger.warning(
                "بصمة جزئية مطابقة للمقطع #%s لكن ملفه غير موجود (%s) — "
                "لا نُسقط الملف؛ راجعه في «مراجعة التكرارات»",
                video_id,
                path,
            )
            continue
        try:
            if full_file_hash(path) == incoming:
                return True
        except OSError as exc:
            logger.warning("تعذّر قراءة %s لتأكيد التكرار: %s", path, exc)
    return False


def find_duplicate_groups(
    db: Any, *, phash_max_distance: int | None = None
) -> list[DuplicateGroup]:
    """يكشف التكرارات: تطابق ثنائي (file_hash) + تشابه بصري (مسافة phash).

    التشابه البصري يُقاس بمسافة Hamming لا بالتساوي التام: نسختان من نفس المقطع
    بجودة/ترميز مختلف تُعطيان phash **متقارباً لا متطابقاً**، فالتجميع بالتساوي
    كان يفوّت تماماً الحالة التي وُجدت الميزة من أجلها.
    """
    threshold = PHASH_MAX_DISTANCE if phash_max_distance is None else phash_max_distance
    groups: list[DuplicateGroup] = []

    exact = db.fetch_all(
        "SELECT file_hash, ARRAY_AGG(id ORDER BY id) "
        "FROM videos WHERE file_hash IS NOT NULL "
        "GROUP BY file_hash HAVING COUNT(*) > 1"
    )
    for _hash, ids in exact:
        ids_list = list(ids)
        groups.append(
            DuplicateGroup(
                representative_id=int(ids_list[0]),
                duplicate_ids=[int(i) for i in ids_list[1:]],
                match_type="exact",
            )
        )

    seen = {gid for g in groups for gid in [g.representative_id, *g.duplicate_ids]}
    rows = db.fetch_all("SELECT id, phash FROM videos WHERE phash IS NOT NULL ORDER BY id")
    candidates = [(int(r[0]), str(r[1])) for r in rows if int(r[0]) not in seen]
    groups.extend(group_by_phash_distance(candidates, threshold))
    return groups


def group_by_phash_distance(
    candidates: list[tuple[int, str]], threshold: int
) -> list[DuplicateGroup]:
    """يجمّع المقاطع المتقاربة بصرياً (تجميع جشِع حول ممثِّل).

    نمشي بالترتيب: أول مقطع غير مُخصَّص يصير ممثِّلاً، ونضم إليه كل من مسافته
    منه ≤ العتبة. بسيط وحتمي وكافٍ لأحجام مكتبة سطح المكتب.
    """
    assigned: set[int] = set()
    out: list[DuplicateGroup] = []
    for i, (vid, phash) in enumerate(candidates):
        if vid in assigned:
            continue
        members: list[int] = []
        for other_id, other_hash in candidates[i + 1 :]:
            if other_id in assigned:
                continue
            try:
                distance = phash_distance(phash, other_hash)
            except (ValueError, TypeError):
                continue  # phash تالف — نتخطاه بدل إسقاط الفحص كله
            if distance <= threshold:
                members.append(other_id)
                assigned.add(other_id)
        if members:
            assigned.add(vid)
            out.append(
                DuplicateGroup(
                    representative_id=vid,
                    duplicate_ids=members,
                    match_type="perceptual",
                )
            )
    return out


__all__ = [
    "PHASH_MAX_DISTANCE",
    "DuplicateGroup",
    "confirmed_duplicate",
    "find_duplicate_groups",
    "group_by_phash_distance",
]
