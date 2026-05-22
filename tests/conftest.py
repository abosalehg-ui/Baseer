"""تهيئة pytest المشتركة."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.db import Database


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Iterator[Database]:
    """قاعدة بيانات مؤقتة لكل اختبار."""
    db_file = tmp_path / "test.duckdb"
    db = Database(db_file)
    db.init_schema()
    try:
        yield db
    finally:
        db.close()
