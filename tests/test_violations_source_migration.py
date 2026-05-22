"""اختبارات ترحيل عمود source في جدول violations والحفاظ على المخالفات اليدوية."""

from __future__ import annotations

from app.core.db import Database


def test_source_column_exists_with_auto_default(tmp_db: Database) -> None:
    """بعد init_schema يجب وجود عمود source بقيمة افتراضية 'auto'."""
    cols = tmp_db.fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'violations' ORDER BY column_name"
    )
    names = [c[0] for c in cols]
    assert "source" in names
    assert "manual_user" in names


def test_insert_without_source_defaults_to_auto(tmp_db: Database) -> None:
    """الإدراج بدون تحديد source يجب أن يستخدم القيمة الافتراضية 'auto'."""
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
        ("/tmp/x.mp4", "x.mp4"),
    )
    vid_row = tmp_db.fetch_one("SELECT id FROM videos LIMIT 1")
    assert vid_row is not None
    video_id = int(vid_row[0])

    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence) "
        "VALUES (?, ?, ?, ?, ?)",
        (video_id, "speeding", 1000, 2000, 0.8),
    )
    row = tmp_db.fetch_one("SELECT source FROM violations WHERE video_id = ?", (video_id,))
    assert row is not None
    assert row[0] == "auto"


def test_manual_violations_preserved_on_reanalysis(tmp_db: Database) -> None:
    """عند حذف المخالفات التلقائية لإعادة التحليل يجب أن تبقى اليدوية محفوظة."""
    tmp_db.execute(
        "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
        ("/tmp/y.mp4", "y.mp4"),
    )
    vid_row = tmp_db.fetch_one("SELECT id FROM videos LIMIT 1")
    assert vid_row is not None
    video_id = int(vid_row[0])

    # مخالفة تلقائية
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (video_id, "speeding", 1000, 2000, 0.8, "auto"),
    )
    # مخالفة يدوية
    tmp_db.execute(
        "INSERT INTO violations (video_id, violation_type, start_ms, end_ms, confidence, source, manual_user) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (video_id, "manual_other", 3000, 4000, 1.0, "manual", "tester"),
    )

    # محاكاة إعادة التحليل: نحذف التلقائية فقط
    tmp_db.execute("DELETE FROM violations WHERE video_id = ? AND source = 'auto'", (video_id,))

    remaining = tmp_db.fetch_all(
        "SELECT violation_type, source, manual_user FROM violations WHERE video_id = ?",
        (video_id,),
    )
    assert len(remaining) == 1
    assert remaining[0][0] == "manual_other"
    assert remaining[0][1] == "manual"
    assert remaining[0][2] == "tester"
