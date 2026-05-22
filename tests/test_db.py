"""اختبارات وحدة قاعدة البيانات."""

from __future__ import annotations

from app.core.db import Database

EXPECTED_TABLES = {
    "videos",
    "scenes",
    "detections",
    "violations",
    "calibrations",
    "zones",
    "exports",
}


def test_schema_creates_all_tables(tmp_db: Database) -> None:
    tables = set(tmp_db.list_tables())
    assert EXPECTED_TABLES.issubset(tables)


def test_table_exists_returns_true_for_known_table(tmp_db: Database) -> None:
    assert tmp_db.table_exists("videos") is True
    assert tmp_db.table_exists("does_not_exist") is False


def test_insert_and_fetch_video(tmp_db: Database) -> None:
    tmp_db.execute(
        """
        INSERT INTO videos (filepath, filename, source_type, duration_sec, width, height, fps)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("/tmp/sample.mp4", "sample.mp4", "dashcam", 12.5, 1920, 1080, 29.97),
    )
    row = tmp_db.fetch_one(
        "SELECT filename, source_type, duration_sec FROM videos WHERE filepath = ?",
        ("/tmp/sample.mp4",),
    )
    assert row is not None
    assert row[0] == "sample.mp4"
    assert row[1] == "dashcam"
    assert row[2] == 12.5


def test_unique_filepath_constraint(tmp_db: Database) -> None:
    import duckdb

    tmp_db.execute(
        "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
        ("/tmp/a.mp4", "a.mp4"),
    )
    try:
        tmp_db.execute(
            "INSERT INTO videos (filepath, filename) VALUES (?, ?)",
            ("/tmp/a.mp4", "a.mp4"),
        )
    except duckdb.ConstraintException:
        return
    raise AssertionError("توقعنا ConstraintException عند إدراج filepath مكرر")


def test_source_type_check_constraint_rejects_invalid_value(tmp_db: Database) -> None:
    import duckdb

    try:
        tmp_db.execute(
            "INSERT INTO videos (filepath, filename, source_type) VALUES (?, ?, ?)",
            ("/tmp/bad.mp4", "bad.mp4", "invalid_source"),
        )
    except duckdb.ConstraintException:
        return
    raise AssertionError("توقعنا ConstraintException عند source_type غير مدعوم")


def test_indexes_exist(tmp_db: Database) -> None:
    rows = tmp_db.fetch_all(
        "SELECT index_name FROM duckdb_indexes() WHERE table_name IN ('detections', 'violations')"
    )
    index_names = {row[0] for row in rows}
    assert "idx_det_video" in index_names
    assert "idx_viol_type" in index_names


def test_init_schema_is_idempotent(tmp_db: Database) -> None:
    tmp_db.init_schema()
    tmp_db.init_schema()
    assert tmp_db.table_exists("videos")
