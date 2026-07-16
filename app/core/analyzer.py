"""خدمة التحليل — inference عبر YOLO وتخزين الكشوفات في DB."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.constants import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_IOU_THRESHOLD, VideoStatus
from app.core.db import Database, get_database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    """كشف واحد في فريم واحد."""

    frame_no: int
    timestamp_ms: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    track_id: int | None = None


@dataclass(frozen=True)
class AnalysisConfig:
    """إعدادات تشغيل التحليل."""

    model_path: Path
    confidence: float = DEFAULT_CONFIDENCE_THRESHOLD
    iou: float = DEFAULT_IOU_THRESHOLD
    imgsz: int = 640
    device: str | int = 0
    frame_stride: int = 1
    max_frames: int | None = None
    # التتبع مفعّل افتراضياً: بدون track_id تُهمَل كل الكشوفات في build_tracks
    # وتعود كل الكواشف بصفر مخالفات (كلها track-based).
    enable_tracking: bool = True


@dataclass
class AnalysisResult:
    """ملخّص ناتج تحليل مقطع واحد."""

    video_id: int
    total_frames: int
    detections_count: int


# نوع الـ callable الذي يُجري الاستدلال الفعلي على ملف فيديو
# نأخذه كـ dependency لتسهيل الـ mocking في الاختبارات.
InferenceCallable = Callable[[Path, AnalysisConfig], Iterable[Detection]]


class AnalyzerService:
    """خدمة استدلال على المقاطع وتخزين الكشوفات."""

    def __init__(
        self,
        *,
        db: Database | None = None,
        settings: AppSettings | None = None,
        inference_fn: InferenceCallable | None = None,
        ocr_service: Any = None,
        frame_provider_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db = db or get_database(self._settings)
        self._inference_fn = inference_fn
        # اختياريان لقراءة اللوحات — قابلان للحقن للاختبار. عند None يُبنيان كسولاً
        # عند الحاجة فقط (وجود كشوفات license_plate + ملف فيديو).
        self._ocr_service = ocr_service
        self._frame_provider_factory = frame_provider_factory

    # ============================================
    # واجهة عامة
    # ============================================
    def analyze_video(self, video_id: int, config: AnalysisConfig) -> AnalysisResult:
        """يُجري الاستدلال على مقطع ويخزّن الكشوفات في DB."""
        video_row = self._db.fetch_one("SELECT id, filepath FROM videos WHERE id = ?", (video_id,))
        if video_row is None:
            raise ValueError(f"لا يوجد مقطع بالمعرّف {video_id}")
        filepath = Path(str(video_row[1]))
        if not filepath.exists():
            raise FileNotFoundError(f"الملف غير موجود: {filepath}")

        inference = self._inference_fn or _default_inference
        detections = list(inference(filepath, config))
        self._store_detections(video_id, detections)
        self._update_video_status(video_id, VideoStatus.PRELABELED)

        frames = len({d.frame_no for d in detections})
        logger.info(
            "تم تحليل المقطع %s: %d كشف عبر %d فريم", filepath.name, len(detections), frames
        )
        return AnalysisResult(
            video_id=video_id, total_frames=frames, detections_count=len(detections)
        )

    def analyze_batch(
        self,
        video_ids: list[int],
        config: AnalysisConfig,
        *,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> list[AnalysisResult]:
        """يحلّل دفعة من المقاطع."""
        results: list[AnalysisResult] = []
        for index, vid in enumerate(video_ids, start=1):
            if progress_cb is not None:
                progress_cb(index, len(video_ids), vid)
            try:
                results.append(self.analyze_video(vid, config))
            except Exception as exc:  # noqa: BLE001
                logger.exception("فشل تحليل المقطع %d", vid)
                _ = exc
        return results

    def list_unanalyzed_video_ids(self) -> list[int]:
        """يعيد معرفات المقاطع التي لم تُحلَّل بعد."""
        rows = self._db.fetch_all(
            "SELECT id FROM videos WHERE status = ? ORDER BY id",
            (VideoStatus.IMPORTED.value,),
        )
        return [int(r[0]) for r in rows]

    def detections_for_video(self, video_id: int) -> list[Detection]:
        """يعيد كل الكشوفات المخزَّنة لمقطع."""
        rows = self._db.fetch_all(
            "SELECT frame_no, timestamp_ms, class_name, confidence, "
            "bbox_x1, bbox_y1, bbox_x2, bbox_y2, track_id "
            "FROM detections WHERE video_id = ? ORDER BY frame_no, id",
            (video_id,),
        )
        return [
            Detection(
                frame_no=int(r[0]),
                timestamp_ms=int(r[1]),
                class_name=str(r[2]),
                confidence=float(r[3]),
                bbox=(float(r[4]), float(r[5]), float(r[6]), float(r[7])),
                track_id=int(r[8]) if r[8] is not None else None,
            )
            for r in rows
        ]

    def extract_violations(self, video_id: int, *, fps: float | None = None) -> int:
        """يُشغّل محرك القواعد على كشوفات مقطع ويخزّن المخالفات في DB.

        يستدعي بعد `analyze_video()` لتوليد جدول `violations` للمقطع.
        يُرجع عدد المخالفات المخزَّنة.
        """
        from app.core.calibration import CalibrationService
        from app.core.detectors import FollowingDistanceDetector, HighBeamDetector
        from app.core.rules import (
            SpeedingDetector,
            all_default_detectors,
            load_zones_from_db,
            run_detectors,
        )

        detections = self.detections_for_video(video_id)
        if not detections:
            return 0
        actual_fps = fps if fps is not None else self._fps_for_video(video_id)
        zones = load_zones_from_db(video_id, self._db)

        # نُضيف الكواشف التي تحتاج معايرة أو ملف فيديو فقط عند توفرها
        detectors = all_default_detectors()
        calibration = CalibrationService(db=self._db).get_calibration(video_id)
        if calibration is not None and calibration.meters_per_px > 0:
            # كلا الكاشفين يحتاجان المعايرة نفسها (meters_per_px)
            detectors.append(SpeedingDetector(meters_per_px=calibration.meters_per_px))
            detectors.append(FollowingDistanceDetector(meters_per_px=calibration.meters_per_px))
        video_filepath = self._video_filepath(video_id)
        if video_filepath is not None and Path(video_filepath).exists():
            detectors.append(HighBeamDetector(video_path=video_filepath))

        candidates = run_detectors(detections, zones, actual_fps, detectors=detectors)

        # قراءة لوحات المركبات المخالِفة (اختياري — يُتخطّى بلا كشوفات لوحات/فيديو)
        plates = self._read_plates(candidates, detections, video_filepath)

        # نحذف فقط المخالفات التلقائية حتى تبقى المخالفات اليدوية محفوظة بعد إعادة التحليل
        self._db.execute(
            "DELETE FROM violations WHERE video_id = ? AND source = 'auto'", (video_id,)
        )
        rows = [
            (
                video_id,
                c.violation_type.value,
                c.start_ms,
                c.end_ms,
                c.confidence,
                c.track_id,
                json.dumps(c.evidence_frames),
                plates.get(i, (None, None))[0],
                plates.get(i, (None, None))[1],
                c.notes,
                "auto",
            )
            for i, c in enumerate(candidates)
        ]
        if rows:
            self._db.executemany(
                """
                INSERT INTO violations
                    (video_id, violation_type, start_ms, end_ms, confidence,
                     track_id, evidence_frames, license_plate, plate_conf, notes, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        self._db.execute(
            "UPDATE videos SET status = ? WHERE id = ?",
            (VideoStatus.ANALYZED.value, video_id),
        )
        logger.info("تم استخراج %d مخالفة من المقطع %d", len(rows), video_id)
        return len(rows)

    def _read_plates(
        self,
        candidates: list[Any],
        detections: list[Detection],
        video_filepath: str | None,
    ) -> dict[int, tuple[str | None, float | None]]:
        """يقرأ لوحة كل مخالفة لها track (فهرس المخالفة → (نص، ثقة)).

        يُتخطّى بصمت إن لم توجد كشوفات لوحات أو تعذّر بناء مزوّد الإطارات — فلا
        يؤثّر على المسار الشائع (بلا فيديو/لوحات) ولا يبطئ الاختبارات.
        """
        has_plate_dets = any(d.class_name == "license_plate" for d in detections)
        if not has_plate_dets:
            return {}
        provider = self._build_frame_provider(video_filepath)
        if provider is None:
            return {}

        from app.core.plate_reader import plate_detections_for_track, read_plate_for_crops
        from app.core.rules import build_tracks, detections_by_frame

        tracks_by_id = {t.track_id: t for t in build_tracks(detections)}
        by_frame = detections_by_frame(detections)
        ocr = self._resolve_ocr_service()

        out: dict[int, tuple[str | None, float | None]] = {}
        try:
            for i, cand in enumerate(candidates):
                track = tracks_by_id.get(getattr(cand, "track_id", None))
                if track is None:
                    continue
                track_bboxes = {d.frame_no: d.bbox for d in track.detections}
                crops = plate_detections_for_track(track_bboxes, by_frame)
                if not crops:
                    continue
                read = read_plate_for_crops(crops, provider, ocr)
                if read.text and read.confidence > 0:
                    out[i] = (read.text, float(read.confidence))
        finally:
            if self._frame_provider_factory is None:
                # أنشأناه داخلياً — نغلقه
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
        return out

    def _build_frame_provider(self, video_filepath: str | None) -> Any:
        if self._frame_provider_factory is not None:
            return self._frame_provider_factory(video_filepath or "")
        if video_filepath is None or not Path(video_filepath).exists():
            return None
        try:
            from app.core.frame_sampler import FrameSampler

            return FrameSampler(video_filepath)
        except Exception as exc:  # noqa: BLE001
            logger.warning("تعذّر فتح الفيديو لقراءة اللوحات: %s", exc)
            return None

    def _resolve_ocr_service(self) -> Any:
        if self._ocr_service is not None:
            return self._ocr_service
        from app.core.ocr import OCRService

        self._ocr_service = OCRService()
        return self._ocr_service

    def _fps_for_video(self, video_id: int) -> float:
        row = self._db.fetch_one("SELECT fps FROM videos WHERE id = ?", (video_id,))
        return float(row[0]) if row and row[0] else 30.0

    def _video_filepath(self, video_id: int) -> str | None:
        row = self._db.fetch_one("SELECT filepath FROM videos WHERE id = ?", (video_id,))
        return str(row[0]) if row and row[0] else None

    # ============================================
    # تخزين داخلي
    # ============================================
    def _store_detections(self, video_id: int, detections: Iterable[Detection]) -> None:
        """يحذف الكشوفات السابقة ويُدرج الجديدة دفعةً واحدة."""
        self._db.execute("DELETE FROM detections WHERE video_id = ?", (video_id,))
        rows = [
            (
                video_id,
                d.frame_no,
                d.timestamp_ms,
                d.class_name,
                d.confidence,
                d.bbox[0],
                d.bbox[1],
                d.bbox[2],
                d.bbox[3],
                d.track_id,
            )
            for d in detections
        ]
        if not rows:
            return
        self._db.executemany(
            """
            INSERT INTO detections
                (video_id, frame_no, timestamp_ms, class_name, confidence,
                 bbox_x1, bbox_y1, bbox_x2, bbox_y2, track_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _update_video_status(self, video_id: int, status: VideoStatus) -> None:
        self._db.execute("UPDATE videos SET status = ? WHERE id = ?", (status.value, video_id))


def _default_inference(filepath: Path, config: AnalysisConfig) -> Iterable[Detection]:
    """مغلِّف ultralytics — يُستدعى فقط عند الاستخدام الحقيقي.

    Lazy import حتى لا نُحمّل torch في كل مرة يُستورد فيها المحلِّل (للاختبارات والـ CI).
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("يحتاج ultralytics — ثبّت requirements.txt") from exc

    model = YOLO(str(config.model_path))
    stream = model.track if config.enable_tracking else model.predict
    # نُمرّر vid_stride لـ ultralytics ليتخطّى الإطارات على مستوى فك التشفير/الاستدلال
    # بدل الاستدلال على كل الإطارات ثم رميها — توفير مباشر بنسبة stride.
    stride = max(1, config.frame_stride)
    results = stream(
        source=str(filepath),
        conf=config.confidence,
        iou=config.iou,
        imgsz=config.imgsz,
        device=config.device,
        vid_stride=stride,
        stream=True,
        verbose=False,
    )

    fps = _probe_fps(filepath)
    for kept_idx, frame_result in enumerate(results):
        if config.max_frames and kept_idx >= config.max_frames:
            break
        # ultralytics يُرجع فقط الإطارات المُبقاة؛ رقم الإطار الحقيقي = المؤشر × stride
        real_frame_no = kept_idx * stride
        yield from _detections_from_frame(frame_result, real_frame_no, fps)


def _probe_fps(filepath: Path) -> float:
    """يحاول استخراج fps المقطع — fallback إلى 30 عند الفشل."""
    try:
        from app.utils.video_utils import extract_metadata

        meta = extract_metadata(filepath)
        return float(meta.fps or 30.0)
    except Exception:  # noqa: BLE001
        return 30.0


def _detections_from_frame(frame_result: Any, frame_idx: int, fps: float) -> list[Detection]:
    """يحوّل ناتج ultralytics لإطار واحد إلى قائمة Detection."""
    boxes = getattr(frame_result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    names = frame_result.names if hasattr(frame_result, "names") else {}
    xyxy = boxes.xyxy.cpu().numpy()
    conf = boxes.conf.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    track_ids = (
        boxes.id.cpu().numpy().astype(int) if getattr(boxes, "id", None) is not None else None
    )

    timestamp_ms = int(1000 * frame_idx / max(fps, 1e-6))
    out: list[Detection] = []
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = xyxy[i].tolist()
        out.append(
            Detection(
                frame_no=frame_idx,
                timestamp_ms=timestamp_ms,
                class_name=names.get(int(cls[i]), str(int(cls[i]))),
                confidence=float(conf[i]),
                bbox=(float(x1), float(y1), float(x2), float(y2)),
                track_id=int(track_ids[i]) if track_ids is not None else None,
            )
        )
    return out


__all__ = [
    "AnalysisConfig",
    "AnalysisResult",
    "AnalyzerService",
    "Detection",
    "InferenceCallable",
]


# يُستخدم في exporter
def detections_grouped_by_frame(detections: Iterable[Detection]) -> dict[int, list[Detection]]:
    """يُجمّع الكشوفات بحسب رقم الفريم."""
    groups: dict[int, list[Detection]] = {}
    for d in detections:
        groups.setdefault(d.frame_no, []).append(d)
    return groups


def detections_to_json(detections: Iterable[Detection]) -> str:
    """يُسلسل الكشوفات إلى JSON."""
    return json.dumps(
        [
            {
                "frame_no": d.frame_no,
                "timestamp_ms": d.timestamp_ms,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox": d.bbox,
                "track_id": d.track_id,
            }
            for d in detections
        ],
        ensure_ascii=False,
    )
