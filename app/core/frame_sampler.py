"""قارئ خفيف لإطارات الفيديو حسب رقم الفريم — للكواشف التي تحتاج البكسلات."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class FrameProvider(Protocol):
    """واجهة بسيطة لقراءة إطار حسب رقمه — تُسهّل الـmocking في الاختبارات."""

    def get_frame(self, frame_no: int) -> np.ndarray | None: ...

    def close(self) -> None: ...


class FrameSampler:
    """يقرأ إطارات معينة من ملف فيديو عبر OpenCV.

    يفتح الـVideoCapture مرة واحدة، ويستخدم `CAP_PROP_POS_FRAMES` للقفز.
    آمن للإغلاق عبر `close()` أو context manager.
    """

    def __init__(self, video_path: Path | str) -> None:
        import cv2  # lazy import — قد لا تكون متوفرة في CI minimal

        self._path = Path(video_path)
        if not self._path.exists():
            raise FileNotFoundError(f"الملف غير موجود: {self._path}")
        self._cap = cv2.VideoCapture(str(self._path))
        if not self._cap.isOpened():
            raise RuntimeError(f"تعذّر فتح الفيديو: {self._path}")

    def get_frame(self, frame_no: int) -> np.ndarray | None:
        """يعيد الإطار كـ BGR numpy array أو None لو لم يتوفر."""
        import cv2

        if frame_no < 0:
            return None
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_no))
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()

    def __enter__(self) -> FrameSampler:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["FrameProvider", "FrameSampler"]
