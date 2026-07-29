"""اختبارات خدمات: البحث في SQL، التجهيل، إلغاء الاستيراد، والتحليل الدفاعي."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.db import Database
from app.core.exporter import (
    anonymize_study,
    anonymize_violation_rows,
    pseudonymize_plate,
)
from app.core.library import LibraryService, VideoDetails
from app.utils.geometry import parse_metadata_json, parse_polygon_json


# ============================================
# البحث والفلترة داخل SQL
# ============================================
def _insert_video(db: Database, filename: str, source: str = "dashcam") -> int:
    db.execute(
        "INSERT INTO videos (filepath, filename, source_type, duration_sec, status) "
        "VALUES (?, ?, ?, 10.0, 'imported')",
        (f"/videos/{filename}", filename, source),
    )
    return int(db.fetch_one("SELECT id FROM videos WHERE filename = ?", (filename,))[0])


def test_list_videos_filters_by_search_in_sql(tmp_db: Database) -> None:
    """الفلترة تجري في القاعدة لا في Python بعد جلب كل الصفوف."""
    service = LibraryService(db=tmp_db)
    _insert_video(tmp_db, "highway_morning.mp4")
    _insert_video(tmp_db, "city_evening.mp4")
    _insert_video(tmp_db, "HIGHWAY_night.mp4")

    assert len(service.list_videos()) == 3
    assert len(service.list_videos(search="highway")) == 2  # غير حسّاس لحالة الأحرف
    assert len(service.list_videos(search="city")) == 1
    assert service.list_videos(search="nothing") == []


def test_search_escapes_like_wildcards(tmp_db: Database) -> None:
    """`%` و`_` تُعامَل كنص عادي لا كمحارف بدل."""
    service = LibraryService(db=tmp_db)
    _insert_video(tmp_db, "report_100%.mp4")
    _insert_video(tmp_db, "other.mp4")

    assert len(service.list_videos(search="100%")) == 1
    # `%` وحدها لا يجب أن تطابق كل شيء
    assert len(service.list_videos(search="%")) == 1


def test_search_combines_with_source_filter(tmp_db: Database) -> None:
    service = LibraryService(db=tmp_db)
    _insert_video(tmp_db, "road_a.mp4", source="dashcam")
    _insert_video(tmp_db, "road_b.mp4", source="cctv")

    assert len(service.list_videos(search="road")) == 2
    assert len(service.list_videos(search="road", source_type="cctv")) == 1


# ============================================
# تفاصيل المقطع بحقول مُسمّاة
# ============================================
def test_get_video_details_returns_named_fields(tmp_db: Database) -> None:
    """بديل `SELECT *` بمؤشرات رقمية تنكسر بصمت عند إضافة عمود."""
    service = LibraryService(db=tmp_db)
    video_id = _insert_video(tmp_db, "named.mp4")

    details = service.get_video_details(video_id)
    assert isinstance(details, VideoDetails)
    assert details.filename == "named.mp4"
    assert details.source_type == "dashcam"
    assert details.status == "imported"
    assert service.get_video_details(9999) is None


def test_video_details_survives_schema_growth(tmp_db: Database) -> None:
    """إضافة عمود جديد لا تُزيح القيم — الأعمدة مُسمّاة في الاستعلام."""
    service = LibraryService(db=tmp_db)
    video_id = _insert_video(tmp_db, "grow.mp4")
    tmp_db.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS extra_col VARCHAR")

    details = service.get_video_details(video_id)
    assert details is not None
    assert details.filename == "grow.mp4"
    assert details.status == "imported"


# ============================================
# إلغاء الاستيراد كنتيجة عادية لا استثناء
# ============================================
def _fake_meta(path):
    from app.utils.video_utils import VideoMetadata

    return VideoMetadata(
        filepath=Path(path),
        duration_sec=5.0,
        width=640,
        height=480,
        fps=30.0,
        codec="h264",
        file_size_mb=1.0,
        recorded_at=None,
    )


def test_import_cancellation_returns_partial_report(tmp_path: Path, tmp_db: Database) -> None:
    """الإلغاء يُنهي بتقرير جزئي `cancelled=True` لا برفع استثناء."""
    service = LibraryService(db=tmp_db)
    for i in range(5):
        (tmp_path / f"clip{i}.mp4").write_bytes(bytes([i]) * 512)

    processed: list[str] = []

    def _stop_after_two() -> bool:
        return len(processed) >= 2

    def _progress(_current, _total, filename):
        processed.append(filename)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *a, **k: a[1]),
        patch("app.core.library.perceptual_hash_from_image_path", return_value="a" * 64),
    ):
        report = service.import_paths(
            [tmp_path], progress_cb=_progress, should_stop=_stop_after_two
        )

    assert report.cancelled is True
    assert len(report.imported) == 2
    assert len(report.skipped) == 3  # لم تُعالَج
    assert service.count_videos() == 2


def test_import_without_stop_callback_completes(tmp_path: Path, tmp_db: Database) -> None:
    service = LibraryService(db=tmp_db)
    for i in range(3):
        (tmp_path / f"v{i}.mp4").write_bytes(bytes([i + 50]) * 512)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *a, **k: a[1]),
        patch("app.core.library.perceptual_hash_from_image_path", return_value="b" * 64),
    ):
        report = service.import_paths([tmp_path])

    assert report.cancelled is False
    assert len(report.imported) == 3


# ============================================
# أسماء الصور المصغّرة حتمية
# ============================================
def test_thumbnail_filename_is_deterministic(tmp_path: Path, tmp_db: Database) -> None:
    """نفس المسار يعطي نفس اسم الـthumbnail في كل تشغيل.

    `hash()` على النصوص مُلَح عشوائياً لكل عملية، فالاسم كان يتغيّر كل جلسة
    ويترك ملفات يتيمة تتراكم.
    """
    service = LibraryService(db=tmp_db)
    video = tmp_path / "same.mp4"
    video.write_bytes(b"x" * 128)

    captured: list[Path] = []

    def _capture(_src, dst, **_kwargs):
        captured.append(Path(dst))
        return dst

    with patch("app.core.library.generate_thumbnail", side_effect=_capture):
        service._build_thumbnail(video, _fake_meta(video))
        service._build_thumbnail(video, _fake_meta(video))

    assert len(captured) == 2
    assert captured[0] == captured[1]
    assert "same_" in captured[0].name


# ============================================
# التجهيل
# ============================================
def test_pseudonymize_plate_is_stable_and_irreversible() -> None:
    a = pseudonymize_plate("ا ب ج 1234")
    b = pseudonymize_plate("ا ب ج 1234")
    c = pseudonymize_plate("د ه و 5678")

    assert a == b, "نفس اللوحة يجب أن تعطي نفس الرمز (لتبقى التجميعات ممكنة)"
    assert a != c
    assert a.startswith("PLATE-")
    assert "1234" not in a
    assert pseudonymize_plate(None) is None
    assert pseudonymize_plate("") is None


def test_pseudonymize_plate_salt_changes_output() -> None:
    assert pseudonymize_plate("ا ب ج 1234", salt="s1") != pseudonymize_plate(
        "ا ب ج 1234", salt="s2"
    )


def test_anonymize_study_replaces_plates() -> None:
    study = {
        "violations": [
            {"id": 1, "license_plate": "ا ب ج 1234"},
            {"id": 2, "license_plate": None},
        ]
    }
    out = anonymize_study(study)
    assert out["anonymized"] is True
    assert out["violations"][0]["license_plate"].startswith("PLATE-")
    assert out["violations"][1]["license_plate"] is None
    # الأصل لم يُعدَّل
    assert study["violations"][0]["license_plate"] == "ا ب ج 1234"


def test_anonymize_violation_rows_keeps_other_fields() -> None:
    from app.core.dashboard import ViolationRow

    row = ViolationRow(
        id=1,
        video_id=2,
        video_filename="a.mp4",
        violation_type="speeding",
        violation_type_ar="السرعة الزائدة",
        start_ms=0,
        end_ms=100,
        confidence=0.9,
        license_plate="ا ب ج 1234",
        review_status="pending",
        notes="ملاحظة",
        created_at=None,
    )
    (out,) = anonymize_violation_rows([row])
    assert out.license_plate.startswith("PLATE-")
    assert out.violation_type_ar == "السرعة الزائدة"
    assert out.confidence == 0.9
    assert row.license_plate == "ا ب ج 1234"  # الأصل سليم


# ============================================
# التحليل الدفاعي للـJSON المخزَّن
# ============================================
@pytest.mark.parametrize(
    "raw",
    [None, "", "not-json", "{}", "[[1]]", '["x"]', '[{"a":1}]', "[[1,2,3]]"],
)
def test_parse_polygon_json_never_raises(raw) -> None:
    """صف تالف يجب ألا يُسقط استخراج المخالفات — يُرجع ما أمكن أو []."""
    result = parse_polygon_json(raw)
    assert isinstance(result, list)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in result)


def test_parse_polygon_json_valid_input() -> None:
    assert parse_polygon_json("[[1, 2], [3.5, 4]]") == [(1.0, 2.0), (3.5, 4.0)]
    # نقطة تالفة وسط نقاط سليمة تُتخطّى وحدها
    assert parse_polygon_json('[[1, 2], "bad", [3, 4]]') == [(1.0, 2.0), (3.0, 4.0)]


def test_parse_metadata_json() -> None:
    assert parse_metadata_json('{"k": 1}') == {"k": 1}
    assert parse_metadata_json("[1,2]") is None
    assert parse_metadata_json("broken") is None
    assert parse_metadata_json(None) is None


def test_zones_survive_corrupted_polygon(tmp_db: Database) -> None:
    """منطقة بـpolygon تالف تُقرأ بقائمة نقاط فارغة بدل انهيار."""
    from app.core.rules import load_zones_from_db

    tmp_db.execute("INSERT INTO videos (filepath, filename) VALUES ('/v/z.mp4', 'z.mp4')")
    vid = int(tmp_db.fetch_one("SELECT id FROM videos")[0])
    tmp_db.execute(
        "INSERT INTO zones (video_id, zone_type, polygon, metadata) VALUES (?, ?, ?, ?)",
        (vid, "stop_line", "{{ تالف", "أيضاً تالف"),
    )
    zones = load_zones_from_db(vid, tmp_db)
    assert len(zones) == 1
    assert zones[0].polygon == []
    assert zones[0].metadata is None
