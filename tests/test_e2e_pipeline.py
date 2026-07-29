"""اختبار قبول للمسار الكامل: استيراد → استدلال → استخراج مخالفات → تصدير.

هذا الاختبار **حارس ضد فجوات التكامل**: كل الوحدات كانت مغطّاة جيداً بينما لا
شيء يتحقق من أنها موصولة ببعضها في مسار الإنتاج. مراجعتان متتاليتان أوصتا به.

يعمل بلا GPU وبلا ultralytics وبلا ملف فيديو حقيقي: الاستدلال يُحقن كـcallable،
وقارئ الإطارات والـOCR يُحقنان أيضاً. ما يُختبَر هو **الأسلاك** لا النماذج.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.constants import ViolationType
from app.core.analyzer import AnalysisConfig, AnalyzerService, Detection
from app.core.calibration import CalibrationService
from app.core.dashboard import DashboardService
from app.core.db import Database
from app.core.exporter import build_study, export_csv, export_json
from app.core.zones import ZoneService

FPS = 10.0


# ============================================
# مزوّدات مُحقونة
# ============================================
class _FakeFrameProvider:
    """يُرجع إطاراً اصطناعياً لأي رقم — يكفي لقراءة اللوحات."""

    def __init__(self, _path: str) -> None:
        self.closed = False

    def get_frame(self, frame_no: int) -> np.ndarray:
        return np.full((120, 200, 3), (frame_no % 200) + 20, dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


class _FakeOCR:
    """OCR ثابت — يتيح اختبار ملء عمود license_plate بلا PaddleOCR."""

    def read_track_plate_images(self, images, *, min_confidence: float = 0.3):
        from app.core.ocr import PlateRead

        return PlateRead(text="ا ب ج 1234", confidence=0.91, reads_count=len(images))


def _synthetic_detections() -> list[Detection]:
    """مركبة تعبر خط توقف والإشارة حمراء + لوحة داخل صندوقها.

    الحركة رأسية من y≈20 إلى y≈120 عبر 30 إطاراً، وخط التوقف عند y=70.
    """
    dets: list[Detection] = []
    for frame in range(30):
        y = 20 + frame * 4
        ts = int(frame * 1000 / FPS)
        dets.append(
            Detection(
                frame_no=frame,
                timestamp_ms=ts,
                class_name="vehicle",
                confidence=0.9,
                bbox=(80.0, float(y), 130.0, float(y + 30)),
                track_id=1,
            )
        )
        # لوحة داخل صندوق المركبة (مركزها داخل الـbbox)
        dets.append(
            Detection(
                frame_no=frame,
                timestamp_ms=ts,
                class_name="license_plate",
                confidence=0.8,
                bbox=(95.0, float(y + 18), 118.0, float(y + 28)),
                track_id=2,
            )
        )
        # إشارة حمراء ظاهرة طوال المقطع
        dets.append(
            Detection(
                frame_no=frame,
                timestamp_ms=ts,
                class_name="traffic_light_red",
                confidence=0.95,
                bbox=(10.0, 5.0, 25.0, 25.0),
                track_id=3,
            )
        )
    return dets


@pytest.fixture()
def video_file(tmp_path: Path) -> Path:
    """ملف بديل عن الفيديو — وجوده وحده هو ما تفحصه الخدمة."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 1024)
    return path


def _seed_video(db: Database, path: Path) -> int:
    db.execute(
        "INSERT INTO videos (filepath, filename, source_type, fps, width, height, "
        "recorded_at, status) VALUES (?, ?, 'dashcam', ?, 200, 120, "
        "TIMESTAMP '2026-03-01 08:30:00', 'imported')",
        (str(path), path.name, FPS),
    )
    return int(db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (str(path),))[0])


# ============================================
# الاختبار الرئيسي
# ============================================
def test_full_pipeline_import_to_export(tmp_db: Database, video_file: Path, tmp_path: Path) -> None:
    """المسار كامل ينتج مخالفة حقيقية ولوحة مقروءة ويُصدَّر بنجاح."""
    video_id = _seed_video(tmp_db, video_file)
    detections = _synthetic_detections()

    service = AnalyzerService(
        db=tmp_db,
        inference_fn=lambda _path, _cfg: detections,
        ocr_service=_FakeOCR(),
        frame_provider_factory=lambda path: _FakeFrameProvider(path),
    )

    # 1) الاستدلال يخزّن الكشوفات ويحدّث الحالة
    result = service.analyze_video(video_id, AnalysisConfig(model_path=Path("fake.pt")))
    assert result.detections_count == len(detections)
    assert service.detections_for_video(video_id)

    # 2) منطقة خط التوقف — بدونها يعود كاشف الإشارة الحمراء فارغاً بصمت
    ZoneService(db=tmp_db).add_zone(video_id, "stop_line", [(0.0, 70.0), (200.0, 70.0)])

    # الجاهزية تعكس ما هو متاح فعلاً
    readiness = service.readiness(video_id)
    assert readiness.has_tracks is True
    assert "stop_line" in readiness.zone_types
    assert readiness.has_calibration is False
    assert any("السرعة" in b for b in readiness.blocked_detectors)

    # 3) استخراج المخالفات
    count = service.extract_violations(video_id, fps=FPS)
    assert count >= 1, "المسار الكامل يجب أن يُنتج مخالفة واحدة على الأقل"
    assert service.last_detector_failures == []

    rows = tmp_db.fetch_all(
        "SELECT violation_type, source, license_plate FROM violations WHERE video_id = ?",
        (video_id,),
    )
    types = {r[0] for r in rows}
    assert ViolationType.RED_LIGHT_RUNNING.value in types
    assert all(r[1] == "auto" for r in rows)
    # العمود الذي كان يبقى فارغاً دائماً في الخط التلقائي
    assert any(r[2] == "ا ب ج 1234" for r in rows), "قراءة اللوحة لم تصل إلى الجدول"

    # 4) الداشبورد يقرأ ما كُتب
    dashboard = DashboardService(db=tmp_db)
    violations = dashboard.list_violations()
    assert len(violations) == len(rows)
    assert dashboard.count_violations() == len(rows)

    # 5) التصدير يعمل — والتجهيل هو الافتراضي في الدراسة المُعدّة للنشر
    study = build_study(dashboard, anonymize=True)
    assert study["anonymized"] is True
    assert all(
        v["license_plate"] is None or v["license_plate"].startswith("PLATE-")
        for v in study["violations"]
    )

    json_path = export_json(study, tmp_path / "study.json")
    assert json.loads(json_path.read_text(encoding="utf-8"))["kpis"]["total_violations"] == len(
        rows
    )

    csv_path = export_csv(violations, tmp_path / "violations.csv")
    assert csv_path.exists() and csv_path.stat().st_size > 0


