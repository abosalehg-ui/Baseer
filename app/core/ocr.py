"""خدمة OCR للوحات السيارات — PaddleOCR + تطبيع للنص العربي/السعودي."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.arabic_utils import normalize_arabic

logger = logging.getLogger(__name__)


# الحروف العربية المسموحة في لوحات السعودية (بعد التطبيع)
SAUDI_PLATE_LETTERS: frozenset[str] = frozenset("ابحدرسصطعقكلمنهوي")


@dataclass(frozen=True)
class OCRResult:
    """نتيجة OCR لصورة واحدة (لوحة)."""

    text: str  # مُطبَّع
    raw_text: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True)
class PlateRead:
    """قراءة لوحة لمسار سيارة (track) عبر عدة فريمات."""

    text: str
    confidence: float
    reads_count: int


# الـ signature للـ callable القابل للحقن
RecognizeCallable = Callable[[Path | Any], list[tuple[str, float]]]


# ============================================
# تطبيع نص اللوحة
# ============================================
def normalize_plate_text(raw: str) -> str:
    """يطبّق التطبيع العربي + يزيل الرموز غير المسموحة + يفصل الأحرف عن الأرقام."""
    if not raw:
        return ""
    text = normalize_arabic(raw)
    text = text.upper()

    cleaned_chars: list[str] = []
    for ch in text:
        if ch.isdigit():
            cleaned_chars.append(ch)
        elif ch in SAUDI_PLATE_LETTERS:
            cleaned_chars.append(ch)
        elif ch.isalpha() and ord("A") <= ord(ch) <= ord("Z"):
            cleaned_chars.append(ch)
        elif ch == " ":
            cleaned_chars.append(" ")
    collapsed = re.sub(r"\s+", " ", "".join(cleaned_chars)).strip()
    return collapsed


def looks_like_saudi_plate(text: str) -> bool:
    """يتحقق بشكل تقريبي أن النص يشبه لوحة سعودية صالحة."""
    normalized = normalize_plate_text(text)
    digits = sum(1 for ch in normalized if ch.isdigit())
    letters = sum(1 for ch in normalized if ch.isalpha())
    return 3 <= digits <= 4 and 2 <= letters <= 4


# ============================================
# خدمة OCR
# ============================================
class OCRService:
    """خدمة OCR للوحات — تستخدم PaddleOCR افتراضياً، قابلة للحقن للاختبار."""

    def __init__(
        self,
        *,
        recognize_fn: RecognizeCallable | None = None,
        lang: str = "ar",
        use_gpu: bool = True,
    ) -> None:
        self._recognize_fn = recognize_fn
        self._lang = lang
        self._use_gpu = use_gpu
        self._paddle_engine: Any = None

    def read_image(self, image_path: Path | str) -> OCRResult:
        """يقرأ كل النصوص في صورة ويُرجع أعلاها ثقة."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"الصورة غير موجودة: {path}")
        readings = self._invoke_recognizer(path)
        return self._best_reading(readings)

    def read_array(self, image: Any) -> OCRResult:
        """يقرأ لوحة من مصفوفة صورة (numpy BGR) بدل مسار ملف."""
        readings = self._invoke_recognizer(image)
        return self._best_reading(readings)

    def read_track_plates(
        self,
        plate_image_paths: list[Path],
        *,
        min_confidence: float = 0.3,
    ) -> PlateRead:
        """يقرأ عدة صور لوحة لنفس track ويُرجع أفضل قراءة بالتصويت."""
        return self._vote(
            (self._safe_read(path, self.read_image) for path in plate_image_paths),
            min_confidence=min_confidence,
        )

    def read_track_plate_images(
        self,
        images: list[Any],
        *,
        min_confidence: float = 0.3,
    ) -> PlateRead:
        """كـ `read_track_plates` لكن من مصفوفات صور بدل مسارات ملفات."""
        return self._vote(
            (self._safe_read(img, self.read_array) for img in images),
            min_confidence=min_confidence,
        )

    # ============================================
    # داخلي
    # ============================================
    @staticmethod
    def _safe_read(source: Any, reader: Callable[[Any], OCRResult]) -> OCRResult | None:
        try:
            return reader(source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل قراءة اللوحة: %s", exc)
            return None

    @staticmethod
    def _vote(
        results: Iterable[OCRResult | None],
        *,
        min_confidence: float,
    ) -> PlateRead:
        """يُصوّت على أفضل نص عبر عدة قراءات (الأكثر تكراراً ثم الأعلى ثقة)."""
        votes: dict[str, list[float]] = {}
        for result in results:
            if result is None or result.is_empty or result.confidence < min_confidence:
                continue
            votes.setdefault(result.text, []).append(result.confidence)

        if not votes:
            return PlateRead(text="", confidence=0.0, reads_count=0)

        def _score(item: tuple[str, list[float]]) -> tuple[int, float]:
            _text, confs = item
            return len(confs), sum(confs) / len(confs)

        best_text, best_confs = max(votes.items(), key=_score)
        return PlateRead(
            text=best_text,
            confidence=sum(best_confs) / len(best_confs),
            reads_count=len(best_confs),
        )

    def _invoke_recognizer(self, source: Path | Any) -> list[tuple[str, float]]:
        if self._recognize_fn is not None:
            return list(self._recognize_fn(source))
        return self._default_recognize(source)

    def _default_recognize(self, source: Path | Any) -> list[tuple[str, float]]:
        engine = self._get_paddle_engine()
        # PaddleOCR يقبل مساراً نصياً أو مصفوفة numpy مباشرة
        arg = str(source) if isinstance(source, str | Path) else source
        result = engine.ocr(arg, cls=True)
        out: list[tuple[str, float]] = []
        if not result or not result[0]:
            return out
        for line in result[0]:
            if not line or len(line) < 2:
                continue
            text, conf = line[1][0], float(line[1][1])
            out.append((text, conf))
        return out

    def _get_paddle_engine(self) -> Any:
        if self._paddle_engine is not None:
            return self._paddle_engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("يحتاج paddleocr — ثبّت requirements.txt") from exc
        self._paddle_engine = PaddleOCR(
            use_angle_cls=True, lang=self._lang, use_gpu=self._use_gpu, show_log=False
        )
        return self._paddle_engine

    @staticmethod
    def _best_reading(readings: list[tuple[str, float]]) -> OCRResult:
        if not readings:
            return OCRResult(text="", raw_text="", confidence=0.0)
        readings.sort(key=lambda r: r[1], reverse=True)
        raw, conf = readings[0]
        return OCRResult(text=normalize_plate_text(raw), raw_text=raw, confidence=conf)


__all__ = [
    "OCRResult",
    "OCRService",
    "PlateRead",
    "looks_like_saudi_plate",
    "normalize_plate_text",
]
