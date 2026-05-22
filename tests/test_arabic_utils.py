"""اختبارات تطبيع النص العربي."""

from __future__ import annotations

from app.utils.arabic_utils import (
    normalize_arabic,
    normalize_digits,
    normalize_letters,
    remove_diacritics,
    remove_tatweel,
)


def test_remove_diacritics() -> None:
    assert remove_diacritics("الْحَمْدُ لِلَّهِ") == "الحمد لله"


def test_remove_tatweel() -> None:
    assert remove_tatweel("الـــبَصير") == "البَصير"


def test_normalize_letters_unifies_alef() -> None:
    assert normalize_letters("أكرم") == "اكرم"
    assert normalize_letters("إيمان") == "ايمان"
    assert normalize_letters("آدم") == "ادم"


def test_normalize_letters_unifies_yeh_and_teh() -> None:
    assert normalize_letters("مكتبى") == "مكتبي"
    assert normalize_letters("سيارة") == "سياره"


def test_normalize_digits_arabic_indic() -> None:
    assert normalize_digits("٠١٢٣٤٥٦٧٨٩") == "0123456789"


def test_normalize_digits_eastern_arabic() -> None:
    assert normalize_digits("۰۱۲۳۴۵۶۷۸۹") == "0123456789"


def test_normalize_arabic_full_pipeline() -> None:
    assert normalize_arabic("الْحَــمْدُ   لِلَّــــهِ ٢٠٢٦") == "الحمد لله 2026"
