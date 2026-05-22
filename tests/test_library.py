"""اختبارات خدمة المكتبة."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppSettings
from app.constants import SourceType
from app.core.db import Database
from app.core.library import LibraryService
from app.utils.video_utils import VideoMetadata


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        db_path=tmp_path / "data" / "results.duckdb",
        log_file=tmp_path / "logs" / "baseer.log",
    )


@pytest.fixture()
def service(tmp_db: Database, settings: AppSettings) -> LibraryService:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    return LibraryService(db=tmp_db, settings=settings)


def _fake_meta(path: Path) -> VideoMetadata:
    return VideoMetadata(
        filepath=path,
        duration_sec=12.5,
        width=1920,
        height=1080,
        fps=29.97,
        codec="h264",
        file_size_mb=8.5,
        recorded_at=datetime(2025, 1, 1, 10, 0, 0),
    )


def test_iter_video_files_filters_by_extension(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "c.MKV").write_bytes(b"x")

    files = list(LibraryService._iter_video_files(tmp_path))
    names = {f.name for f in files}
    assert names == {"a.mp4", "c.MKV"}


def test_import_single_file_inserts_row(tmp_path: Path, service: LibraryService) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"\x00" * 1024)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *a, **k: a[1]),
        patch("app.core.library.perceptual_hash_from_image_path", return_value="deadbeef" * 4),
    ):
        report = service.import_path(video, SourceType.DASHCAM)

    assert len(report.imported) == 1
    assert service.count_videos() == 1
    row = service.get_video(report.imported[0])
    assert row is not None
    assert row[1].endswith("sample.mp4")
    assert row[3] == SourceType.DASHCAM.value


def test_reimport_same_path_is_skipped(tmp_path: Path, service: LibraryService) -> None:
    video = tmp_path / "dup.mp4"
    video.write_bytes(b"\x00" * 2048)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *a, **k: a[1]),
        patch("app.core.library.perceptual_hash_from_image_path", return_value="aa" * 8),
    ):
        first = service.import_path(video, SourceType.OTHER)
        second = service.import_path(video, SourceType.OTHER)

    assert len(first.imported) == 1
    assert len(second.skipped) == 1
    assert service.count_videos() == 1


def test_duplicate_detection_by_file_hash(tmp_path: Path, service: LibraryService) -> None:
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    payload = b"identical content" * 256
    a.write_bytes(payload)
    b.write_bytes(payload)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *args, **kw: args[1]),
        patch("app.core.library.perceptual_hash_from_image_path", side_effect=["a", "b"]),
    ):
        r1 = service.import_path(a, SourceType.DASHCAM)
        r2 = service.import_path(b, SourceType.DASHCAM)

    assert len(r1.imported) == 1
    assert len(r2.duplicates) == 1
    assert service.count_videos() == 1


def test_list_videos_filters_by_source_type(tmp_path: Path, service: LibraryService) -> None:
    a = tmp_path / "dash.mp4"
    b = tmp_path / "cctv.mp4"
    a.write_bytes(b"AAAA" * 256)
    b.write_bytes(b"BBBB" * 256)

    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *args, **kw: args[1]),
        patch("app.core.library.perceptual_hash_from_image_path", side_effect=["aa", "bb"]),
    ):
        service.import_path(a, SourceType.DASHCAM)
        service.import_path(b, SourceType.CCTV)

    dash = service.list_videos(source_type="dashcam")
    cctv = service.list_videos(source_type="cctv")
    assert len(dash) == 1 and dash[0][1] == "dash.mp4"
    assert len(cctv) == 1 and cctv[0][1] == "cctv.mp4"


def test_update_source_type(tmp_path: Path, service: LibraryService) -> None:
    video = tmp_path / "x.mp4"
    video.write_bytes(b"xxxx" * 256)
    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *args, **kw: args[1]),
        patch("app.core.library.perceptual_hash_from_image_path", return_value="cc" * 8),
    ):
        report = service.import_path(video, SourceType.OTHER)

    vid = report.imported[0]
    service.update_source_type(vid, SourceType.SOCIAL)
    row = service.get_video(vid)
    assert row is not None
    assert row[3] == SourceType.SOCIAL.value


def test_total_duration_sums_all_videos(tmp_path: Path, service: LibraryService) -> None:
    for i in range(3):
        f = tmp_path / f"v{i}.mp4"
        f.write_bytes(f"DATA-{i}".encode() * 256)
    with (
        patch("app.core.library.extract_metadata", side_effect=_fake_meta),
        patch("app.core.library.generate_thumbnail", side_effect=lambda *args, **kw: args[1]),
        patch(
            "app.core.library.perceptual_hash_from_image_path",
            side_effect=[f"{i}{i}" * 8 for i in range(3)],
        ),
    ):
        service.import_path(tmp_path, SourceType.DASHCAM)

    assert service.total_duration_seconds() == pytest.approx(12.5 * 3)
