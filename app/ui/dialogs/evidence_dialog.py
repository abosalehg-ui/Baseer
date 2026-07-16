"""حوار مستعرض أدلة المخالفة — يعرض إطارات الإثبات ويقفز بالمشغّل إلى وقت المخالفة.

يستفيد من البيانات المحفوظة أصلاً (evidence_frames + start_ms) دون أي حساب جديد.
استخراج الإطارات قابل للحقن لاختبار المنطق بلا فيديو حقيقي.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.db import Database, get_database

logger = logging.getLogger(__name__)


def evidence_frame_numbers(evidence_frames_json: str | None) -> list[int]:
    """يفك ترميز عمود evidence_frames (JSON list) إلى أرقام إطارات."""
    if not evidence_frames_json:
        return []
    try:
        data = json.loads(evidence_frames_json)
    except (ValueError, TypeError):
        return []
    out: list[int] = []
    for item in data if isinstance(data, list) else []:
        try:
            out.append(int(item))
        except (ValueError, TypeError):
            continue
    return out


def extract_evidence_images(
    video_path: str,
    frame_nos: list[int],
    *,
    provider_factory: Callable[[str], object] | None = None,
    max_frames: int = 6,
) -> list[np.ndarray]:
    """يستخرج إطارات الإثبات كمصفوفات BGR (قابل للحقن عبر provider_factory)."""
    if not frame_nos:
        return []
    if provider_factory is not None:
        provider = provider_factory(video_path)
    else:
        try:
            from app.core.frame_sampler import FrameSampler

            provider = FrameSampler(video_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("تعذّر فتح الفيديو لاستخراج الأدلة: %s", exc)
            return []

    images: list[np.ndarray] = []
    try:
        for frame_no in frame_nos[:max_frames]:
            frame = provider.get_frame(frame_no)  # type: ignore[attr-defined]
            if frame is not None:
                images.append(frame)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    return images


class EvidenceDialog(QDialog):
    """يعرض أدلة مخالفة: إطارات إثبات مصغّرة + مشغّل يقفز إلى بداية المخالفة."""

    def __init__(
        self,
        violation_id: int,
        *,
        db: Database | None = None,
        provider_factory: Callable[[str], object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db or get_database()
        self._provider_factory = provider_factory
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"أدلة المخالفة #{violation_id}")
        self.setMinimumSize(760, 560)
        self._row = self._load_violation(violation_id)
        self._build_ui()

    def _load_violation(self, violation_id: int) -> dict | None:
        row = self._db.fetch_one(
            "SELECT vi.id, vi.video_id, v.filepath, v.filename, vi.violation_type, "
            "vi.start_ms, vi.end_ms, vi.evidence_frames, vi.license_plate, vi.notes, v.fps "
            "FROM violations vi JOIN videos v ON v.id = vi.video_id WHERE vi.id = ?",
            (violation_id,),
        )
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "video_id": int(row[1]),
            "filepath": str(row[2]) if row[2] else "",
            "filename": str(row[3]) if row[3] else "",
            "violation_type": str(row[4]),
            "start_ms": int(row[5] or 0),
            "end_ms": int(row[6] or 0),
            "evidence_frames": row[7],
            "license_plate": row[8],
            "notes": row[9],
            "fps": float(row[10]) if row[10] else 30.0,
        }

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        if self._row is None:
            root.addWidget(QLabel("المخالفة غير موجودة.", self))
            return

        root.addWidget(QLabel(self._summary_text(), self))

        # مشغّل الفيديو (يقفز إلى بداية المخالفة) — يتدهور بأمان لو تعذّر
        player = self._try_build_player()
        if player is not None:
            root.addWidget(player, stretch=1)

        root.addWidget(QLabel("إطارات الإثبات:", self))
        root.addWidget(self._build_thumbnails(), stretch=1)

        close_btn = QPushButton("إغلاق", self)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)

    def _summary_text(self) -> str:
        assert self._row is not None
        plate = self._row["license_plate"] or "—"
        return (
            f"<b>الملف:</b> {self._row['filename']} &nbsp;|&nbsp; "
            f"<b>البداية:</b> {self._row['start_ms']} ms &nbsp;|&nbsp; "
            f"<b>اللوحة:</b> {plate}<br>{self._row['notes'] or ''}"
        )

    def _try_build_player(self) -> QWidget | None:
        assert self._row is not None
        filepath = self._row["filepath"]
        if not filepath or not Path(filepath).exists():
            return None
        try:
            from app.ui.widgets.video_player import VideoPlayer

            player = VideoPlayer(self)
            player.load(filepath)
            player.seek(self._row["start_ms"])
            return player
        except Exception as exc:  # noqa: BLE001
            logger.warning("تعذّر بناء مشغّل الأدلة: %s", exc)
            return None

    def _build_thumbnails(self) -> QWidget:
        assert self._row is not None
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        container = QWidget()
        layout = QHBoxLayout(container)

        frame_nos = evidence_frame_numbers(self._row["evidence_frames"])
        images = extract_evidence_images(
            self._row["filepath"], frame_nos, provider_factory=self._provider_factory
        )
        if not images:
            layout.addWidget(QLabel("لا تتوفّر إطارات إثبات.", container))
        else:
            for frame, image in zip(frame_nos, images, strict=False):
                layout.addWidget(self._thumb_widget(frame, image, container))
        layout.addStretch()
        area.setWidget(container)
        return area

    @staticmethod
    def _thumb_widget(frame_no: int, bgr: np.ndarray, parent: QWidget) -> QWidget:
        from app.ui.dialogs.zone_editor_dialog import numpy_bgr_to_qimage

        box = QWidget(parent)
        col = QVBoxLayout(box)
        label = QLabel(box)
        qimg: QImage = numpy_bgr_to_qimage(bgr)
        pix = QPixmap.fromImage(qimg).scaledToWidth(200, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pix)
        col.addWidget(label)
        cap = QLabel(f"إطار {frame_no}", box)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(cap)
        return box


__all__ = ["EvidenceDialog", "evidence_frame_numbers", "extract_evidence_images"]
