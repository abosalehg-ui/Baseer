"""اختبارات ربط قراءة اللوحات بخط المخالفات."""

from __future__ import annotations

import numpy as np

from app.core.analyzer import Detection
from app.core.frame_sampler import FrameProvider
from app.core.ocr import OCRService
from app.core.plate_reader import plate_detections_for_track, read_plate_for_crops


class _FakeProvider:
    """FrameProvider وهمي يعيد إطاراً ثابتاً لأي رقم."""

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def get_frame(self, frame_no: int) -> np.ndarray | None:
        return self._frame

    def close(self) -> None:
        pass


def test_plate_detections_inside_vehicle_bbox() -> None:
    # مركبة تغطي (0,0)-(100,100) في الإطارين 0 و1
    track_bboxes = {0: (0.0, 0.0, 100.0, 100.0), 1: (0.0, 0.0, 100.0, 100.0)}
    frame_dets = {
        0: [
            Detection(0, 0, "license_plate", 0.9, (40.0, 70.0, 60.0, 85.0)),  # داخل المركبة
            Detection(0, 0, "license_plate", 0.8, (500.0, 500.0, 520.0, 515.0)),  # خارجها
        ],
        1: [Detection(1, 33, "license_plate", 0.9, (42.0, 70.0, 62.0, 85.0))],
    }
    crops = plate_detections_for_track(track_bboxes, frame_dets)
    assert len(crops) == 2
    assert {c.frame_no for c in crops} == {0, 1}


def test_plate_detections_none_when_no_plates() -> None:
    track_bboxes = {0: (0.0, 0.0, 100.0, 100.0)}
    frame_dets = {0: [Detection(0, 0, "vehicle", 0.9, (0, 0, 100, 100))]}
    assert plate_detections_for_track(track_bboxes, frame_dets) == []


def test_read_plate_for_crops_votes_across_frames() -> None:
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    provider: FrameProvider = _FakeProvider(frame)

    # OCR وهمي يعيد نصاً ثابتاً لكل صورة
    def _recognizer(_image: object) -> list[tuple[str, float]]:
        return [("أ ب ج 1234", 0.88)]

    ocr = OCRService(recognize_fn=_recognizer)
    from app.core.plate_reader import PlateCrop

    crops = [PlateCrop(0, (40.0, 70.0, 60.0, 85.0)), PlateCrop(1, (42.0, 70.0, 62.0, 85.0))]
    read = read_plate_for_crops(crops, provider, ocr)
    assert read.reads_count == 2
    assert read.confidence > 0.8
    assert "1234" in read.text
