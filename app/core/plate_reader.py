"""ربط قراءة اللوحات بخط المخالفات — يقرن كشوفات license_plate بالمركبة المخالِفة.

يفكّ حصار العمود `violations.license_plate` الذي كان يبقى فارغاً دائماً في الخط
التلقائي. الوحدة قابلة للحقن بالكامل (FrameProvider + OCRService) لتُختبر بلا
GPU ولا ملفات فيديو حقيقية.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.core.analyzer import Detection
from app.core.frame_sampler import FrameProvider
from app.core.ocr import OCRService, PlateRead
from app.utils.geometry import BBox, bbox_center, bbox_contains_point

logger = logging.getLogger(__name__)

LICENSE_PLATE_CLASS = "license_plate"


@dataclass(frozen=True)
class PlateCrop:
    """اقتصاص لوحة من إطار (frame_no + bbox)."""

    frame_no: int
    bbox: BBox


def plate_detections_for_track(
    track_bboxes: dict[int, BBox],
    frame_detections: dict[int, list[Detection]],
    *,
    max_crops: int = 5,
) -> list[PlateCrop]:
    """يجد كشوفات اللوحات الواقعة داخل صندوق المركبة عبر إطاراتها.

    Args:
        track_bboxes: خريطة frame_no → bbox المركبة في ذلك الإطار.
        frame_detections: كل كشوفات الإطار حسب رقمه.
        max_crops: أقصى عدد اقتصاصات نعيدها (نكتفي بأوضحها للتصويت).
    """
    crops: list[PlateCrop] = []
    for frame_no, vehicle_bbox in sorted(track_bboxes.items()):
        for det in frame_detections.get(frame_no, []):
            if det.class_name != LICENSE_PLATE_CLASS:
                continue
            if bbox_contains_point(vehicle_bbox, bbox_center(det.bbox)):
                crops.append(PlateCrop(frame_no=frame_no, bbox=det.bbox))
                break  # لوحة واحدة لكل إطار تكفي
        if len(crops) >= max_crops:
            break
    return crops


def read_plate_for_crops(
    crops: list[PlateCrop],
    provider: FrameProvider,
    ocr: OCRService,
    *,
    min_confidence: float = 0.3,
) -> PlateRead:
    """يقتصّ صور اللوحات من الإطارات ويقرأها بالتصويت عبر عدة إطارات."""
    images: list[np.ndarray] = []
    for crop in crops:
        frame = provider.get_frame(crop.frame_no)
        if frame is None:
            continue
        h, w = frame.shape[:2]
        x1 = max(0, int(crop.bbox[0]))
        y1 = max(0, int(crop.bbox[1]))
        x2 = min(w, int(crop.bbox[2]))
        y2 = min(h, int(crop.bbox[3]))
        if x2 <= x1 or y2 <= y1:
            continue
        images.append(frame[y1:y2, x1:x2])

    if not images:
        return PlateRead(text="", confidence=0.0, reads_count=0)
    return ocr.read_track_plate_images(images, min_confidence=min_confidence)


__all__ = ["PlateCrop", "plate_detections_for_track", "read_plate_for_crops"]
