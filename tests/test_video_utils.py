"""اختبارات أدوات الفيديو — بوابة كل الاستيراد وكانت بتغطية 25%.

تحليل ناتج ffprobe ومهل التنفيذ قابلان للاختبار بـJSON مُثبَّت بلا FFmpeg حقيقي.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.video_utils import (
    FFMPEG_TIMEOUT_SEC,
    FFPROBE_TIMEOUT_SEC,
    FFmpegNotFoundError,
    _parse_fps,
    _parse_recorded_at,
    extract_metadata,
    generate_thumbnail,
    probe_video,
)


# ============================================
# تحليل FPS
# ============================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30/1", 30.0),
        ("30000/1001", pytest.approx(29.97, abs=0.01)),
        ("25", 25.0),
        ("0/0", None),
        ("", None),
        (None, None),
        ("abc", None),
        ("30/0", None),  # قسمة على صفر
        ("x/y", None),
    ],
)
def test_parse_fps(raw, expected) -> None:
    assert _parse_fps(raw) == expected


# ============================================
# تحليل وقت التسجيل
# ============================================
def test_parse_recorded_at_iso() -> None:
    result = _parse_recorded_at({"creation_time": "2026-03-01T08:30:00.000000Z"})
    assert isinstance(result, datetime)
    assert result.year == 2026 and result.month == 3


def test_parse_recorded_at_apple_key() -> None:
    result = _parse_recorded_at({"com.apple.quicktime.creationdate": "2025-12-31T23:59:59+03:00"})
    assert isinstance(result, datetime)
    assert result.year == 2025


@pytest.mark.parametrize(
    "tags",
    [{}, {"creation_time": ""}, {"creation_time": "not-a-date"}, {"other": "2026-01-01"}],
)
def test_parse_recorded_at_returns_none_on_bad_input(tags) -> None:
    assert _parse_recorded_at(tags) is None


# ============================================
# probe_video — الأخطاء والمهل
# ============================================
def test_probe_video_requires_ffprobe(tmp_path: Path) -> None:
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    with patch("app.utils.video_utils.shutil.which", return_value=None):
        with pytest.raises(FFmpegNotFoundError):
            probe_video(video)


def test_probe_video_missing_file(tmp_path: Path) -> None:
    with patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffprobe"):
        with pytest.raises(FileNotFoundError):
            probe_video(tmp_path / "ghost.mp4")


def test_probe_video_timeout_raises_clear_error(tmp_path: Path) -> None:
    """مهلة التنفيذ تمنع تعليق العملية على ملف تالف/مُصاغ خصيصاً."""
    video = tmp_path / "hang.mp4"
    video.write_bytes(b"x")
    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffprobe"),
        patch(
            "app.utils.video_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=FFPROBE_TIMEOUT_SEC),
        ),
    ):
        with pytest.raises(RuntimeError, match="المهلة"):
            probe_video(video)


def test_probe_video_passes_timeout_argument(tmp_path: Path) -> None:
    video = tmp_path / "ok.mp4"
    video.write_bytes(b"x")

    class _Result:
        returncode = 0
        stdout = "{}"
        stderr = ""

    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("app.utils.video_utils.subprocess.run", return_value=_Result()) as run_mock,
    ):
        probe_video(video)
    assert run_mock.call_args.kwargs["timeout"] == FFPROBE_TIMEOUT_SEC


def test_probe_video_invalid_json(tmp_path: Path) -> None:
    video = tmp_path / "bad.mp4"
    video.write_bytes(b"x")

    class _Result:
        returncode = 0
        stdout = "{not json"
        stderr = ""

    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("app.utils.video_utils.subprocess.run", return_value=_Result()),
    ):
        with pytest.raises(RuntimeError, match="غير صالح"):
            probe_video(video)


def test_probe_video_nonzero_exit(tmp_path: Path) -> None:
    video = tmp_path / "err.mp4"
    video.write_bytes(b"x")

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "Invalid data found"

    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffprobe"),
        patch("app.utils.video_utils.subprocess.run", return_value=_Result()),
    ):
        with pytest.raises(RuntimeError, match="فشل ffprobe"):
            probe_video(video)


# ============================================
# extract_metadata من ناتج ffprobe مُثبَّت
# ============================================
_PROBE_OUTPUT = {
    "format": {
        "duration": "125.4",
        "size": "10485760",
        "tags": {"creation_time": "2026-03-01T08:30:00.000000Z"},
    },
    "streams": [
        {"codec_type": "audio", "codec_name": "aac"},
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30000/1001",
        },
    ],
}


def test_extract_metadata_full(tmp_path: Path) -> None:
    video = tmp_path / "full.mp4"
    video.write_bytes(b"x")
    with patch("app.utils.video_utils.probe_video", return_value=_PROBE_OUTPUT):
        meta = extract_metadata(video)

    assert meta.duration_sec == pytest.approx(125.4)
    assert (meta.width, meta.height) == (1920, 1080)
    assert meta.codec == "h264"
    assert meta.fps == pytest.approx(29.97, abs=0.01)
    assert meta.file_size_mb == pytest.approx(10.0)
    assert meta.recorded_at is not None and meta.recorded_at.year == 2026


def test_extract_metadata_falls_back_to_r_frame_rate(tmp_path: Path) -> None:
    video = tmp_path / "fallback.mp4"
    video.write_bytes(b"x")
    payload = json.loads(json.dumps(_PROBE_OUTPUT))
    payload["streams"][1]["avg_frame_rate"] = "0/0"
    payload["streams"][1]["r_frame_rate"] = "25/1"

    with patch("app.utils.video_utils.probe_video", return_value=payload):
        meta = extract_metadata(video)
    assert meta.fps == 25.0


def test_extract_metadata_audio_only(tmp_path: Path) -> None:
    """ملف بلا مسار فيديو لا يُسقط الاستيراد."""
    video = tmp_path / "audio.m4a"
    video.write_bytes(b"x")
    payload = {"format": {"duration": "10", "size": "1024"}, "streams": [{"codec_type": "audio"}]}

    with patch("app.utils.video_utils.probe_video", return_value=payload):
        meta = extract_metadata(video)
    assert meta.width is None and meta.height is None and meta.fps is None
    assert meta.duration_sec == 10.0


def test_extract_metadata_empty_probe(tmp_path: Path) -> None:
    video = tmp_path / "empty.mp4"
    video.write_bytes(b"x")
    with patch("app.utils.video_utils.probe_video", return_value={}):
        meta = extract_metadata(video)
    assert meta.duration_sec is None
    assert meta.file_size_mb == 0.0


# ============================================
# generate_thumbnail
# ============================================
def test_generate_thumbnail_requires_ffmpeg(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with patch("app.utils.video_utils.shutil.which", return_value=None):
        with pytest.raises(FFmpegNotFoundError):
            generate_thumbnail(video, tmp_path / "t.jpg")


def test_generate_thumbnail_timeout(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch(
            "app.utils.video_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=FFMPEG_TIMEOUT_SEC),
        ),
    ):
        with pytest.raises(RuntimeError, match="المهلة"):
            generate_thumbnail(video, tmp_path / "t.jpg")


def test_generate_thumbnail_success(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    dst = tmp_path / "out" / "t.jpg"

    class _Result:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"jpeg")
        return _Result()

    with (
        patch("app.utils.video_utils.shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("app.utils.video_utils.subprocess.run", side_effect=_fake_run),
    ):
        result = generate_thumbnail(video, dst, timestamp_sec=2.5, width=320)
    assert result == dst and dst.exists()
