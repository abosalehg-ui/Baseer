"""اختبار التعافي التلقائي من ملف WAL فاسد عند فتح DuckDB."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from app.core.db import Database


def test_normal_open_does_not_touch_existing_wal(tmp_path: Path) -> None:
    """فتح ناجح لا يجب أن يلمس ملف الـwal أو ينشئ نسخاً احتياطية."""
    db_file = tmp_path / "test.duckdb"
    db = Database(db_file)
    db.init_schema()
    db.close()

    db2 = Database(db_file)
    try:
        db2.init_schema()
    finally:
        db2.close()

    backups = list(tmp_path.glob("*.wal.broken-*"))
    assert backups == []


def test_wal_error_triggers_recovery(tmp_path: Path) -> None:
    """عند فشل فتح القاعدة بخطأ ذكر "WAL"، يُنحَّى ملف الـwal وتعاد المحاولة."""
    db_file = tmp_path / "test.duckdb"
    # نُنشئ قاعدة بيانات حقيقية مع جدول
    seed = Database(db_file)
    seed.init_schema()
    seed.close()
    # ثم نضع ملف wal اصطناعي بجانبها
    wal_file = db_file.with_suffix(".duckdb.wal")
    wal_file.write_bytes(b"fake wal content")

    original_connect = duckdb.connect
    call_count = {"n": 0}

    def fake_connect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise duckdb.Error("INTERNAL Error: Failure while replaying WAL file: dummy")
        return original_connect(*args, **kwargs)

    with patch("app.core.db.duckdb.connect", side_effect=fake_connect):
        db = Database(db_file)

    try:
        # نفّذ استعلاماً للتأكد أن الاتصال شغّال
        db.init_schema()
        assert db.list_tables()  # غير فارغة
    finally:
        db.close()

    # الـwal تم نقله إلى backup
    backups = list(tmp_path.glob("*.wal.broken-*"))
    assert len(backups) == 1
    assert not wal_file.exists()


def test_non_wal_error_propagates(tmp_path: Path) -> None:
    """خطأ غير متعلّق بـwal يجب أن يُرفع كما هو (لا نُخفيه)."""
    db_file = tmp_path / "test.duckdb"
    seed = Database(db_file)
    seed.close()
    wal_file = db_file.with_suffix(".duckdb.wal")
    wal_file.write_bytes(b"x")

    def always_fail(*args, **kwargs):
        raise duckdb.Error("Some other error completely unrelated")

    with patch("app.core.db.duckdb.connect", side_effect=always_fail):
        with pytest.raises(duckdb.Error, match="Some other error"):
            Database(db_file)

    # ولا نسخة احتياطية أُنشئت لأن السبب ليس WAL
    backups = list(tmp_path.glob("*.wal.broken-*"))
    assert backups == []
    # الـwal الأصلي لا يزال موجوداً
    assert wal_file.exists()
