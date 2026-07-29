"""خدمة المكتبة — استيراد المقاطع، استخراج البيانات الوصفية، إدارة التكرار."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.constants import (
    DEFAULT_THUMBNAIL_WIDTH,
    SUPPORTED_VIDEO_EXTENSIONS,
    SourceType,
)
from app.core.db import Database, get_database
from app.utils.hash_utils import file_hash, perceptual_hash_from_image_path, phash_distance
from app.utils.video_utils import VideoMetadata, extract_metadata, generate_thumbnail

logger = logging.getLogger(__name__)


def _escape_like(text: str) -> str:
    """يهرّب محارف LIKE الخاصة حتى يبحث المستخدم عن `%` و`_` كنص عادي."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class ImportReport:
    """تقرير ملخّص عن عملية الاستيراد."""

    imported: list[int] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total(self) -> int:
        return len(self.imported) + len(self.duplicates) + len(self.failed) + len(self.skipped)


@dataclass
class DuplicateGroup:
    """مجموعة مقاطع متطابقة."""

    representative_id: int
    duplicate_ids: list[int]
    match_type: str  # "exact" | "perceptual"


@dataclass(frozen=True)
class VideoDetails:
    """تفاصيل مقطع للعرض — حقول مُسمّاة بدل صف tuple بمؤشرات رقمية.

    قراءة `SELECT *` بمؤشرات (row[2]، row[18]…) كانت تنكسر **بصمت** عند أي
    `ALTER TABLE videos ADD COLUMN`: تنزاح المؤشرات وتُعرض قيمة عمود مكان آخر
    بلا أي خطأ. الأعمدة هنا مُسمّاة صراحةً في الاستعلام وفي النوع.
    """

    id: int
    filepath: str
    filename: str
    source_type: str | None
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    file_size_mb: float | None
    recorded_at: object | None
    imported_at: object | None
    status: str | None
    notes: str | None = None


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
        progress_cb: Callable[[int, int, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ImportReport:
        """يستورد ملفاً أو كل مقاطع المجلد."""
        return self.import_paths(
            [path],
            source_type,
            generate_thumbnails=generate_thumbnails,
            progress_cb=progress_cb,
            should_stop=should_stop,
        )

    def import_paths(
        self,
        paths: list[Path | str],
        source_type: SourceType | str = SourceType.OTHER,
        *,
        generate_thumbnails: bool = True,
        progress_cb: Callable[[int, int, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> ImportReport:
        """يستورد عدة ملفات/مجلدات في عملية واحدة بتقرير وتقدّم موحّدين.

        يجمع كل مقاطع الفيديو عبر كل المسارات (مع إزالة التكرار في القائمة نفسها)
        ثم يستوردها دفعةً واحدة — يتجنّب سلوك "استيراد أول ملف فقط" عند الإسقاط المتعدد.

        `should_stop`: تُستطلَع قبل كل ملف؛ عند True نتوقف ونُرجع التقرير الجزئي
        مع `cancelled=True`. الإلغاء هكذا **نتيجة عادية لا استثناء** — الرفع من
        داخل callback التقدّم كان يظهر للمستخدم كـ«فشل الاستيراد».
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
            if should_stop is not None and should_stop():
                report.cancelled = True
                report.skipped.extend(files[index - 1 :])
                break
            if progress_cb is not None:
                progress_cb(index, len(files), file_path.name)
            self._import_single(file_path, source, generate_thumbnails, report)

        logger.info(
            "انتهى الاستيراد%s: %d مُستورد، %d مكرر، %d فاشل",
            " (أُلغي)" if report.cancelled else "",
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
        # بصمة **حتمية** للمسار: `hash()` على النصوص مُلَح عشوائياً لكل عملية
        # تشغيل (PYTHONHASHSEED)، فنفس الملف كان يعطي اسم thumbnail مختلفاً في
        # كل جلسة ويترك ملفات يتيمة تتراكم بلا مرجع.
        digest = hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()[:12]
        thumb_path = thumb_dir / f"{file_path.stem}_{digest}.jpg"
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
        search: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[Any, ...]]:
        """يعيد قائمة المقاطع مع الفلترة الاختيارية.

        `search`: فلترة على اسم الملف **داخل SQL** لا في Python بعد جلب كل
        الصفوف — يتجنّب سحب المكتبة كاملة عند كل حرف يُكتب في مربع البحث.
        """
        sql = "SELECT id, filename, source_type, duration_sec, status, thumbnail_path FROM videos"
        clauses: list[str] = []
        params: list[Any] = []
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search:
            # ESCAPE صريح: بدونه يُعامل DuckDB الـ`\` كمحرف عادي فلا يُهرَّب
            # شيء، وبحث المستخدم عن «100%» يطابق كل شيء.
            clauses.append("filename ILIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(search)}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY imported_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self._db.fetch_all(sql, tuple(params) if params else None)

    def video_names(self) -> list[tuple[int, str]]:
        """(id, filename) لكل المقاطع — لملء القوائم المنسدلة في الواجهة."""
        rows = self._db.fetch_all("SELECT id, filename FROM videos ORDER BY id")
        return [(int(r[0]), str(r[1])) for r in rows]

    def video_filepath(self, video_id: int) -> str | None:
        """مسار ملف المقطع، أو None لو غير موجود."""
        row = self._db.fetch_one("SELECT filepath FROM videos WHERE id = ?", (video_id,))
        return str(row[0]) if row and row[0] else None

    def get_video_details(self, video_id: int) -> VideoDetails | None:
        """تفاصيل مقطع بحقول مُسمّاة (بديل `get_video()` ذي المؤشرات الرقمية)."""
        row = self._db.fetch_one(
            "SELECT id, filepath, filename, source_type, duration_sec, width, height, "
            "fps, codec, file_size_mb, recorded_at, imported_at, status, notes "
            "FROM videos WHERE id = ?",
            (video_id,),
        )
        if row is None:
            return None
        return VideoDetails(
            id=int(row[0]),
            filepath=str(row[1]),
            filename=str(row[2]),
            source_type=str(row[3]) if row[3] is not None else None,
            duration_sec=float(row[4]) if row[4] is not None else None,
            width=int(row[5]) if row[5] is not None else None,
            height=int(row[6]) if row[6] is not None else None,
            fps=float(row[7]) if row[7] is not None else None,
            codec=str(row[8]) if row[8] is not None else None,
            file_size_mb=float(row[9]) if row[9] is not None else None,
            recorded_at=row[10],
            imported_at=row[11],
            status=str(row[12]) if row[12] is not None else None,
            notes=str(row[13]) if row[13] is not None else None,
        )

    def count_videos(self) -> int:
        """عدد المقاطع الكلي."""
        row = self._db.fetch_one("SELECT COUNT(*) FROM videos")
        return int(row[0]) if row else 0

    def total_duration_seconds(self) -> float:
        """مجموع مدة كل المقاطع."""
        row = self._db.fetch_one("SELECT COALESCE(SUM(duration_sec), 0) FROM videos")
        return float(row[0]) if row else 0.0

    def get_video(self, video_id: int) -> tuple[Any, ...] | None:
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

    def delete_video(self, video_id: int, *, audit: bool = True) -> None:
        """يحذف مقطعاً وكل صفوفه المرتبطة (detections/violations/scenes/…) وملف الـ thumbnail.

        DuckDB يفرض القيود المرجعية ولا يدعم ON DELETE CASCADE، فنحذف الأبناء
        يدوياً بترتيب صحيح (child→parent) ثم الأب.

        ملاحظة: لا نلفّها في معاملة صريحة واحدة لأن DuckDB يمنع حذف الأب وأبنائه
        داخل المعاملة نفسها (قيد FK يبقى مرئياً حتى الـ commit). الحذف المتتابع
        بالـ autocommit يفي بالقيد ويطبّق الأبناء قبل الأب.

        ⚠️ **ملف الفيديو الأصلي لا يُحذف** — تُحذف سجلات القاعدة والـthumbnail
        فقط. المقطع (وما فيه من وجوه ولوحات) يبقى على القرص؛ الواجهة تُعلم
        المستخدم بذلك صراحةً عند الحذف.
        """
        row = self._db.fetch_one(
            "SELECT thumbnail_path, filename FROM videos WHERE id = ?", (video_id,)
        )
        thumbnail_path = row[0] if row else None
        filename = str(row[1]) if row and row[1] else str(video_id)

        for table in self._CHILD_TABLES:
            # اسم الجدول من الثابت الداخلي `_CHILD_TABLES` حصراً — لا من مدخل
            # مستخدم إطلاقاً. أي تعديل مستقبلي يجب أن يحافظ على هذا الشرط.
            self._db.execute(f"DELETE FROM {table} WHERE video_id = ?", (video_id,))
        self._db.execute("DELETE FROM videos WHERE id = ?", (video_id,))

        if audit:
            self._db.record_audit(
                entity="video", entity_id=video_id, action="delete", old_value=filename
            )

        if thumbnail_path:
            try:
                Path(thumbnail_path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("تعذّر حذف thumbnail %s: %s", thumbnail_path, exc)

    def video_summaries(self) -> list[tuple[int, str, str, int, int]]:
        """(id, filename, status, عدد الكشوفات، عدد المخالفات) لكل مقطع.

        كان هذا الاستعلام مكتوباً كـSQL خام داخل `analysis_view` و`annotator_view`
        عبر الوصول للـ`_db` الخاص بالخدمة — منطق قاعدة بيانات في طبقة العرض.
        """
        rows = self._db.fetch_all(
            "SELECT v.id, v.filename, v.status, "
            "COALESCE((SELECT COUNT(*) FROM detections d WHERE d.video_id = v.id), 0), "
            "COALESCE((SELECT COUNT(*) FROM violations vi WHERE vi.video_id = v.id), 0) "
            "FROM videos v ORDER BY v.id"
        )
        return [(int(r[0]), str(r[1]), str(r[2]), int(r[3]), int(r[4])) for r in rows]

    def update_source_type(self, video_id: int, source_type: SourceType | str) -> None:
        """يحدّث نوع المصدر."""
        source = source_type.value if isinstance(source_type, SourceType) else source_type
        self._db.execute("UPDATE videos SET source_type = ? WHERE id = ?", (source, video_id))

    # ============================================
    # كشف التكرار
    # ============================================
    # عتبة مسافة Hamming للتشابه البصري (phash بطول 16×16 بت = 256 بت).
    # القيمة محافظة عمداً: كلما ارتفعت زاد التقاط المتشابهات وزادت الإيجابيات
    # الكاذبة. النتائج تُراجَع بشرياً في DuplicatesDialog ولا تُحذف تلقائياً.
    PHASH_MAX_DISTANCE: int = 10

    def detect_duplicates(self, *, phash_max_distance: int | None = None) -> list[DuplicateGroup]:
        """يكشف التكرارات: تطابق ثنائي (file_hash) + تشابه بصري (مسافة phash).

        التشابه البصري يُقاس بمسافة Hamming لا بالتساوي التام: نسختان من نفس
        المقطع بجودة/ترميز مختلف تُعطيان phash **متقارباً لا متطابقاً**، فالتجميع
        بالتساوي كان يفوّت تماماً الحالة التي وُجدت الميزة من أجلها.
        """
        threshold = self.PHASH_MAX_DISTANCE if phash_max_distance is None else phash_max_distance
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

        seen = {gid for g in groups for gid in [g.representative_id, *g.duplicate_ids]}
        rows = self._db.fetch_all(
            "SELECT id, phash FROM videos WHERE phash IS NOT NULL ORDER BY id"
        )
        candidates = [(int(r[0]), str(r[1])) for r in rows if int(r[0]) not in seen]
        groups.extend(self._group_by_phash_distance(candidates, threshold))
        return groups

    @staticmethod
    def _group_by_phash_distance(
        candidates: list[tuple[int, str]], threshold: int
    ) -> list[DuplicateGroup]:
        """يجمّع المقاطع المتقاربة بصرياً (تجميع جشِع حول ممثِّل).

        نمشي بالترتيب: أول مقطع غير مُخصَّص يصير ممثِّلاً، ونضم إليه كل من
        مسافته منه ≤ العتبة. بسيط وحتمي وكافٍ لأحجام مكتبة سطح المكتب.
        """
        assigned: set[int] = set()
        out: list[DuplicateGroup] = []
        for i, (vid, phash) in enumerate(candidates):
            if vid in assigned:
                continue
            members: list[int] = []
            for other_id, other_hash in candidates[i + 1 :]:
                if other_id in assigned:
                    continue
                try:
                    distance = phash_distance(phash, other_hash)
                except (ValueError, TypeError):
                    continue  # phash تالف — نتخطاه بدل إسقاط الفحص كله
                if distance <= threshold:
                    members.append(other_id)
                    assigned.add(other_id)
            if members:
                assigned.add(vid)
                out.append(
                    DuplicateGroup(
                        representative_id=vid,
                        duplicate_ids=members,
                        match_type="perceptual",
                    )
                )
        return out

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
