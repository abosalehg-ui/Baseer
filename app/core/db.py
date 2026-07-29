"""اتصال DuckDB وإدارة المخطط."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from app.config import AppSettings, get_settings

logger = logging.getLogger(__name__)

# ============================================
# تعريف المخطط الأساسي (Schema DDL)
# ============================================
# كل عبارة هنا **idempotent** (IF NOT EXISTS) وتُنفَّذ عند كل إقلاع.
# أي تغيير لاحق على المخطط يذهب إلى MIGRATIONS أدناه، لا هنا.
BASE_SCHEMA: tuple[str, ...] = (
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
    "CREATE INDEX IF NOT EXISTS idx_viol_review ON violations(review_status);",
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
    # جدول تتبّع الترحيلات المُطبَّقة
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version     INTEGER PRIMARY KEY,
        name        VARCHAR NOT NULL,
        applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
)

# متوافق مع الاسم القديم (كان يُصدَّر قبل فصل الترحيلات)
SCHEMA_STATEMENTS: tuple[str, ...] = BASE_SCHEMA


# ============================================
# الترحيلات (Migrations)
# ============================================
# كل ترحيل = (رقم، اسم وصفي، عبارات SQL). تُطبَّق بالترتيب **مرة واحدة** ويُسجَّل
# رقمها في `schema_migrations`. العبارات تبقى idempotent قدر الإمكان حتى يبقى
# إعادة التطبيق على قاعدة قديمة (أُنشئت قبل نظام الترحيل) آمناً.
MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (
        1,
        "violations_source_and_manual_user",
        (
            # مصدر المخالفة (تلقائي/يدوي) — يحافظ على المخالفات اليدوية عند إعادة التحليل
            "ALTER TABLE violations ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'auto';",
            "ALTER TABLE violations ADD COLUMN IF NOT EXISTS manual_user VARCHAR;",
            "CREATE INDEX IF NOT EXISTS idx_viol_source ON violations(source);",
        ),
    ),
    (
        2,
        "audit_log",
        (
            "CREATE SEQUENCE IF NOT EXISTS seq_audit_id START 1;",
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY DEFAULT nextval('seq_audit_id'),
                entity      VARCHAR NOT NULL,
                entity_id   INTEGER,
                action      VARCHAR NOT NULL,
                old_value   VARCHAR,
                new_value   VARCHAR,
                actor       VARCHAR,
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);",
        ),
    ),
)


class Database:
    """مغلِّف اتصال DuckDB مع قفل للوصول الآمن من threads متعددة."""

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        self._db_path = Path(db_path)
        self._read_only = read_only
        self._lock = threading.RLock()
        self._in_transaction = False
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._connect_with_wal_recovery()

    def _connect_with_wal_recovery(self) -> duckdb.DuckDBPyConnection:
        """يفتح اتصال DuckDB ويتعافى تلقائياً من WAL تالف من crash سابق.

        DuckDB يحتفظ بـ `<db>.wal` لمعاملات لم تُكتب بعد. لو حدث crash
        (مثل PermissionError قبل تطبيق PR #19)، يبقى الملف بحالة فاسدة
        وعند فتح DB لاحقاً يفشل بـ InternalException على replay.
        نُسلك:
        1) محاولة فتح طبيعية
        2) لو فشل بسبب WAL، ننقل `.wal` لـ `.wal.broken-<ts>` ونعيد المحاولة
        3) لا نلمس ملف DB الرئيسي — البيانات الملتزمة تبقى محفوظة
        """
        try:
            return duckdb.connect(database=str(self._db_path), read_only=self._read_only)
        except duckdb.Error as exc:
            msg = str(exc)
            wal_path = self._db_path.with_suffix(self._db_path.suffix + ".wal")
            if "wal" not in msg.lower() or not wal_path.exists():
                raise
            import time

            backup = wal_path.with_suffix(f".wal.broken-{int(time.time())}")
            logger.warning(
                "WAL فاسد في %s — نُنحّيه إلى %s ونعيد فتح القاعدة (البيانات الملتزمة سليمة)",
                wal_path,
                backup.name,
            )
            try:
                wal_path.rename(backup)
            except OSError as rename_err:
                logger.error("تعذّر نقل WAL: %s — حاول الحذف اليدوي", rename_err)
                raise
            return duckdb.connect(database=str(self._db_path), read_only=self._read_only)

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
            row: tuple[Any, ...] | None = cur.fetchone()
            return row

    def fetch_all(
        self, sql: str, params: tuple[Any, ...] | list[Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """يعيد كل الصفوف من النتيجة."""
        with self._lock:
            cur = self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)
            rows: list[tuple[Any, ...]] = cur.fetchall()
            return rows

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """يلفّ مجموعة عمليات في معاملة واحدة — إما تنجح كلها أو لا شيء.

        يمنع الحالات الوسطى مثل «حُذفت المخالفات القديمة ثم فشل إدراج الجديدة».
        القفل مُعاد الدخول (RLock) فالاستدعاءات المتداخلة لـ`execute` داخل الكتلة
        تعمل من نفس الـthread بلا مشاكل.

        تحذير: DuckDB يفرض القيود المرجعية عند الـcommit لا عند العبارة، فحذف
        صف أب وأبنائه داخل معاملة واحدة يفشل — استخدم autocommit المتتابع هناك
        (انظر `LibraryService.delete_video`).

        مثال:
            with db.transaction():
                db.execute("DELETE FROM violations WHERE video_id = ?", (vid,))
                db.executemany("INSERT INTO violations ...", rows)
        """
        with self._lock:
            if self._in_transaction:
                # معاملة متداخلة: نتركها للمعاملة الخارجية (لا savepoints هنا)
                yield self
                return
            self._conn.begin()
            self._in_transaction = True
            try:
                yield self
            except BaseException:
                try:
                    self._conn.rollback()
                finally:
                    self._in_transaction = False
                raise
            self._conn.commit()
            self._in_transaction = False

    def init_schema(self) -> None:
        """ينشئ المخطط الأساسي ثم يطبّق الترحيلات غير المُطبَّقة."""
        with self._lock:
            for stmt in BASE_SCHEMA:
                self._conn.execute(stmt)
            self._apply_migrations()

    def _apply_migrations(self) -> None:
        """يطبّق كل ترحيل لم يُسجَّل رقمه في `schema_migrations`."""
        applied = {
            int(r[0])
            for r in self._conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for version, name, statements in MIGRATIONS:
            if version in applied:
                continue
            for stmt in statements:
                self._conn.execute(stmt)
            self._conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name)
            )
            logger.info("طُبِّق الترحيل %d — %s", version, name)

    def applied_migrations(self) -> list[int]:
        """أرقام الترحيلات المُطبَّقة (للتشخيص والاختبارات)."""
        rows = self.fetch_all("SELECT version FROM schema_migrations ORDER BY version")
        return [int(r[0]) for r in rows]

    def record_audit(
        self,
        *,
        entity: str,
        entity_id: int | None,
        action: str,
        old_value: str | None = None,
        new_value: str | None = None,
        actor: str | None = None,
    ) -> None:
        """يسجّل حدثاً في سجل التدقيق — لا يرفع استثناءً أبداً.

        سجل التدقيق مساعد وليس جزءاً من المسار الحرج: فشل الكتابة فيه يجب ألا
        يُسقط العملية الأصلية (تحديث مراجعة، حذف مخالفة…).
        """
        try:
            self.execute(
                "INSERT INTO audit_log (entity, entity_id, action, old_value, new_value, actor) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entity, entity_id, action, old_value, new_value, actor or current_actor()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("تعذّر كتابة سجل التدقيق (%s/%s): %s", entity, action, exc)

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
# هوية المُنفِّذ (للتدقيق)
# ============================================
def current_actor() -> str:
    """اسم مستخدم نظام التشغيل الحالي — يُستعمل كـ«مُنفِّذ» في سجل التدقيق.

    ⚠️ هذه **ليست هوية مُصادَقاً عليها**: التطبيق محلي أحادي المستخدم بلا نظام
    دخول، والقيمة تأتي من بيئة العملية فيمكن انتحالها. تُستخدم كأثر تشغيلي
    مساعد فقط، لا كإثبات لسلسلة عهدة. (موثَّق في README قسم «الخصوصية».)
    """
    import getpass

    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


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
