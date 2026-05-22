"""تطبيع النص العربي."""

from __future__ import annotations

import re

_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"

_NORMALIZE_MAP = {
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",
    "ى": "ي",
    "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
}

_ARABIC_INDIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_EASTERN_ARABIC_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def remove_diacritics(text: str) -> str:
    """يزيل التشكيل والعلامات."""
    return _ARABIC_DIACRITICS.sub("", text)


def remove_tatweel(text: str) -> str:
    """يزيل التطويل (kashida)."""
    return text.replace(_TATWEEL, "")


def normalize_letters(text: str) -> str:
    """يوحّد الأشكال المختلفة (أ/إ/آ → ا، ى → ي، ة → ه...)."""
    for src, dst in _NORMALIZE_MAP.items():
        text = text.replace(src, dst)
    return text


def normalize_digits(text: str) -> str:
    """يحوّل الأرقام الهندية والفارسية إلى لاتينية."""
    return text.translate(_ARABIC_INDIC_DIGITS).translate(_EASTERN_ARABIC_DIGITS)


def normalize_arabic(text: str) -> str:
    """يطبّق كل خطوات التطبيع — للبحث والمقارنة."""
    text = remove_diacritics(text)
    text = remove_tatweel(text)
    text = normalize_letters(text)
    text = normalize_digits(text)
    return re.sub(r"\s+", " ", text).strip()


def shape_for_pdf(text: str) -> str:
    """يُعيد تشكيل النص العربي للعرض في PDF (يحتاج arabic-reshaper + bidi)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError as exc:
        raise RuntimeError("يحتاج arabic-reshaper و python-bidi") from exc
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)
