"""اختبارات خدمة OCR — كلها بـ mocked recognizer بدون PaddleOCR."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ocr import (
    OCRResult,
    OCRService,
    looks_like_saudi_plate,
    normalize_plate_text,
)


# ============================================
# normalize_plate_text
# ============================================
def test_normalize_plate_strips_non_plate_chars() -> None:
    assert normalize_plate_text("ا ب د 1 2 3 *") == "ا ب د 1 2 3"


def test_normalize_plate_collapses_whitespace() -> None:
    assert normalize_plate_text("  ا  ب  د    1234  ") == "ا ب د 1234"


def test_normalize_plate_converts_arabic_digits() -> None:
    assert "1234" in normalize_plate_text("١٢٣٤")


def test_normalize_plate_unifies_alef_forms() -> None:
    # أ، إ، آ → ا
    assert "أ" not in normalize_plate_text("أ ب ج 1234")
    assert "ا" in normalize_plate_text("أ ب ج 1234")


def test_normalize_plate_uppercases_latin() -> None:
    assert "ABC" in normalize_plate_text("abc 1234")


def test_normalize_plate_empty_input_returns_empty() -> None:
    assert normalize_plate_text("") == ""


# ============================================
# looks_like_saudi_plate
# ============================================
def test_looks_like_saudi_plate_accepts_typical_format() -> None:
    assert looks_like_saudi_plate("ا ب د 1234")
    assert looks_like_saudi_plate("ABC 1234")


def test_looks_like_saudi_plate_rejects_too_short() -> None:
    assert not looks_like_saudi_plate("ا 12")


def test_looks_like_saudi_plate_rejects_letters_only() -> None:
    assert not looks_like_saudi_plate("ا ب د")


# ============================================
# OCRService.read_image
# ============================================
def _fake_recognizer(readings: list[tuple[str, float]]):
    def _fn(_path) -> list[tuple[str, float]]:
        return list(readings)

    return _fn


@pytest.fixture()
def image_file(tmp_path: Path) -> Path:
    img = tmp_path / "plate.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    return img


def test_read_image_returns_highest_confidence_reading(image_file: Path) -> None:
    service = OCRService(recognize_fn=_fake_recognizer([("ا ب د ١٢٣٤", 0.92), ("noise", 0.20)]))
    result = service.read_image(image_file)
    assert "1234" in result.text
    assert result.confidence == 0.92


def test_read_image_returns_empty_when_no_readings(image_file: Path) -> None:
    service = OCRService(recognize_fn=_fake_recognizer([]))
    result = service.read_image(image_file)
    assert result.is_empty
    assert result.confidence == 0.0


def test_read_image_raises_for_missing_file(tmp_path: Path) -> None:
    service = OCRService(recognize_fn=_fake_recognizer([]))
    with pytest.raises(FileNotFoundError):
        service.read_image(tmp_path / "ghost.jpg")


# ============================================
# read_track_plates (التصويت)
# ============================================
def test_read_track_plates_picks_majority_vote(tmp_path: Path) -> None:
    images = []
    readings = [
        [("ا ب د 1234", 0.85)],
        [("ا ب د 1234", 0.90)],
        [("ا ب د 5678", 0.50)],
    ]
    for i, _reads in enumerate(readings):
        img = tmp_path / f"p{i}.jpg"
        img.write_bytes(b"\xff\xd8\xff")
        images.append(img)

    iter_readings = iter(readings)

    def _fn(_path) -> list[tuple[str, float]]:
        return next(iter_readings)

    service = OCRService(recognize_fn=_fn)
    plate = service.read_track_plates(images)
    assert "1234" in plate.text
    assert plate.reads_count == 2
    assert plate.confidence == pytest.approx((0.85 + 0.90) / 2)


def test_read_track_plates_returns_empty_when_all_below_threshold(
    tmp_path: Path,
) -> None:
    img = tmp_path / "p.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    service = OCRService(recognize_fn=_fake_recognizer([("x", 0.1)]))
    plate = service.read_track_plates([img], min_confidence=0.5)
    assert plate.text == ""
    assert plate.reads_count == 0


def test_read_track_plates_skips_failed_reads(tmp_path: Path) -> None:
    good = tmp_path / "good.jpg"
    good.write_bytes(b"\xff\xd8\xff")
    bad = tmp_path / "bad.jpg"  # غير موجود — سيرفع FileNotFoundError

    service = OCRService(recognize_fn=_fake_recognizer([("ا ب د 1234", 0.85)]))
    plate = service.read_track_plates([good, bad])
    assert plate.text != ""
    assert plate.reads_count == 1


# ============================================
# OCRResult
# ============================================
def test_ocr_result_is_empty_helper() -> None:
    assert OCRResult(text="", raw_text="", confidence=0.0).is_empty
    assert not OCRResult(text="abc", raw_text="abc", confidence=0.5).is_empty
