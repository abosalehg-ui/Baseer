"""كاشف إساءة استخدام أنوار التلاقي — heuristic مبني على شدة الإضاءة وحجم البقع.

النهج الهجين (المرحلة 1): يكتشف الإطارات الليلية ثم البقع الساطعة المشبعة في
منطقة المصابيح. مرحلة 2 (مستقبلية): استبدال هذا بفئة YOLO جديدة `high_beam_on`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from app.constants import ViolationType
from app.core.analyzer import Detection
from app.core.frame_sampler import FrameProvider, FrameSampler
from app.core.violations import BaseViolationDetector, Track, ViolationCandidate, Zone

logger = logging.getLogger(__name__)

VEHICLE_CLASSES = ("vehicle", "motorcycle")


class HighBeamDetector(BaseViolationDetector):
    """يكشف إساءة استخدام أنوار التلاقي عبر تحليل البكسلات في إطارات معاينة."""

    def __init__(
        self,
        *,
        video_path: Path | str | None = None,
        frame_provider: FrameProvider | None = None,
        luminance_night_threshold: int = 70,
        glare_v_min: int = 240,
        glare_s_max: int = 40,
        min_blob_area_px: int = 80,
        min_duration_sec: float = 2.0,
        sample_every_n_frames: int = 5,
    ) -> None:
        self._video_path = Path(video_path) if video_path is not None else None
        self._injected_provider = frame_provider
        self._luminance_night_threshold = luminance_night_threshold
        self._glare_v_min = glare_v_min
        self._glare_s_max = glare_s_max
        self._min_blob_area_px = min_blob_area_px
        self._min_duration_sec = min_duration_sec
        self._sample_every_n_frames = max(1, sample_every_n_frames)

    def detect(
        self,
        tracks: list[Track],
        frame_detections: dict[int, list[Detection]],
        zones: list[Zone],
        fps: float,
    ) -> list[ViolationCandidate]:
        if fps <= 0:
            return []
        provider = self._resolve_provider()
        if provider is None:
            return []

        try:
            return self._run(tracks, fps, provider)
        finally:
            # نُغلق فقط لو أنشأنا الـ provider داخلياً
            if self._injected_provider is None:
                provider.close()

    def _resolve_provider(self) -> FrameProvider | None:
        if self._injected_provider is not None:
            return self._injected_provider
        if self._video_path is None:
            return None
        try:
            return FrameSampler(self._video_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HighBeamDetector: تعذّر فتح الفيديو %s: %s", self._video_path, exc)
            return None

    def _run(
        self,
        tracks: list[Track],
        fps: float,
        provider: FrameProvider,
    ) -> list[ViolationCandidate]:
        import cv2

        # 1) نُفهرِس المركبات المطلوب فحصها حسب رقم الإطار.
        #    نحتفظ بالـ bboxes فقط (بضع عشرات البايتات) لا بالإطارات نفسها.
        boxes_per_frame: dict[int, list[tuple[int, tuple[float, float, float, float]]]] = {}
        for track in tracks:
            if track.class_name not in VEHICLE_CLASSES:
                continue
            for det in track.detections:
                if det.frame_no % self._sample_every_n_frames != 0:
                    continue
                boxes_per_frame.setdefault(det.frame_no, []).append((track.track_id, det.bbox))

        # 2) نعالج إطاراً واحداً في كل لحظة ثم نتخلّص منه.
        #    الاحتفاظ بكل الإطارات المسحوبة في الذاكرة (السلوك السابق) يعني
        #    ~11 ج.ب لمقطع 5 دقائق 1080p — كافٍ لإسقاط العملية بـMemoryError.
        #    فحص «هل الإطار ليلي؟» يُحسب **مرة لكل إطار** لا مرة لكل مركبة.
        bright_frames_per_track: dict[int, list[int]] = {}
        for frame_no in sorted(boxes_per_frame):
            frame = provider.get_frame(frame_no)
            if frame is None:
                continue
            if not self._is_night_frame(frame, cv2):
                continue
            for track_id, bbox in boxes_per_frame[frame_no]:
                if self._has_glare_in_bbox(frame, bbox, cv2):
                    bright_frames_per_track.setdefault(track_id, []).append(frame_no)
            del frame

        # 3) تجميع لكل track: تتابع الإطارات الساطعة
        violations: list[ViolationCandidate] = []
        for track in tracks:
            if track.class_name not in VEHICLE_CLASSES:
                continue
            track_frames = sorted(bright_frames_per_track.get(track.track_id, []))
            if not track_frames:
                continue
            duration_s = (track_frames[-1] - track_frames[0] + 1) / fps
            if duration_s < self._min_duration_sec:
                continue
            violations.append(
                ViolationCandidate(
                    violation_type=ViolationType.HIGH_BEAM_MISUSE,
                    track_id=track.track_id,
                    start_ms=int(track_frames[0] * 1000 / fps),
                    end_ms=int(track_frames[-1] * 1000 / fps),
                    confidence=min(0.75, 0.55 + duration_s / 20.0),
                    evidence_frames=track_frames[:5],
                    notes=(
                        f"[heuristic] بقع ساطعة في منطقة المصابيح لمدة {duration_s:.1f} ثانية "
                        "— يحتاج تأكيد بشري"
                    ),
                )
            )
        return violations

    def _is_night_frame(self, frame: np.ndarray, cv2: Any) -> bool:
        """فحص الإطار الليلي عبر متوسط قناة V في HSV."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mean_v = float(hsv[:, :, 2].mean())
        return mean_v <= self._luminance_night_threshold

    def _has_glare_in_bbox(
        self, frame: np.ndarray, bbox: tuple[float, float, float, float], cv2: Any
    ) -> bool:
        """يفحص الثُلث السفلي من bbox عن بقع بيضاء مشبعة."""
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))
        if x2 <= x1 or y2 <= y1:
            return False
        # الثُلث السفلي
        third_y1 = y1 + 2 * (y2 - y1) // 3
        crop = frame[third_y1:y2, x1:x2]
        if crop.size == 0:
            return False

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 2] >= self._glare_v_min) & (hsv[:, :, 1] <= self._glare_s_max)).astype(
            np.uint8
        ) * 255

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        big_blobs = sum(1 for c in contours if cv2.contourArea(c) >= self._min_blob_area_px)
        if big_blobs >= 2:
            return True
        # بقعة واحدة كبيرة جداً (تشبع شديد — مصابيح عالية أو هالة)
        if big_blobs == 1:
            largest = max(cv2.contourArea(c) for c in contours)
            if largest >= 3 * self._min_blob_area_px:
                return True
        return False


__all__ = ["HighBeamDetector"]
