"""أدوات استخراج بيانات الفيديو عبر FFmpeg/ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class VideoMetadata:
    """بيانات وصفية أساسية للمقطع."""

    filepath: Path
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    file_size_mb: float
    recorded_at: datetime | None


class FFmpegNotFoundError(RuntimeError):
    """يُرفع عند عدم وجود FFmpeg/ffprobe في PATH."""


def _require_ffprobe() -> str:
    """يتحقق من وجود ffprobe ويعيد مساره."""
    path = shutil.which("ffprobe")
    if path is None:
        raise FFmpegNotFoundError(
            "ffprobe غير موجود في PATH — ثبّت FFmpeg أولاً وتأكد من إضافته للمتغيرات."
        )
    return path


def probe_video(filepath: Path | str) -> dict:
    """يعيد ناتج ffprobe بصيغة JSON خام."""
    ffprobe = _require_ffprobe()
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"الملف غير موجود: {path}")
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"فشل ffprobe: {result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def _parse_fps(rate: str | None) -> float | None:
    """يحوّل تعبير الـ FPS (مثل '30000/1001') إلى رقم."""
    if not rate or rate == "0/0":
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            n, d = float(num), float(den)
            return n / d if d else None
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def _parse_recorded_at(tags: dict) -> datetime | None:
    """يستخرج وقت التسجيل من tags الفيديو."""
    candidates = ("creation_time", "com.apple.quicktime.creationdate", "date")
    for key in candidates:
        raw = tags.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
    return None


def extract_metadata(filepath: Path | str) -> VideoMetadata:
    """يستخرج البيانات الوصفية للمقطع."""
    path = Path(filepath)
    info = probe_video(path)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

    duration_raw = fmt.get("duration")
    duration = float(duration_raw) if duration_raw is not None else None
    size_bytes = float(fmt.get("size", 0) or 0)

    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    codec = video_stream.get("codec_name") if video_stream else None
    fps = _parse_fps(video_stream.get("avg_frame_rate") if video_stream else None)
    if fps is None and video_stream:
        fps = _parse_fps(video_stream.get("r_frame_rate"))

    tags = (fmt.get("tags") or {}) | ((video_stream or {}).get("tags") or {})
    recorded_at = _parse_recorded_at(tags)

    return VideoMetadata(
        filepath=path,
        duration_sec=duration,
        width=width,
        height=height,
        fps=fps,
        codec=codec,
        file_size_mb=round(size_bytes / (1024 * 1024), 2),
        recorded_at=recorded_at,
    )
