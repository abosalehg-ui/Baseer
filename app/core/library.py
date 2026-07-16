"""خدمة المكتبة — استيراد المقاطع، استخراج البيانات الوصفية، إدارة التكرار."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.config import AppSettings, get_settings
from app.constants import (
    DEFAULT_THUMBNAIL_WIDTH,
    SUPPORTED_VIDEO_EXTENSIONS,
    SourceType,
)
from app.core.db import Database, get_database
from app.utils.hash_utils import file_hash, perceptual_hash_from_image_path
from app.utils.video_utils import VideoMetadata, extract_metadata, generate_thumbnail

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """تقرير ملخّص عن عملية الاستيراد."""

    imported: list[int] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.imported) + len(self.duplicates) + len(self.failed) + len(self.skipped)


@dataclass
class DuplicateGroup:
    """مجموعة مقاطع متطابقة."""

    representative_id: int
    duplicate_ids: list[int]
    match_type: str  # "exact" | "perceptual"


class LibraryService:
    """خدمة إدارة مكتبة المقاطع."""

    def __init__(
        self,
        *,
        db: Database | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._db = db or get_database(self._settings)

    # ============================================
    # الاستيراد
    # ============================================
    def import_path(
        self,
        path: Path | str,
        source_type: SourceType | str = SourceType.OTHER,
        *,
        generate_thumbnails: bool = True,
        progress_cb: callable | None = None,
    ) -> ImportReport:
        """يستورد ملفاً أو كل مقاطع المجلد."""
        return self.import_paths(
            [path],
            source_type,
            generate_thumbnails=generate_thumbnails,
            progress_cb=progress_cb,
        )

    def import_paths(
        self,
        paths: list[Path | str],
        source_type: SourceType | str = SourceType.OTHER,
        *,
        generate_thumbnails: bool = True,
        progress_cb: callable | None = None,
    ) -> ImportReport:
        """يستورد عدة ملفات/مجلدات في عملية واحدة بتقرير وتقدّم موحّدين.

        يجمع كل مقاطع الفيديو عبر كل المسارات (مع إزالة التكرار في القائمة نفسها)
        ثم يستوردها دفعةً واحدة — يتجنّب سلوك "استيراد أول ملف فقط" عند الإسقاط المتعدد.
        """
        report = ImportReport()
        source = source_type.value if isinstance(source_type, SourceType) else source_type

        files: list[Path] = []
        seen: set[Path] = set()
        for path in paths:
            for file_path in self._iter_video_files(Path(path)):
                resolved = file_path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                files.append(file_path)

        for index, file_path in enumerate(files, start=1):
            if progress_cb is not None:
                progress_cb(index, len(files), file_path.name)
            self._import_single(file_path, source, generate_thumbnails, report)

        logger.info(
            "انتهى الاستيراد: %d مُستورد، %d مكرر، %d فاشل",
            len(report.imported),
            len(report.duplicates),
            len(report.failed),
        )
        return report

    def _import_single(
        self,
        file_path: Path,
        source: str,
        generate_thumbnails: bool,
        report: ImportReport,
    ) -> None:
        """يستورد ملفاً واحداً مع كل الفحوصات."""
        abs_path = str(file_path.resolve())
        existing = self._db.fetch_one("SELECT id FROM videos WHERE filepath = ?", (abs_path,))
        if existing is not None:
            report.skipped.append(file_path)
            return

        try:
            meta = extract_metadata(file_path)
            fhash = file_hash(file_path)
            phash: str | None = None
            thumb_path: Path | None = None

            if generate_thumbnails:
                thumb_path = self._build_thumbnail(file_path, meta)
                if thumb_path is not None:
                    try:
                        phash = perceptual_hash_from_image_path(thumb_path)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("فشل حساب phash لـ %s: %s", file_path.name, exc)

            if self._is_exact_duplicate(fhash):
                report.duplicates.append(file_path)
                return

            video_id = self._insert_video(file_path, source, meta, fhash, phash, thumb_path)
            report.imported.append(video_id)

        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل استيراد %s", file_path)
            report.failed.append((file_path, str(exc)))

    def _build_thumbnail(self, file_path: Path, meta: VideoMetadata) -> Path | None:
        """يولّد thumbnail ويعيد مساره أو None عند الفشل."""
        thumb_dir = self._settings.data_dir / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{file_path.stem}_{abs(hash(str(file_path)))}.jpg"
        timestamp = 1.0 if (meta.duration_sec or 0) > 2 else 0.0
        try:
            generate_thumbnail(
                file_path, thumb_path, timestamp_sec=timestamp, width=DEFAULT_THUMBNAIL_WIDTH
            )
            return thumb_path
        except Exception as exc:  # noqa: BLE001
            logger.warning("فشل توليد thumbnail لـ %s: %s", file_path.name, exc)
            return None

    def _insert_video(
        self,
        file_path: Path,
        source: str,
        meta: VideoMetadata,
        fhash: str,
        phash: str | None,
        thumb_path: Path | None,
    ) -> int:
        """يُدرج سجل المقطع في قاعدة البيانات ويعيد المعرف."""
        self._db.execute(
            """
            INSERT INTO videos (
                filepath, filename, source_type,
                duration_sec, width, height, fps, codec,
                file_size_mb, file_hash, phash,
                recorded_at, thumbnail_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(file_path.resolve()),
                file_path.name,
                source,
                meta.duration_sec,
                meta.width,
                meta.height,
                meta.fps,
                meta.codec,
                meta.file_size_mb,
                fhash,
                phash,
                meta.recorded_at,
                str(thumb_path) if thumb_path else None,
            ),
        )
        row = self._db.fetch_one(
            "SELECT id FROM videos WHERE filepath = ?", (str(file_path.resolve()),)
        )
        assert row is not None
        return int(row[0])

    def _is_exact_duplicate(self, fhash: str) -> bool:
        """يفحص التكرار الثنائي الحقيقي (file_hash) فقط — أساس الإسقاط التلقائي الآمن.

        التكرار الحسّي (phash) لا يُسقط المقطع تلقائياً لتجنّب رفض مقاطع CCTV
        المختلفة من كاميرا ثابتة بصمت؛ يُعرض بدلاً من ذلك في `detect_duplicates()`
        للمراجعة البشرية.
        """
        return self._db.fetch_one("SELECT id FROM videos WHERE file_hash = ?", (fhash,)) is not None

    # ============================================
    # الاستعلام والإدارة
    # ============================================
    def list_videos(
        self,
        *,
        source_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[tuple]:
        """يعيد قائمة المقاطع مع الفلترة الاختيارية."""
        sql = "SELECT id, filename, source_type, duration_sec, status, thumbnail_path FROM videos"
        clauses: list[str] = []
        params: list = []
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY imported_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._db.fetch_all(sql, tuple(params) if params else None)

    def count_videos(self) -> int:
        """عدد المقاطع الكلي."""
        row = self._db.fetch_one("SELECT COUNT(*) FROM videos")
        return int(row[0]) if row else 0

    def total_duration_seconds(self) -> float:
        """مجموع مدة كل المقاطع."""
        row = self._db.fetch_one("SELECT COALESCE(SUM(duration_sec), 0) FROM videos")
        return float(row[0]) if row else 0.0

    def get_video(self, video_id: int) -> tuple | None:
        """يعيد كل بيانات المقطع."""
        return self._db.fetch_one("SELECT * FROM videos WHERE id = ?", (video_id,))

    # الجداول الأبناء التي تشير إلى videos(id) — تُحذف قبل الأب.
    # DuckDB يفرض القيود المرجعية ولا يدعم ON DELETE CASCADE، فنحذف يدوياً.
    _CHILD_TABLES: tuple[str, ...] = (
        "detections",
        "violations",
        "scenes",
        "calibrations",
        "zones",
    )

    def delete_video(self, video_id: int) -> None:
        """يحذف مقطعاً وكل صفوفه المرتبطة (detections/violations/scenes/…) وملف الـ thumbnail.

        DuckDB يفرض القيود المرجعية ولا يدعم ON DELETE CASCADE، فنحذف الأبناء
        يدوياً بترتيب صحيح (child→parent) ثم الأب.

        ملاحظة: لا نلفّها في معاملة صريحة واحدة لأن DuckDB يمنع حذف الأب وأبنائه
        داخل المعاملة نفسها (قيد FK يبقى مرئياً حتى الـ commit). الحذف المتتابع
        بالـ autocommit يفي بالقيد ويطبّق الأبناء قبل الأب.
        """
        thumb_row = self._db.fetch_one(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        )
        thumbnail_path = thumb_row[0] if thumb_row else None

        for table in self._CHILD_TABLES:
            self._db.execute(f"DELETE FROM {table} WHERE video_id = ?", (video_id,))
        self._db.execute("DELETE FROM videos WHERE id = ?", (video_id,))

        if thumbnail_path:
            try:
                Path(thumbnail_path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("تعذّر حذف thumbnail %s: %s", thumbnail_path, exc)

    def update_source_type(self, video_id: int, source_type: SourceType | str) -> None:
        """يحدّث نوع المصدر."""
        source = source_type.value if isinstance(source_type, SourceType) else source_type
        self._db.execute("UPDATE videos SET source_type = ? WHERE id = ?", (source, video_id))

    # ============================================
    # كشف التكرار
    # ============================================
    def detect_duplicates(self) -> list[DuplicateGroup]:
        """يكشف التكرارات بناءً على file_hash و phash."""
        groups: list[DuplicateGroup] = []

        exact = self._db.fetch_all(
            "SELECT file_hash, ARRAY_AGG(id ORDER BY id) "
            "FROM videos WHERE file_hash IS NOT NULL "
            "GROUP BY file_hash HAVING COUNT(*) > 1"
        )
        for _hash, ids in exact:
            ids_list = list(ids)
            groups.append(
                DuplicateGroup(
                    representative_id=int(ids_list[0]),
                    duplicate_ids=[int(i) for i in ids_list[1:]],
                    match_type="exact",
                )
            )

        perceptual = self._db.fetch_all(
            "SELECT phash, ARRAY_AGG(id ORDER BY id) "
            "FROM videos WHERE phash IS NOT NULL "
            "GROUP BY phash HAVING COUNT(*) > 1"
        )
        seen = {gid for g in groups for gid in [g.representative_id, *g.duplicate_ids]}
        for _hash, ids in perceptual:
            ids_list = [int(i) for i in ids if int(i) not in seen]
            if len(ids_list) > 1:
                groups.append(
                    DuplicateGroup(
                        representative_id=ids_list[0],
                        duplicate_ids=ids_list[1:],
                        match_type="perceptual",
                    )
                )
        return groups

    # ============================================
    # مساعدات داخلية
    # ============================================
    @staticmethod
    def _iter_video_files(path: Path) -> Iterator[Path]:
        """يمشي على الملفات أو المجلد ويعيد مقاطع الفيديو فقط."""
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                yield path
            return
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                    yield child