def test_pipeline_reanalysis_preserves_manual_violations(
    tmp_db: Database, video_file: Path
) -> None:
    """إعادة التحليل تستبدل التلقائية وتُبقي اليدوية."""
    video_id = _seed_video(tmp_db, video_file)
    service = AnalyzerService(
        db=tmp_db, inference_fn=lambda _p, _c: _synthetic_detections(), ocr_service=_FakeOCR()
    )
    service.analyze_video(video_id, AnalysisConfig(model_path=Path("fake.pt")))
    ZoneService(db=tmp_db).add_zone(video_id, "stop_line", [(0.0, 70.0), (200.0, 70.0)])
    service.extract_violations(video_id, fps=FPS)

    DashboardService(db=tmp_db).insert_manual_violation(
        video_id=video_id,
        violation_type=ViolationType.MANUAL_OTHER.value,
        start_ms=100,
        end_ms=900,
        evidence_frames_json="[]",
        license_plate=None,
        notes="[manual] مراجعة بشرية",
    )

    before = tmp_db.fetch_one(
        "SELECT COUNT(*) FROM violations WHERE video_id = ? AND source = 'manual'", (video_id,)
    )[0]
    service.extract_violations(video_id, fps=FPS)
    after = tmp_db.fetch_one(
        "SELECT COUNT(*) FROM violations WHERE video_id = ? AND source = 'manual'", (video_id,)
    )[0]
    assert before == after == 1


def test_pipeline_with_calibration_enables_speed_detector(
    tmp_db: Database, video_file: Path
) -> None:
    """وجود المعايرة يُفعّل كاشف السرعة الذي يبقى معطّلاً بدونها."""
    video_id = _seed_video(tmp_db, video_file)
    service = AnalyzerService(
        db=tmp_db, inference_fn=lambda _p, _c: _synthetic_detections(), ocr_service=_FakeOCR()
    )
    service.analyze_video(video_id, AnalysisConfig(model_path=Path("fake.pt")))

    assert service.readiness(video_id).has_calibration is False
    # 2 متر لكل بكسل → 4px/إطار × 10fps = 80 م/ث ≈ 288 كم/س (فوق الحد 80)
    CalibrationService(db=tmp_db).save_calibration(video_id, [(0.0, 0.0), (10.0, 0.0)], [20.0])
    assert service.readiness(video_id).has_calibration is True

    service.extract_violations(video_id, fps=FPS)
    types = {
        r[0]
        for r in tmp_db.fetch_all(
            "SELECT violation_type FROM violations WHERE video_id = ?", (video_id,)
        )
    }
    assert ViolationType.SPEEDING.value in types


def test_extract_violations_is_atomic_on_failure(tmp_db: Database, video_file: Path) -> None:
    """فشل الإدراج لا يترك المقطع بلا مخالفات بعد حذف القديمة."""
    video_id = _seed_video(tmp_db, video_file)
    service = AnalyzerService(
        db=tmp_db, inference_fn=lambda _p, _c: _synthetic_detections(), ocr_service=_FakeOCR()
    )
    service.analyze_video(video_id, AnalysisConfig(model_path=Path("fake.pt")))
    ZoneService(db=tmp_db).add_zone(video_id, "stop_line", [(0.0, 70.0), (200.0, 70.0)])
    service.extract_violations(video_id, fps=FPS)

    original = tmp_db.fetch_all(
        "SELECT id FROM violations WHERE video_id = ? AND source = 'auto'", (video_id,)
    )
    assert original, "نحتاج مخالفات موجودة لاختبار الذرّية"

    # نُفشل الإدراج داخل المعاملة
    real_executemany = tmp_db.executemany

    def _boom(sql, rows):
        if "INSERT INTO violations" in sql:
            raise RuntimeError("انقطاع محاكى أثناء الإدراج")
        return real_executemany(sql, rows)

    tmp_db.executemany = _boom  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            service.extract_violations(video_id, fps=FPS)
    finally:
        tmp_db.executemany = real_executemany  # type: ignore[method-assign]

    # المعاملة تراجعت: المخالفات القديمة ما زالت موجودة
    after = tmp_db.fetch_all(
        "SELECT id FROM violations WHERE video_id = ? AND source = 'auto'", (video_id,)
    )
    assert len(after) == len(original), "الحذف طُبِّق رغم فشل الإدراج — المعاملة لم تعمل"
