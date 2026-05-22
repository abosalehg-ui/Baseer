"""اتصال DuckDB وإدارة المخطط."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb

from app.config import AppSettings, get_settings

# ============================================
# تعريف المخطط (Schema DDL)
# ============================================
SCHEMA_STATEMENTS: tuple[str, ...] = (
    # تسلسلات المعرفات
    "CREATE SEQUENCE IF NOT EXISTS seq_videos_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_scenes_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_detections_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_violations_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_calibrations_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_zones_id START 1;",
    "CREATE SEQUENCE IF NOT EXISTS seq_exports_id START 1;",
    # المقاطع
    """
    CREATE TABLE IF NOT EXISTS videos (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_videos_id'),
        filepath        VARCHAR NOT NULL UNIQUE,
        filename        VARCHAR NOT NULL,
        source_type     VARCHAR CHECK (source_type IN ('dashcam','cctv','social','other')),
        duration_sec    DOUBLE,
        width           INTEGER,
        height          INTEGER,
        fps             DOUBLE,
        codec           VARCHAR,
        file_size_mb    DOUBLE,
        file_hash       VARCHAR,
        phash           VARCHAR,
        recorded_at     TIMESTAMP,
        imported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        thumbnail_path  VARCHAR,
        location_lat    DOUBLE,
        location_lon    DOUBLE,
        notes           VARCHAR,
        status          VARCHAR DEFAULT 'imported'
    );
    """,
    # المشاهد
    """
    CREATE TABLE IF NOT EXISTS scenes (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_scenes_id'),
        video_id        INTEGER REFERENCES videos(id),
        scene_index     INTEGER,
        start_ms        INTEGER,
        end_ms          INTEGER
    );
    """,
    # الكشوفات
    """
    CREATE TABLE IF NOT EXISTS detections (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_detections_id'),
        video_id        INTEGER REFERENCES videos(id),
        frame_no        INTEGER,
        timestamp_ms    INTEGER,
        class_name      VARCHAR,
        confidence      DOUBLE,
        bbox_x1         DOUBLE,
        bbox_y1         DOUBLE,
        bbox_x2         DOUBLE,
        bbox_y2         DOUBLE,
        track_id        INTEGER
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_det_video ON detections(video_id);",
    "CREATE INDEX IF NOT EXISTS idx_det_track ON detections(video_id, track_id);",
    # المخالفات
    """
    CREATE TABLE IF NOT EXISTS violations (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_violations_id'),
        video_id        INTEGER REFERENCES videos(id),
        violation_type  VARCHAR,
        start_ms        INTEGER,
        end_ms          INTEGER,
        confidence      DOUBLE,
        track_id        INTEGER,
        evidence_frames VARCHAR,
        license_plate   VARCHAR,
        plate_conf      DOUBLE,
        review_status   VARCHAR DEFAULT 'pending',
        notes           VARCHAR,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_at     TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_viol_type ON violations(violation_type);",
    "CREATE INDEX IF NOT EXISTS idx_viol_video ON violations(video_id);",
    # ترحيل: عمود مصدر المخالفة (تلقائي/يدوي) — يحافظ على المخالفات اليدوية عند إعادة التحليل
    "ALTER TABLE violations ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'auto';",
    "ALTER TABLE violations ADD COLUMN IF NOT EXISTS manual_user VARCHAR;",
    "CREATE INDEX IF NOT EXISTS idx_viol_source ON violations(source);",
    # المعايرات
    """
    CREATE TABLE IF NOT EXISTS calibrations (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_calibrations_id'),
        video_id        INTEGER REFERENCES videos(id),
        reference_pts   VARCHAR,
        meters_per_px   DOUBLE,
        calibrated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    # المناطق
    """
    CREATE TABLE IF NOT EXISTS zones (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_zones_id'),
        video_id        INTEGER REFERENCES videos(id),
        zone_type       VARCHAR,
        polygon         VARCHAR,
        metadata        VARCHAR
    );
    """,
    # الدراسات المُصدَّرة
    """
    CREATE TABLE IF NOT EXISTS exports (
        id              INTEGER PRIMARY KEY DEFAULT nextval('seq_exports_id'),
        study_name      VARCHAR,
        filter_json     VARCHAR,
        format          VARCHAR,
        output_path     VARCHAR,
        exported_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
)


class Database:
    """مغلِّف اتصال DuckDB مع قفل للوصول الآمن من threads متعددة."""

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        self._db_path = Path(db_path)
        self._read_only = read_only
        self._lock = threading.RLock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection = duckdb.connect(
            database=str(self._db_path),
            read_only=read_only,
        )

    @property
    def path(self) -> Path:
        return self._db_path

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None) -> Any:
        """ينفذ استعلام SQL ويعيد cursor النتيجة."""
        with self._lock:
            if params is None:
                return self._conn.execute(sql)
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        """ينفذ استعلاماً على مجموعة صفوف."""
        with self._lock:
            self._conn.executemany(sql, rows)

    def fetch_one(
        self, sql: str, params: tuple[Any, ...] | list[Any] | None = None
    ) -> tuple[Any, ...] | None:
        """يعيد أول صف من النتيجة، أو None."""
        with self._lock:
            cur = self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)
            return cur.fetchone()

    def fetch_all(
        self, sql: str, params: tuple[Any, ...] | list[Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """يعيد كل الصفوف من النتيجة."""
        with self._lock:
            cur = self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)
            return cur.fetchall()

    def init_schema(self) -> None:
        """ينشئ كل الجداول والفهارس إن لم تكن موجودة."""
        with self._lock:
            for stmt in SCHEMA_STATEMENTS:
                self._conn.execute(stmt)

    def table_exists(self, table_name: str) -> bool:
        """يتحقق من وجود جدول."""
        result = self.fetch_one(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            (table_name,),
        )
        return result is not None

    def list_tables(self) -> list[str]:
        """يعيد قائمة بأسماء الجداول."""
        rows = self.fetch_all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return [row[0] for row in rows]

    def close(self) -> None:
        """يغلق الاتصال."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# ============================================
# مدير اتصال مفرد على مستوى التطبيق
# ============================================
_singleton_lock = threading.Lock()
_singleton: Database | None = None


def get_database(settings: AppSettings | None = None) -> Database:
    """يعيد الاتصال المفرد بقاعدة البيانات (مُهيَّأ بالمخطط)."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            s = settings or get_settings()
            _singleton = Database(s.db_path)
            _singleton.init_schema()
        return _singleton


def reset_database_singleton() -> None:
    """يُغلق الاتصال المفرد ويعيد ضبطه — للاختبارات أساساً."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.close()
            _singleton = None
